import logging
import uuid

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

EFFORT_MODULE = {
    'custom': (8.0, 20.0),
    'oca': (2.0, 4.0),
    'enterprise': (1.0, 2.0),
    'localization': (2.0, 6.0),
    'odoo_official': (0.0, 0.0),
    'unknown': (1.0, 3.0),
}
EFFORT_FIELD = {
    'studio': 1.0,
    'custom_dev': 2.0,
    'other_manual': 1.5,
}
EFFORT_MODEL_BASE = 16.0
EFFORT_MODEL_PER_FIELD = 0.5
EFFORT_VOLUME = {'low': 0.0, 'medium': 4.0, 'high': 10.0}
EFFORT_FIXED = [
    ('testing', 'Testing y validación post-migración', 8.0),
    ('training', 'Capacitación al equipo del cliente', 4.0),
]


class RunAuditWizard(models.TransientModel):
    _name = 'run.audit.wizard'
    _description = 'Asistente de escaneo de auditoría'

    project_id = fields.Many2one('audit.project', required=True, readonly=True)
    audit_mode = fields.Selection(related='project_id.audit_mode', readonly=True)
    backup_file = fields.Binary(string='Archivo de backup')
    backup_filename = fields.Char(string='Nombre del archivo')
    scan_modules = fields.Boolean(default=True, string='Escanear módulos instalados')
    scan_fields = fields.Boolean(default=True, string='Escanear campos custom/Studio')
    scan_models = fields.Boolean(default=True, string='Escanear modelos custom')
    scan_volume = fields.Boolean(default=True, string='Escanear volumen de datos')
    generate_effort = fields.Boolean(default=True, string='Generar estimación automáticamente')
    scan_log = fields.Text(readonly=True)
    scan_done = fields.Boolean(default=False)

    def action_scan(self):
        self.ensure_one()
        project = self.project_id
        log_lines = []

        def log(msg):
            log_lines.append(msg)
            _logger.info('[AuditScan] %s', msg)

        try:
            project.write({'state': 'scanning'})
            project.module_finding_ids.unlink()
            project.field_finding_ids.unlink()
            project.model_finding_ids.unlink()
            project.volume_finding_ids.unlink()

            if project.audit_mode == 'xmlrpc':
                self._scan_xmlrpc(project, log)
            else:
                self._scan_backup(project, log)

            if self.generate_effort:
                self._generate_effort_lines(project, log)

            project.write({'state': 'done', 'scan_date': fields.Datetime.now()})
            log('✓ Escaneo completado.')

        except Exception as e:
            import traceback
            project.write({'state': 'error'})
            log(f'✗ Error durante el escaneo: {e}')
            log(traceback.format_exc())

        self.write({'scan_log': '\n'.join(log_lines), 'scan_done': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    # ── Modo A: XML-RPC ────────────────────────────────────────────────────

    def _scan_xmlrpc(self, project, log):
        from ..services.xmlrpc_client import OdooXmlRpcClient
        conn = project.connection_id
        if not conn:
            raise UserError('El proyecto no tiene credenciales XML-RPC configuradas.')

        log(f'Conectando a {conn.url} / {conn.database}...')
        client = OdooXmlRpcClient(conn.url, conn.database, conn.username, conn.password)

        version = client.get_server_version()
        project.write({'odoo_version_detected': version.get('server_version', '')})
        log(f'Versión detectada: {version.get("server_version")}')

        if self.scan_modules:
            log('Escaneando módulos...')
            self._create_module_findings(project, client.get_installed_modules(), log)

        if self.scan_fields:
            log('Escaneando campos custom...')
            self._create_field_findings_xmlrpc(project, client.get_custom_fields(), client, log)

        if self.scan_models:
            log('Escaneando modelos custom...')
            self._create_model_findings_xmlrpc(project, client.get_custom_models(), client, log)

        if self.scan_volume:
            log('Midiendo volumen de datos...')
            self._create_volume_findings_xmlrpc(project, client, log)

    # ── Modo B: Backup ─────────────────────────────────────────────────────

    def _scan_backup(self, project, log):
        from ..services.backup_processor import BackupProcessor, SCHEMA_PREFIX
        import base64

        if not self.backup_file:
            raise UserError('Debes subir el archivo de backup antes de escanear.')

        file_bytes = base64.b64decode(self.backup_file)
        filename = self.backup_filename or 'backup'
        log(f'Archivo recibido: {filename} ({len(file_bytes) / 1024 / 1024:.1f} MB)')

        fmt = BackupProcessor.detect_format(filename, file_bytes)
        log(f'Formato detectado: {fmt}')

        backup_rec = self.env['audit.backup'].create({
            'name': f'Backup — {project.client_name}',
            'backup_filename': filename,
            'backup_format': fmt,
            'state': 'processing',
        })
        project.write({'backup_id': backup_rec.id})

        schema_name = f'{SCHEMA_PREFIX}{project.id}_{uuid.uuid4().hex[:8]}'
        backup_rec.write({'schema_name': schema_name})

        dsn = self._get_own_dsn()
        processor = BackupProcessor(dsn, schema_name)

        try:
            processor.create_schema()
            log(f'Schema temporal creado: {schema_name}')

            if fmt == 'zip_odoo':
                log('Extrayendo dump del zip...')
                dump_bytes, manifest = BackupProcessor.extract_dump_from_zip(file_bytes)
                log(f'Manifest versión: {manifest.get("odoo_version", "no encontrada")}')
                project.write({
                    'odoo_version_detected': manifest.get('odoo_version', ''),
                    'is_enterprise': 'enterprise' in str(manifest).lower(),
                })
                inner_fmt = BackupProcessor.detect_format('dump', dump_bytes)
            else:
                dump_bytes = file_bytes
                inner_fmt = fmt

            if inner_fmt == 'pg_custom':
                log('Importando dump pg_custom (usando pg_restore)...')
                processor.import_pg_custom_dump(dump_bytes, log_callback=log)
            else:
                log('Importando dump SQL...')
                processor.import_sql_dump(dump_bytes, log_callback=log)

            if not project.odoo_version_detected:
                ver = processor.get_odoo_version()
                project.write({'odoo_version_detected': ver})
                log(f'Versión Odoo detectada en dump: {ver}')

            backup_rec.write({'state': 'ready', 'processed_date': fields.Datetime.now()})

            if self.scan_modules:
                log('Escaneando módulos...')
                self._create_module_findings(project, processor.get_installed_modules(), log)

            if self.scan_fields:
                log('Escaneando campos custom...')
                self._create_field_findings_backup(project, processor.get_custom_fields(), processor, log)

            if self.scan_models:
                log('Escaneando modelos custom...')
                self._create_model_findings_backup(project, processor.get_custom_models(), processor, log)

            if self.scan_volume:
                log('Midiendo volumen de datos...')
                self._create_volume_findings_backup(project, processor, log)

        finally:
            try:
                processor.drop_schema()
                backup_rec.write({'state': 'cleaned', 'schema_name': False})
                log(f'Schema temporal {schema_name} eliminado.')
            except Exception as e:
                log(f'[WARN] No se pudo eliminar el schema: {e}')
            processor.close()

    def _get_own_dsn(self):
        from odoo.tools import config
        db_host = config.get('db_host', 'localhost')
        db_port = config.get('db_port', 5432)
        db_user = config.get('db_user', 'odoo')
        db_password = config.get('db_password', '')
        db_name = self.env.cr.dbname
        parts = [f'dbname={db_name}', f'user={db_user}', f'host={db_host}', f'port={db_port}']
        if db_password:
            parts.append(f'password={db_password}')
        return ' '.join(parts)

    # ── Categorización ────────────────────────────────────────────────────

    def _detect_module_category(self, mod):
        name = mod.get('name', '')
        author = (mod.get('author') or '').lower()
        ENTERPRISE = {
            'web_enterprise', 'account_reports', 'account_accountant',
            'sale_subscription', 'sale_renting', 'sign', 'documents',
            'quality_control', 'maintenance', 'helpdesk', 'studio',
            'social', 'marketing_automation', 'voip', 'whatsapp',
        }
        OFFICIAL_PREFIXES = (
            'account', 'sale', 'purchase', 'stock', 'mrp', 'project',
            'hr', 'mail', 'web', 'base', 'bus', 'auth', 'calendar',
            'crm', 'lunch', 'fleet', 'point_of_sale', 'website',
            'payment', 'delivery', 'repair', 'survey',
        )
        if name in ENTERPRISE:
            return 'enterprise'
        if name.startswith('l10n_'):
            return 'localization'
        if 'oca' in author or 'odoo community association' in author:
            return 'oca'
        if 'odoo s.a.' in author or 'odoo sa' in author:
            return 'odoo_official'
        if any(name.startswith(p) for p in OFFICIAL_PREFIXES):
            return 'odoo_official'
        return 'custom'

    def _detect_field_origin(self, field_name):
        if field_name.startswith('x_studio_'):
            return 'studio'
        if field_name.startswith('x_'):
            return 'custom_dev'
        return 'other_manual'

    # ── Creación de findings ───────────────────────────────────────────────

    def _create_module_findings(self, project, modules, log):
        for mod in modules:
            self.env['audit.module.finding'].create({
                'project_id': project.id,
                'name': mod['name'],
                'display_name_module': mod.get('shortdesc') or mod.get('display_name_module') or mod['name'],
                'author': mod.get('author') or '',
                'version': mod.get('installed_version') or '',
                'module_category': self._detect_module_category(mod),
            })
        log(f'  → {len(modules)} módulos registrados')

    def _create_field_findings_xmlrpc(self, project, fields_data, client, log):
        for f in fields_data:
            model_id = f.get('model_id')
            model_name = model_id[1] if isinstance(model_id, list) else f.get('model_name', '')
            count = client.get_field_value_count(model_name, f['name']) if model_name else -1
            self.env['audit.field.finding'].create({
                'project_id': project.id,
                'name': f['name'],
                'field_description': f.get('field_description', ''),
                'model_name': model_name,
                'field_type': f.get('ttype', ''),
                'field_origin': self._detect_field_origin(f['name']),
                'has_data': count > 0,
                'record_count_with_value': max(count, 0),
            })
        log(f'  → {len(fields_data)} campos custom registrados')

    def _create_field_findings_backup(self, project, fields_data, processor, log):
        for f in fields_data:
            model_name = f.get('model_name', '')
            count = processor.get_field_value_count(model_name, f['name']) if model_name else -1
            self.env['audit.field.finding'].create({
                'project_id': project.id,
                'name': f['name'],
                'field_description': f.get('field_description', ''),
                'model_name': model_name,
                'field_type': f.get('ttype', ''),
                'field_origin': self._detect_field_origin(f['name']),
                'has_data': count > 0,
                'record_count_with_value': max(count, 0),
            })
        log(f'  → {len(fields_data)} campos custom registrados')

    def _create_model_findings_xmlrpc(self, project, models_data, client, log):
        for m in models_data:
            count = client.get_record_count(m['model'])
            self.env['audit.model.finding'].create({
                'project_id': project.id,
                'name': m['model'],
                'description': m.get('name') or m.get('info') or '',
                'field_count': len(m.get('field_id', [])),
                'record_count': max(count, 0),
            })
        log(f'  → {len(models_data)} modelos custom registrados')

    def _create_model_findings_backup(self, project, models_data, processor, log):
        for m in models_data:
            count = processor.get_record_count(m['model'])
            self.env['audit.model.finding'].create({
                'project_id': project.id,
                'name': m['model'],
                'description': m.get('name') or m.get('info') or '',
                'field_count': m.get('field_count', 0),
                'record_count': max(count, 0),
            })
        log(f'  → {len(models_data)} modelos custom registrados')

    def _create_volume_findings_xmlrpc(self, project, client, log):
        from ..models.audit_volume_finding import VOLUME_MODELS
        for model_name, display in VOLUME_MODELS:
            count = client.get_record_count(model_name)
            if count < 0:
                continue
            tier = 'high' if count >= 100000 else 'medium' if count >= 10000 else 'low'
            self.env['audit.volume.finding'].create({
                'project_id': project.id,
                'model_name': model_name,
                'display_name': display,
                'record_count': count,
                'volume_tier': tier,
                'effort_extra_hours': EFFORT_VOLUME[tier],
            })
        log('  → Volumen de datos registrado')

    def _create_volume_findings_backup(self, project, processor, log):
        from ..models.audit_volume_finding import VOLUME_MODELS
        for model_name, display in VOLUME_MODELS:
            if not processor.table_exists(model_name):
                continue
            count = processor.get_record_count(model_name)
            if count < 0:
                continue
            tier = 'high' if count >= 100000 else 'medium' if count >= 10000 else 'low'
            self.env['audit.volume.finding'].create({
                'project_id': project.id,
                'model_name': model_name,
                'display_name': display,
                'record_count': count,
                'volume_tier': tier,
                'effort_extra_hours': EFFORT_VOLUME[tier],
            })
        log('  → Volumen de datos registrado')

    # ── Generación de effort lines ─────────────────────────────────────────

    def _generate_effort_lines(self, project, log):
        project.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()
        lines = []

        for mod in project.module_finding_ids.filtered('is_relevant'):
            min_h, max_h = EFFORT_MODULE.get(mod.module_category, (1.0, 3.0))
            h = (min_h + max_h) / 2
            cat = 'custom_module' if mod.module_category == 'custom' else 'oca_module'
            lines.append({
                'category': cat,
                'description': f'Módulo: {mod.display_name_module or mod.name}',
                'estimated_hours': h,
                'reference': mod.name,
                'source': 'auto',
            })
            mod.write({'effort_hours': h})

        studio_fields = project.field_finding_ids.filtered(lambda f: f.field_origin == 'studio')
        custom_fields = project.field_finding_ids.filtered(lambda f: f.field_origin == 'custom_dev')

        if studio_fields:
            lines.append({
                'category': 'studio_fields',
                'description': f'Campos Studio (x_studio_*): {len(studio_fields)} campos',
                'estimated_hours': len(studio_fields) * EFFORT_FIELD['studio'],
                'reference': 'x_studio_*',
                'source': 'auto',
            })
        if custom_fields:
            lines.append({
                'category': 'studio_fields',
                'description': f'Campos custom (x_*): {len(custom_fields)} campos',
                'estimated_hours': len(custom_fields) * EFFORT_FIELD['custom_dev'],
                'reference': 'x_*',
                'source': 'auto',
            })

        for model in project.model_finding_ids:
            h = EFFORT_MODEL_BASE + (model.field_count * EFFORT_MODEL_PER_FIELD)
            lines.append({
                'category': 'custom_model',
                'description': f'Modelo custom: {model.name} ({model.field_count} campos, {model.record_count} registros)',
                'estimated_hours': h,
                'reference': model.name,
                'source': 'auto',
            })
            model.write({'effort_hours': h})

        volume_extra = sum(project.volume_finding_ids.mapped('effort_extra_hours'))
        if volume_extra > 0:
            lines.append({
                'category': 'data_volume',
                'description': 'Optimización ETL por volumen de datos',
                'estimated_hours': volume_extra,
                'reference': 'volumen',
                'source': 'auto',
            })

        for category, desc, hours in EFFORT_FIXED:
            lines.append({'category': category, 'description': desc,
                          'estimated_hours': hours, 'source': 'auto'})

        subtotal = sum(l['estimated_hours'] for l in lines)
        contingency = round(subtotal * 0.10, 1)
        lines.append({
            'category': 'contingency',
            'description': f'Contingencia 10% ({subtotal:.1f}h base)',
            'estimated_hours': contingency,
            'source': 'auto',
        })

        seq = 10
        for line_vals in lines:
            product = project._get_product_for_line(line_vals.get('category', 'other'))
            self.env['audit.effort.line'].create({
                'project_id': project.id,
                'sequence': seq,
                'product_id': product.id if product else False,
                **line_vals,
            })
            seq += 10

        log(f'  → {len(lines)} líneas de esfuerzo generadas. Total: {subtotal + contingency:.1f}h')
