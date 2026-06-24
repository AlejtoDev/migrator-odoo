from odoo import models, fields


class AuditFieldFinding(models.Model):
    _name = 'audit.field.finding'
    _description = 'Campo custom detectado en auditoría'
    _order = 'model_name, name'

    project_id = fields.Many2one('audit.project', required=True, ondelete='cascade')
    name = fields.Char(string='Nombre técnico', required=True)
    field_description = fields.Char(string='Etiqueta')
    model_name = fields.Char(string='Modelo')
    field_type = fields.Char(string='Tipo de campo')
    field_origin = fields.Selection([
        ('studio', 'Odoo Studio (x_studio_*)'),
        ('custom_dev', 'Desarrollo custom (x_*)'),
        ('other_manual', 'Otro campo manual'),
    ], string='Origen')
    has_data = fields.Boolean(string='Tiene datos')
    record_count_with_value = fields.Integer(string='Registros con valor')
    migration_decision = fields.Selection([
        ('migrate', 'Migrar'),
        ('recreate_studio', 'Recrear en Studio'),
        ('drop', 'Eliminar'),
        ('pending', 'Pendiente'),
    ], string='Decisión', default='pending')
    effort_hours = fields.Float(string='Horas estimadas')
    notes = fields.Text(string='Notas del consultor')
