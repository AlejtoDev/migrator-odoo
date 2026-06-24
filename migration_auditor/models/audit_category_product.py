from odoo import models, fields, api
from odoo.exceptions import ValidationError


EFFORT_CATEGORIES = [
    ('analysis',      'Análisis y diagnóstico'),
    ('custom_module', 'Módulos custom'),
    ('oca_module',    'Módulos OCA'),
    ('studio_fields', 'Campos Studio / custom'),
    ('custom_model',  'Modelos custom completos'),
    ('data_volume',   'Optimización ETL / volumen'),
    ('testing',       'Testing y validación'),
    ('training',      'Capacitación'),
    ('contingency',   'Contingencia'),
    ('other',         'Otros'),
]


class AuditCategoryProduct(models.Model):
    _name = 'audit.category.product'
    _description = 'Producto de servicio por categoría de esfuerzo'
    _order = 'sequence'

    sequence = fields.Integer(default=10)
    category = fields.Selection(EFFORT_CATEGORIES, string='Categoría de esfuerzo', required=True)
    product_id = fields.Many2one(
        'product.product',
        string='Producto de servicio',
        domain=[('detailed_type', '=', 'service')],
        required=True,
    )

    _sql_constraints = [
        ('category_unique', 'UNIQUE(category)',
         'Ya existe un producto asignado para esta categoría.'),
    ]

    @api.constrains('product_id')
    def _check_product_type(self):
        for rec in self:
            if rec.product_id and rec.product_id.type != 'service':
                raise ValidationError(
                    f'El producto "{rec.product_id.name}" no es de tipo Servicio. '
                    'Solo se permiten productos de tipo Servicio para las líneas de auditoría.'
                )

    @api.model
    def get_product_for_category(self, category):
        mapping = self.search([('category', '=', category)], limit=1)
        if mapping:
            return mapping.product_id
        default_product_id = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'migration_auditor.default_product_id', 0
            ) or 0
        )
        if default_product_id:
            return self.env['product.product'].browse(default_product_id)
        return False

    @api.model
    def create_default_products_and_mappings(self):
        for category, label in EFFORT_CATEGORIES:
            existing = self.search([('category', '=', category)], limit=1)
            if existing:
                continue
            product_name = f'Migración Odoo — {label}'
            product = self.env['product.product'].search([
                ('name', '=', product_name),
                ('detailed_type', '=', 'service'),
            ], limit=1)
            if not product:
                uom_hour = self.env.ref('uom.product_uom_hour', raise_if_not_found=False)
                vals = {
                    'name': product_name,
                    'type': 'service',
                    'invoice_policy': 'order',
                    'description_sale': f'Servicios de migración Odoo: {label}',
                }
                if uom_hour:
                    vals.update({'uom_id': uom_hour.id, 'uom_po_id': uom_hour.id})
                product = self.env['product.product'].create(vals)
            self.create({'category': category, 'product_id': product.id})
