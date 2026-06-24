import csv
import io
import base64
from odoo import models, fields, api


class MigrationExecutionRun(models.Model):
    _name = 'migration.execution.run'
    _description = 'Ejecución de trabajo de migración'
    _order = 'execution_date desc'

    name = fields.Char(string='Nombre', required=True, default='Nueva ejecución')
    job_id = fields.Many2one('migration.job', string='Trabajo', required=True, ondelete='cascade')
    execution_date = fields.Datetime(string='Inicio', default=fields.Datetime.now)
    end_date = fields.Datetime(string='Fin')
    dry_run = fields.Boolean(string='Dry Run')
    state = fields.Selection([
        ('running', 'Ejecutando'),
        ('done', 'Completado'),
        ('partial', 'Parcial'),
        ('error', 'Error'),
    ], string='Estado', default='running', required=True)
    log_ids = fields.One2many('migration.log', 'execution_run_id', string='Logs')
    total_records = fields.Integer(string='Total registros', compute='_compute_counts', store=True)
    success_count = fields.Integer(string='OK', compute='_compute_counts', store=True)
    warning_count = fields.Integer(string='Warnings', compute='_compute_counts', store=True)
    error_count = fields.Integer(string='Errores', compute='_compute_counts', store=True)
    duration_seconds = fields.Float(string='Duración (seg)', compute='_compute_duration', store=True)

    @api.depends('log_ids', 'log_ids.log_type')
    def _compute_counts(self):
        for run in self:
            logs = run.log_ids
            run.total_records = len(logs)
            run.success_count = len(logs.filtered(lambda l: l.log_type == 'info'))
            run.warning_count = len(logs.filtered(lambda l: l.log_type == 'warning'))
            run.error_count = len(logs.filtered(lambda l: l.log_type == 'error'))

    @api.depends('execution_date', 'end_date')
    def _compute_duration(self):
        for run in self:
            if run.execution_date and run.end_date:
                delta = run.end_date - run.execution_date
                run.duration_seconds = delta.total_seconds()
            else:
                run.duration_seconds = 0.0

    def action_export_logs_csv(self):
        self.ensure_one()

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL)

        writer.writerow([
            'Fecha',
            'Tipo',
            'Dry Run',
            'Modelo Origen',
            'ID Origen',
            'Campo',
            'Regla',
            'Mensaje',
            'Rollback',
            'Traceback',
        ])

        for log in self.log_ids.sorted('execution_date'):
            writer.writerow([
                log.execution_date.strftime('%Y-%m-%d %H:%M:%S') if log.execution_date else '',
                log.log_type,
                'Sí' if log.dry_run else 'No',
                log.source_model,
                log.source_record_id_int,
                log.field_name or '',
                log.rule_name or '',
                log.message or '',
                'Sí' if log.was_rollback else 'No',
                (log.traceback or '').replace('\n', ' | '),
            ])

        csv_content = output.getvalue()
        output.close()

        ts = self.execution_date.strftime('%Y%m%d_%H%M%S') if self.execution_date else 'export'
        filename = f'migration_logs_{self.job_id.name}_{ts}.csv'

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(csv_content.encode('utf-8')),
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
