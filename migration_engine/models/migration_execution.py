import re
import logging
import traceback as tb

from odoo import models, fields
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class MigrationExecution(models.AbstractModel):
    _name = 'migration.execution'
    _description = 'Motor ETL con savepoints'
    _auto = False

    def run(self, job, dry_run=False):
        seq = self.env['ir.sequence'].next_by_code('migration.execution.run') or '/'
        base_name = f'{seq} — {job.name}'
        run_vals = {
            'name': f'[DRY RUN] {base_name}' if dry_run else base_name,
            'job_id': job.id,
            'dry_run': dry_run,
            'state': 'running',
            'execution_date': fields.Datetime.now(),
        }

        if not dry_run:
            run = self.env['migration.execution.run'].create(run_vals)

        job.write({'state': 'running'})

        SourceModel = self.env[job.source_model_id.model]
        domain = safe_eval(job.domain or '[]')
        records = SourceModel.search(domain)

        pending_entries = []
        has_errors = has_warnings = False

        if dry_run:
            global_sp = f'migration_dry_{job.id}_{fields.Datetime.now().strftime("%H%M%S%f")}'
            self.env.cr.execute(f'SAVEPOINT {global_sp}')

        for record in records:
            result, log_list = self._process_record(job, record, dry_run)
            if dry_run:
                pending_entries.append((result, log_list))
            if result == 'error':
                has_errors = True
            elif result == 'warning':
                has_warnings = True

        if dry_run:
            self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {global_sp}')
            self.env.invalidate_all()
            run = self.env['migration.execution.run'].create(run_vals)
            for _result, log_list in pending_entries:
                for log_vals in log_list:
                    self.env['migration.log'].create({
                        'execution_run_id': run.id,
                        'job_id': job.id,
                        'dry_run': True,
                        'execution_date': fields.Datetime.now(),
                        'was_rollback': False,
                        **log_vals,
                    })

        final_state = 'error' if has_errors else 'partial' if has_warnings else 'done'
        run.write({'state': final_state, 'end_date': fields.Datetime.now()})
        job.write({'state': final_state})
        return run

    # ------------------------------------------------------------------
    # Procesamiento de un registro
    # ------------------------------------------------------------------

    def _process_record(self, job, record, dry_run):
        """
        Retorna (result, log_list).
        En modo real, los logs se persisten aquí mismo via _flush_logs.
        En dry_run, se devuelven para que run() los persista tras el ROLLBACK global.
        """
        collected_logs = []

        # FASE 1: Validación
        validation_result, validation_logs = self._validate_record(job, record)
        collected_logs.extend(validation_logs)
        if validation_result == 'fatal':
            if not dry_run:
                self._flush_logs(job, collected_logs)
            return 'error', collected_logs

        # FASE 2: Mapeo dinámico
        try:
            vals = self._apply_field_maps(job, record)
        except Exception as e:
            collected_logs.append({
                'log_type': 'error',
                'source_record_id_int': record.id,
                'source_model': record._name,
                'message': f'Error en mapeo de campos: {e}',
                'traceback': tb.format_exc(),
                'execution_date': fields.Datetime.now(),
            })
            if not dry_run:
                self._flush_logs(job, collected_logs)
            return 'error', collected_logs

        # FASE 3: Resolución del registro destino
        dest_record = None
        if job.mode in ('update_only', 'create_or_update'):
            dest_record = self._resolve_dest_record(job, record, vals)
            if not dest_record and job.mode == 'update_only':
                collected_logs.append({
                    'log_type': 'warning',
                    'source_record_id_int': record.id,
                    'source_model': record._name,
                    'message': 'Modo update_only: no se encontró registro destino. Omitido.',
                    'execution_date': fields.Datetime.now(),
                })
                if not dry_run:
                    self._flush_logs(job, collected_logs)
                return 'warning', collected_logs

        # FASE 4: Dry run — registrar intención sin modificar datos
        if dry_run:
            action = 'UPDATE' if dest_record else 'CREATE'
            collected_logs.append({
                'log_type': 'info' if not validation_logs else 'warning',
                'source_record_id_int': record.id,
                'source_model': record._name,
                'message': f'[DRY RUN] {action} procesable. Vals: {vals}',
                'execution_date': fields.Datetime.now(),
            })
            return ('warning' if validation_logs else 'ok'), collected_logs

        # FASE 5: Ejecución transaccional con savepoint
        DestModel = self.env[job.dest_model_id.model]
        sp = f'migration_sp_{record.id}_{fields.Datetime.now().strftime("%f")}'
        self.env.cr.execute(f'SAVEPOINT {sp}')
        try:
            if dest_record:
                dest_record.write(vals)
            else:
                DestModel.create(vals)
            self.env.cr.execute(f'RELEASE SAVEPOINT {sp}')

            log_type = 'warning' if validation_logs else 'info'
            suffix = f' (con {len(validation_logs)} warning(s))' if validation_logs else ''
            collected_logs.append({
                'log_type': log_type,
                'source_record_id_int': record.id,
                'source_model': record._name,
                'message': f'Registro migrado correctamente{suffix}',
                'execution_date': fields.Datetime.now(),
            })
            self._flush_logs(job, collected_logs)
            return ('warning' if validation_logs else 'ok'), collected_logs

        except Exception as e:
            self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp}')
            self.env.invalidate_all()
            collected_logs.append({
                'log_type': 'error',
                'source_record_id_int': record.id,
                'source_model': record._name,
                'message': f'Error en create/write: {e}',
                'traceback': tb.format_exc(),
                'was_rollback': True,
                'execution_date': fields.Datetime.now(),
            })
            self._flush_logs(job, collected_logs)
            return 'error', collected_logs

    def _flush_logs(self, job, log_list):
        active_run = job.execution_run_ids.filtered(lambda r: r.state == 'running')[:1]
        if not active_run:
            return
        for log_vals in log_list:
            self.env['migration.log'].create({
                'execution_run_id': active_run.id,
                'job_id': job.id,
                'dry_run': False,
                'execution_date': fields.Datetime.now(),
                'was_rollback': False,
                **log_vals,
            })

    # ------------------------------------------------------------------
    # Validación
    # ------------------------------------------------------------------

    def _validate_record(self, job, record):
        pending_logs = []
        for rule in job.rule_ids.filtered('active').sorted('sequence'):
            try:
                field_value = record[rule.field_id.name]
                passed = self._evaluate_rule(rule, field_value, record)
                if not passed:
                    log_vals = {
                        'log_type': 'warning' if rule.on_failure == 'warning' else 'error',
                        'source_record_id_int': record.id,
                        'source_model': record._name,
                        'field_name': rule.field_id.name,
                        'rule_name': rule.name,
                        'message': f"Regla '{rule.name}' falló en campo '{rule.field_id.name}'",
                    }
                    if rule.on_failure == 'error':
                        pending_logs.append(log_vals)
                        return 'fatal', pending_logs
                    pending_logs.append(log_vals)
            except Exception as e:
                pending_logs.append({
                    'log_type': 'error',
                    'source_record_id_int': record.id,
                    'source_model': record._name,
                    'field_name': rule.field_id.name,
                    'rule_name': rule.name,
                    'message': f"Excepción evaluando regla '{rule.name}': {e}",
                    'traceback': tb.format_exc(),
                })
                return 'fatal', pending_logs
        return 'ok', pending_logs

    def _evaluate_rule(self, rule, value, record):
        if rule.rule_type == 'not_null':
            return bool(value) or value == 0
        elif rule.rule_type == 'type_check':
            return value is not None
        elif rule.rule_type == 'format_regex':
            return bool(re.match(rule.regex_pattern or '', str(value or '')))
        elif rule.rule_type == 'python_expr':
            local_dict = {'value': value, 'record': record, 'env': self.env}
            return bool(safe_eval(rule.python_expr, local_dict))
        return True

    # ------------------------------------------------------------------
    # Mapeo de campos
    # ------------------------------------------------------------------

    def _apply_field_maps(self, job, record):
        vals = {}
        for fmap in job.field_map_ids.sorted('sequence'):
            source_val = record[fmap.source_field_id.name] if fmap.source_field_id else None
            dest_field = fmap.dest_field_id.name
            dest_field_type = fmap.dest_field_id.ttype

            try:
                if fmap.transform_type == 'direct':
                    transformed = source_val
                elif fmap.transform_type == 'fixed_value':
                    transformed = fmap.fixed_value
                elif fmap.transform_type == 'python_expr':
                    local_dict = {'value': source_val, 'record': record, 'env': self.env}
                    transformed = safe_eval(fmap.python_expr, local_dict)
                elif fmap.transform_type == 'lookup':
                    LookupModel = self.env[fmap.lookup_model_id.model]
                    lookup_rec = LookupModel.search(
                        [(fmap.lookup_source_field_id.name, '=', source_val)], limit=1
                    )
                    transformed = lookup_rec[fmap.lookup_dest_field_id.name] if lookup_rec else False
                else:
                    transformed = source_val

                if dest_field_type == 'many2one' and hasattr(transformed, 'id'):
                    transformed = transformed.id

                vals[dest_field] = transformed

            except Exception as e:
                if fmap.required:
                    raise ValueError(
                        f"Mapeo requerido '{fmap.source_field_id.name}' → '{dest_field}' falló: {e}"
                    ) from e
                _logger.warning(
                    'migration_engine: campo no-required omitido: %s → %s: %s',
                    fmap.source_field_id.name if fmap.source_field_id else '?',
                    dest_field,
                    str(e),
                )

        return vals

    # ------------------------------------------------------------------
    # Resolución de registro destino
    # ------------------------------------------------------------------

    def _resolve_dest_record(self, job, source_record, vals):
        if not job.key_field_ids:
            return False

        DestModel = self.env[job.dest_model_id.model]
        domain = []
        for key_field in job.key_field_ids:
            field_name = key_field.name
            value = vals.get(field_name, source_record[field_name])
            if hasattr(value, 'id'):
                value = value.id
            domain.append((field_name, '=', value))

        return DestModel.search(domain, limit=1)
