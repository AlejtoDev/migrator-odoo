from odoo import models, fields


class AuditModelFinding(models.Model):
    _name = 'audit.model.finding'
    _description = 'Modelo custom detectado en auditoría'
    _order = 'name'

    project_id = fields.Many2one('audit.project', required=True, ondelete='cascade')
    name = fields.Char(string='Nombre técnico', required=True)
    description = fields.Char(string='Descripción')
    field_count = fields.Integer(string='Cantidad de campos')
    record_count = fields.Integer(string='Registros')
    has_menu = fields.Boolean(string='Tiene menú')
    migration_decision = fields.Selection([
        ('migrate_full', 'Migrar completo'),
        ('migrate_data_only', 'Solo datos'),
        ('drop', 'Eliminar'),
        ('pending', 'Pendiente'),
    ], string='Decisión', default='pending')
    effort_hours = fields.Float(string='Horas estimadas')
    notes = fields.Text(string='Notas del consultor')
