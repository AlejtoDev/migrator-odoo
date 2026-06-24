from odoo import models, fields


class MigrationLog(models.Model):
    _name = 'migration.log'
    _description = 'Log de evento de migración'
    _order = 'execution_date desc, id desc'

    execution_run_id = fields.Many2one(
        'migration.execution.run',
        string='Ejecución',
        required=True,
        ondelete='cascade',
    )
    job_id = fields.Many2one(
        'migration.job',
        string='Trabajo',
        related='execution_run_id.job_id',
        store=True,
    )
    execution_date = fields.Datetime(string='Fecha/Hora')
    log_type = fields.Selection([
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ], string='Tipo', required=True, default='info')
    source_record_id_int = fields.Integer(string='ID origen')
    source_model = fields.Char(string='Modelo origen')
    field_name = fields.Char(string='Campo')
    rule_name = fields.Char(string='Regla')
    message = fields.Text(string='Mensaje')
    traceback = fields.Text(string='Traceback')
    was_rollback = fields.Boolean(string='Revertido')
    dry_run = fields.Boolean(string='Dry Run')
