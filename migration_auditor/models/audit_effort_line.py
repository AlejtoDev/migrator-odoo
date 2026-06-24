from odoo import models, fields, api


class AuditEffortLine(models.Model):
    _name = 'audit.effort.line'
    _description = 'Línea de estimación de horas para migración'
    _order = 'project_id, sequence'

    project_id = fields.Many2one('audit.project', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Secuencia', default=10)
    category = fields.Selection([
        ('analysis', 'Análisis previo'),
        ('custom_module', 'Módulo custom'),
        ('oca_module', 'Módulo OCA'),
        ('studio_fields', 'Campos Studio / custom'),
        ('custom_model', 'Modelo custom'),
        ('data_volume', 'Volumen de datos'),
        ('testing', 'Testing'),
        ('training', 'Capacitación'),
        ('contingency', 'Contingencia'),
        ('other', 'Otro'),
    ], string='Categoría', required=True)
    description = fields.Char(string='Descripción', required=True)
    source = fields.Selection([
        ('auto', 'Generado automáticamente'),
        ('manual', 'Manual'),
    ], string='Origen', default='manual')
    estimated_hours = fields.Float(string='Horas estimadas')
    unit_price = fields.Float(
        string='Tarifa hora',
        related='project_id.hourly_rate',
        readonly=True,
    )
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)
    reference = fields.Char(string='Referencia')

    @api.depends('estimated_hours', 'unit_price')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.estimated_hours * line.unit_price
