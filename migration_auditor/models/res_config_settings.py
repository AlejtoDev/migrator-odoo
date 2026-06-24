from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    auditor_default_currency_id = fields.Many2one(
        'res.currency',
        string='Moneda por defecto',
        config_parameter='migration_auditor.default_currency_id',
        help='Moneda usada en nuevos proyectos de auditoría si no se especifica otra.',
    )
    auditor_default_hourly_rate = fields.Float(
        string='Tarifa hora por defecto',
        config_parameter='migration_auditor.default_hourly_rate',
        help='Tarifa hora del consultor usada en nuevos proyectos.',
    )
    auditor_default_product_id = fields.Many2one(
        'product.product',
        string='Producto de servicio por defecto',
        domain=[('type', '=', 'service')],
        config_parameter='migration_auditor.default_product_id',
        help='Producto usado cuando una categoría de esfuerzo no tiene producto asignado.',
    )
    auditor_default_partner_id = fields.Many2one(
        'res.partner',
        string='Cliente genérico para cotizaciones',
        config_parameter='migration_auditor.default_partner_id',
        help='Partner usado al crear sale.order si el proyecto no tiene cliente en res.partner.',
    )

    def action_create_default_products(self):
        self.env['audit.category.product'].create_default_products_and_mappings()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Productos creados',
                'message': 'Se crearon los productos de servicio por categoría correctamente.',
                'type': 'success',
            }
        }
