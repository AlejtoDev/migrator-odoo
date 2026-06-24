from odoo import models, fields, api

VOLUME_MODELS = [
    ('res.partner', 'Contactos'),
    ('account.move', 'Facturas / Asientos'),
    ('account.move.line', 'Líneas contables'),
    ('sale.order', 'Órdenes de venta'),
    ('sale.order.line', 'Líneas de venta'),
    ('purchase.order', 'Órdenes de compra'),
    ('stock.move', 'Movimientos de stock'),
    ('stock.picking', 'Transferencias'),
    ('mrp.production', 'Órdenes de producción'),
    ('hr.employee', 'Empleados'),
    ('project.task', 'Tareas'),
    ('crm.lead', 'Oportunidades CRM'),
    ('product.template', 'Productos'),
    ('product.product', 'Variantes de producto'),
]


class AuditVolumeFinding(models.Model):
    _name = 'audit.volume.finding'
    _description = 'Volumen de datos detectado en auditoría'
    _order = 'record_count desc'

    project_id = fields.Many2one('audit.project', required=True, ondelete='cascade')
    model_name = fields.Char(string='Modelo', required=True)
    display_name = fields.Char(string='Nombre legible')
    record_count = fields.Integer(string='Registros')
    volume_tier = fields.Selection([
        ('low', 'Bajo (<10k)'),
        ('medium', 'Medio (10k-100k)'),
        ('high', 'Alto (>100k)'),
    ], string='Nivel de volumen', compute='_compute_tier', store=True)
    effort_extra_hours = fields.Float(string='Horas adicionales por volumen')
    notes = fields.Text(string='Notas')

    @api.depends('record_count')
    def _compute_tier(self):
        for rec in self:
            if rec.record_count < 0:
                rec.volume_tier = 'low'
            elif rec.record_count < 10000:
                rec.volume_tier = 'low'
            elif rec.record_count < 100000:
                rec.volume_tier = 'medium'
            else:
                rec.volume_tier = 'high'
