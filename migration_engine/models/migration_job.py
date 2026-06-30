from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval


class MigrationJob(models.Model):
    _name = 'migration.job'
    _description = 'Trabajo de migración ETL'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True)
    source_model_id = fields.Many2one('ir.model', string='Modelo origen', required=True, ondelete='cascade')
    dest_model_id = fields.Many2one('ir.model', string='Modelo destino', required=True, ondelete='cascade')
    domain = fields.Char(string='Dominio de filtro', default='[]')
    mode = fields.Selection([
        ('create_only', 'Solo crear'),
        ('update_only', 'Solo actualizar'),
        ('create_or_update', 'Crear o actualizar'),
    ], string='Modo', default='create_only', required=True)
    key_field_ids = fields.Many2many(
        'ir.model.fields',
        'migration_job_key_fields_rel',
        'job_id',
        'field_id',
        string='Campos clave',
        domain="[('model_id', '=', source_model_id)]",
    )
    field_map_ids = fields.One2many('migration.field.map', 'job_id', string='Mapeo de campos')
    rule_ids = fields.One2many('migration.rule', 'job_id', string='Reglas de validación')
    execution_run_ids = fields.One2many('migration.execution.run', 'job_id', string='Ejecuciones')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('running', 'Ejecutando'),
        ('done', 'Completado'),
        ('partial', 'Parcial'),
        ('error', 'Error'),
    ], string='Estado', default='draft', required=True)
    last_run = fields.Datetime(string='Última ejecución', compute='_compute_last_run', store=True)
    total_runs = fields.Integer(string='Total ejecuciones', compute='_compute_total_runs', store=True)
    notes = fields.Text(string='Notas internas')

    @api.depends('execution_run_ids', 'execution_run_ids.execution_date')
    def _compute_last_run(self):
        for job in self:
            last = job.execution_run_ids.sorted('execution_date', reverse=True)[:1]
            job.last_run = last.execution_date if last else False

    @api.depends('execution_run_ids')
    def _compute_total_runs(self):
        for job in self:
            job.total_runs = len(job.execution_run_ids)

    def action_run(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ejecutar migración',
            'res_model': 'run.migration.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_job_id': self.id},
        }

    def action_view_runs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Historial de ejecuciones',
            'res_model': 'migration.execution.run',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
        }
