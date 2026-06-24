# Patch v2 — `migration_auditor`: moneda, productos por categoría y cotización en Ventas
#
# Este archivo es un PATCH sobre claude_code_prompt_migration_auditor.md
# Aplica los cambios en el orden en que aparecen. Donde dice "REEMPLAZAR",
# sustituye la sección correspondiente del prompt original. Donde dice
# "AGREGAR", inserta el bloque en la posición indicada.
#
# Resumen de cambios:
#   1. Nueva dependencia: 'sale'
#   2. Nuevo modelo: res.config.settings (herencia) — ajustes globales
#   3. Nuevo modelo: audit.category.product — mapeo categoría → producto
#   4. Modificaciones a audit.project — moneda y producto override por proyecto
#   5. Modificaciones a audit.effort.line — product_id por línea
#   6. Nuevo método en audit.project: action_create_sale_order()
#   7. Modificaciones al wizard generate.report.wizard — opción de crear SO
#   8. Nuevo wizard: create_sale_order_wizard.py
#   9. Vista: ajustes globales en res.config.settings
#  10. Cambios en vistas de audit.project y audit.effort.line
#  11. Actualización de ir.model.access.csv
#  12. Actualización de __manifest__.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 1. REEMPLAZAR — `__manifest__.py`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```python
{
    'name': 'Migration Auditor',
    'version': '17.0.1.0.0',
    'summary': 'Auditoría remota de instancias Odoo y presupuesto de migraciones',
    'category': 'Technical',
    'author': 'AlejtoDev',
    'website': 'https://odoo.alejtodev.cl',
    'depends': ['base', 'web', 'mail', 'sale'],   # ← sale agregado
    'data': [
        'security/auditor_security.xml',
        'security/ir.model.access.csv',
        'data/auditor_data.xml',
        'data/effort_rules_data.xml',
        'report/audit_report_action.xml',
        'report/audit_report_template.xml',
        'views/res_config_settings_views.xml',         # ← NUEVO
        'views/audit_category_product_views.xml',      # ← NUEVO
        'views/audit_project_views.xml',
        'views/audit_connection_views.xml',
        'views/audit_backup_views.xml',
        'views/audit_finding_views.xml',
        'views/audit_effort_line_views.xml',
        'views/menus.xml',
    ],
    'external_dependencies': {
        'python': ['xmlrpc.client', 'zipfile', 'psycopg2'],
    },
    'license': 'OPL-1',
    'installable': True,
    'application': True,
}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 2. AGREGAR — Nuevo modelo `audit.category.product`
##    Archivo: `models/audit_category_product.py`
##    Posición en __init__.py de models/: después de audit_effort_line.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Define el mapeo global entre cada categoría de esfuerzo y su producto de
servicio en Odoo. Hay exactamente un registro por categoría (singleton por
categoría). Los productos deben ser de tipo `service`.

```python
from odoo import models, fields, api
from odoo.exceptions import ValidationError


# Categorías disponibles — deben coincidir con el Selection de audit.effort.line
EFFORT_CATEGORIES = [
    ('analysis',       'Análisis y diagnóstico'),
    ('custom_module',  'Módulos custom'),
    ('oca_module',     'Módulos OCA'),
    ('studio_fields',  'Campos Studio / custom'),
    ('custom_model',   'Modelos custom completos'),
    ('data_volume',    'Optimización ETL / volumen'),
    ('testing',        'Testing y validación'),
    ('training',       'Capacitación'),
    ('contingency',    'Contingencia'),
    ('other',          'Otros'),
]


class AuditCategoryProduct(models.Model):
    _name = 'audit.category.product'
    _description = 'Producto de servicio por categoría de esfuerzo'
    _order = 'sequence'

    sequence = fields.Integer(default=10)
    category = fields.Selection(
        EFFORT_CATEGORIES,
        string='Categoría de esfuerzo',
        required=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Producto de servicio',
        domain=[('type', '=', 'service')],
        required=True,
    )
    # Validación: el producto debe ser de tipo servicio
    # (el domain en la vista ya filtra, pero validamos también en backend)

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
        """
        Retorna el product.product para una categoría dada.
        Si no hay mapeo configurado, retorna el producto por defecto
        de los ajustes globales. Si tampoco existe, retorna False.
        """
        mapping = self.search([('category', '=', category)], limit=1)
        if mapping:
            return mapping.product_id
        # Fallback al producto por defecto global
        default_product_id = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'migration_auditor.default_product_id', 0
            )
        )
        if default_product_id:
            return self.env['product.product'].browse(default_product_id)
        return False

    @api.model
    def create_default_products_and_mappings(self):
        """
        Crea productos de servicio por defecto para cada categoría
        si aún no existen mapeos. Llamado desde el wizard de configuración
        inicial o desde un botón en los ajustes.
        """
        for category, label in EFFORT_CATEGORIES:
            existing = self.search([('category', '=', category)], limit=1)
            if existing:
                continue
            # Buscar producto existente con ese nombre
            product_name = f'Migración Odoo — {label}'
            product = self.env['product.product'].search([
                ('name', '=', product_name),
                ('type', '=', 'service'),
            ], limit=1)
            if not product:
                product = self.env['product.product'].create({
                    'name': product_name,
                    'type': 'service',
                    'invoice_policy': 'order',
                    'uom_id': self.env.ref('uom.product_uom_hour').id,
                    'uom_po_id': self.env.ref('uom.product_uom_hour').id,
                    'description_sale': f'Servicios de migración Odoo: {label}',
                })
            self.create({
                'category': category,
                'product_id': product.id,
            })
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 3. AGREGAR — Herencia de `res.config.settings`
##    Archivo: `models/res_config_settings.py`
##    Posición en models/__init__.py: al final
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ajustes globales del módulo. Se guardan en `ir.config_parameter`.
El consultor los configura una sola vez en Ajustes > Migration Auditor.

```python
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Moneda por defecto ──────────────────────────────────────────────────
    auditor_default_currency_id = fields.Many2one(
        'res.currency',
        string='Moneda por defecto',
        config_parameter='migration_auditor.default_currency_id',
        help='Moneda usada en nuevos proyectos de auditoría si no se especifica otra.',
    )

    # ── Tarifa hora por defecto ─────────────────────────────────────────────
    auditor_default_hourly_rate = fields.Float(
        string='Tarifa hora por defecto',
        config_parameter='migration_auditor.default_hourly_rate',
        help='Tarifa hora del consultor usada en nuevos proyectos.',
    )

    # ── Producto de servicio por defecto (fallback global) ──────────────────
    auditor_default_product_id = fields.Many2one(
        'product.product',
        string='Producto de servicio por defecto',
        domain=[('type', '=', 'service')],
        config_parameter='migration_auditor.default_product_id',
        help='Producto usado cuando una categoría de esfuerzo no tiene producto asignado.',
    )

    # ── Cliente por defecto para cotizaciones (opcional) ────────────────────
    auditor_default_partner_id = fields.Many2one(
        'res.partner',
        string='Cliente genérico para cotizaciones',
        config_parameter='migration_auditor.default_partner_id',
        help='Partner usado al crear sale.order si el proyecto no tiene cliente en res.partner.',
    )

    # ── Acción: crear productos y mapeos por defecto ────────────────────────
    def action_create_default_products(self):
        """
        Crea un producto de servicio por cada categoría de esfuerzo
        y los asigna en audit.category.product si aún no existen mapeos.
        Útil para la configuración inicial del módulo.
        """
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
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 4. REEMPLAZAR — Campos adicionales en `audit.project`
##    Archivo: `models/audit_project.py`
##    Agregar estos campos a la definición de la clase (junto a los existentes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Añadir los siguientes campos al modelo `audit.project` (además de los ya
definidos en el prompt original):

```python
# ── Configuración financiera del proyecto ───────────────────────────────────

partner_id = fields.Many2one(
    'res.partner',
    string='Cliente (res.partner)',
    help='Contacto en Odoo para crear la cotización de venta. '
         'Opcional si el cliente no tiene registro en el sistema.',
)
currency_id = fields.Many2one(
    'res.currency',
    string='Moneda',
    default=lambda self: self._default_currency(),
    required=True,
)
hourly_rate = fields.Float(
    string='Tarifa hora',
    default=lambda self: self._default_hourly_rate(),
)
override_product = fields.Boolean(
    string='Sobreescribir producto por proyecto',
    help='Si está activo, todas las líneas de este proyecto usarán el producto '
         'seleccionado aquí, ignorando los mapeos por categoría.',
)
project_product_id = fields.Many2one(
    'product.product',
    string='Producto único del proyecto',
    domain=[('type', '=', 'service')],
    help='Producto de servicio a usar en todas las líneas cuando '
         '"Sobreescribir producto" está activo.',
    attrs="{'invisible': [('override_product', '=', False)], "
          "'required': [('override_product', '=', True)]}",
)

# ── Sale order vinculada ────────────────────────────────────────────────────
sale_order_ids = fields.Many2many(
    'sale.order',
    'audit_project_sale_order_rel',
    'project_id',
    'sale_order_id',
    string='Cotizaciones generadas',
    readonly=True,
)
sale_order_count = fields.Integer(
    compute='_compute_sale_order_count',
    string='Cotizaciones',
)

# ── Métodos de default ───────────────────────────────────────────────────────

@api.model
def _default_currency(self):
    param = self.env['ir.config_parameter'].sudo().get_param(
        'migration_auditor.default_currency_id'
    )
    if param:
        return int(param)
    return self.env.company.currency_id.id

@api.model
def _default_hourly_rate(self):
    param = self.env['ir.config_parameter'].sudo().get_param(
        'migration_auditor.default_hourly_rate'
    )
    return float(param) if param else 0.0

# ── Compute ─────────────────────────────────────────────────────────────────

def _compute_sale_order_count(self):
    for rec in self:
        rec.sale_order_count = len(rec.sale_order_ids)

# ── Acción smart button cotizaciones ────────────────────────────────────────

def action_view_sale_orders(self):
    self.ensure_one()
    return {
        'type': 'ir.actions.act_window',
        'name': 'Cotizaciones',
        'res_model': 'sale.order',
        'view_mode': 'tree,form',
        'domain': [('id', 'in', self.sale_order_ids.ids)],
        'context': {'default_partner_id': self.partner_id.id},
    }

# ── Creación de sale.order ───────────────────────────────────────────────────

def action_create_sale_order(self):
    """Abre el wizard de creación de cotización."""
    self.ensure_one()
    if self.state != 'done':
        raise UserError('El proyecto debe estar en estado "done" para crear una cotización.')
    return {
        'type': 'ir.actions.act_window',
        'name': 'Crear cotización',
        'res_model': 'create.sale.order.wizard',
        'view_mode': 'form',
        'target': 'new',
        'context': {'default_project_id': self.id},
    }

def _get_product_for_line(self, category):
    """
    Resuelve el producto a usar para una línea de esfuerzo.
    Prioridad:
      1. Si override_product está activo → project_product_id
      2. Mapeo global en audit.category.product para esa categoría
      3. Producto por defecto en ir.config_parameter
      4. False (la línea de SO no tendrá producto — debe corregirse manualmente)
    """
    if self.override_product and self.project_product_id:
        return self.project_product_id
    return self.env['audit.category.product'].get_product_for_category(category)
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 5. REEMPLAZAR — Campos adicionales en `audit.effort.line`
##    Archivo: `models/audit_effort_line.py`
##    Añadir estos campos a los ya existentes
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```python
# Añadir a audit.effort.line junto a los campos existentes:

product_id = fields.Many2one(
    'product.product',
    string='Producto',
    domain=[('type', '=', 'service')],
    help='Producto de servicio que representa esta línea en la cotización de venta. '
         'Se asigna automáticamente según la categoría al generar las líneas.',
)
unit_price = fields.Float(
    string='Precio unitario (hora)',
    related='project_id.hourly_rate',
    readonly=True,
)
subtotal = fields.Float(
    string='Subtotal',
    compute='_compute_subtotal',
    store=True,
)

@api.depends('estimated_hours', 'unit_price')
def _compute_subtotal(self):
    for line in self:
        line.subtotal = line.estimated_hours * line.unit_price
```

Y en el método `_generate_effort_lines` del wizard `run.audit.wizard`,
al crear cada línea agregar la resolución del producto:

```python
# En cada bloque donde se hace self.env['audit.effort.line'].create({...})
# añadir la clave 'product_id':

product = project._get_product_for_line(category)
self.env['audit.effort.line'].create({
    'project_id': project.id,
    'sequence': seq,
    'category': category,
    'description': description,
    'estimated_hours': hours,
    'source': 'auto',
    'reference': reference,
    'product_id': product.id if product else False,  # ← AGREGAR
})
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 6. AGREGAR — Nuevo wizard `create.sale.order.wizard`
##    Archivo: `wizards/create_sale_order_wizard.py`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```python
from odoo import models, fields, api
from odoo.exceptions import UserError


class CreateSaleOrderWizard(models.TransientModel):
    _name = 'create.sale.order.wizard'
    _description = 'Crear cotización de venta desde auditoría'

    project_id = fields.Many2one('audit.project', required=True, readonly=True)

    # ── Partner ─────────────────────────────────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        required=True,
        default=lambda self: self._default_partner(),
        help='Cliente al que se emitirá la cotización.',
    )

    # ── Moneda y tarifa ─────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        required=True,
        default=lambda self: self._default_currency(),
    )
    hourly_rate = fields.Float(
        string='Tarifa hora',
        default=lambda self: self._default_rate(),
    )

    # ── Opciones de líneas ───────────────────────────────────────────────────
    group_by_category = fields.Boolean(
        string='Agrupar líneas por categoría',
        default=True,
        help='Si está activo, agrupa todas las líneas de la misma categoría '
             'en una sola línea de cotización sumando las horas. '
             'Si no, crea una línea de SO por cada línea de esfuerzo.',
    )
    include_zero_lines = fields.Boolean(
        string='Incluir líneas con 0 horas',
        default=False,
    )

    # ── Notas ────────────────────────────────────────────────────────────────
    note = fields.Text(
        string='Nota en la cotización',
        default=lambda self: self._default_note(),
    )

    # ── Preview de líneas ────────────────────────────────────────────────────
    preview_line_ids = fields.One2many(
        'create.sale.order.wizard.line',
        'wizard_id',
        string='Vista previa de líneas',
        readonly=True,
    )
    preview_total = fields.Float(
        string='Total estimado',
        compute='_compute_preview_total',
    )

    # ── Defaults ──────────────────────────────────────────────────────────────

    @api.model
    def _default_partner(self):
        ctx_project = self.env.context.get('default_project_id')
        if ctx_project:
            project = self.env['audit.project'].browse(ctx_project)
            if project.partner_id:
                return project.partner_id.id
        param = self.env['ir.config_parameter'].sudo().get_param(
            'migration_auditor.default_partner_id'
        )
        return int(param) if param else False

    @api.model
    def _default_currency(self):
        ctx_project = self.env.context.get('default_project_id')
        if ctx_project:
            project = self.env['audit.project'].browse(ctx_project)
            if project.currency_id:
                return project.currency_id.id
        param = self.env['ir.config_parameter'].sudo().get_param(
            'migration_auditor.default_currency_id'
        )
        return int(param) if param else self.env.company.currency_id.id

    @api.model
    def _default_rate(self):
        ctx_project = self.env.context.get('default_project_id')
        if ctx_project:
            project = self.env['audit.project'].browse(ctx_project)
            if project.hourly_rate:
                return project.hourly_rate
        param = self.env['ir.config_parameter'].sudo().get_param(
            'migration_auditor.default_hourly_rate'
        )
        return float(param) if param else 0.0

    @api.model
    def _default_note(self):
        ctx_project = self.env.context.get('default_project_id')
        if ctx_project:
            project = self.env['audit.project'].browse(ctx_project)
            return (
                f'Propuesta de migración Odoo — {project.client_name}\n'
                f'Versión origen: {project.odoo_version_detected or project.source_version} '
                f'→ Versión destino: {project.target_version}\n'
                f'Fecha de análisis: {project.scan_date}'
            )
        return ''

    # ── Compute preview ───────────────────────────────────────────────────────

    @api.depends('preview_line_ids.subtotal')
    def _compute_preview_total(self):
        for wiz in self:
            wiz.preview_total = sum(wiz.preview_line_ids.mapped('subtotal'))

    @api.onchange('group_by_category', 'include_zero_lines', 'hourly_rate')
    def _onchange_compute_preview(self):
        """Recalcula la preview de líneas al cambiar opciones."""
        self.preview_line_ids = [(5, 0, 0)]  # limpiar
        if not self.project_id:
            return
        lines_data = self._build_lines_data()
        self.preview_line_ids = [(0, 0, d) for d in lines_data]

    def _build_lines_data(self):
        """
        Construye la lista de dicts para las líneas de la cotización
        según las opciones seleccionadas (agrupado o no).
        Retorna lista de dicts con: description, hours, product_id, subtotal.
        """
        effort_lines = self.project_id.effort_line_ids
        if not self.include_zero_lines:
            effort_lines = effort_lines.filtered(lambda l: l.estimated_hours > 0)

        rate = self.hourly_rate or self.project_id.hourly_rate

        if self.group_by_category:
            # Agrupar por categoría: sumar horas, usar el producto de la categoría
            from collections import defaultdict
            groups = defaultdict(lambda: {'hours': 0.0, 'product_id': False,
                                          'description': '', 'category': ''})
            for line in effort_lines:
                cat = line.category
                groups[cat]['hours'] += line.estimated_hours
                groups[cat]['category'] = cat
                if not groups[cat]['product_id'] and line.product_id:
                    groups[cat]['product_id'] = line.product_id.id
                if not groups[cat]['description']:
                    groups[cat]['description'] = dict(
                        self.env['audit.effort.line']._fields['category'].selection
                    ).get(cat, cat)

            result = []
            for cat, data in sorted(groups.items()):
                if not self.include_zero_lines and data['hours'] == 0:
                    continue
                result.append({
                    'description': data['description'],
                    'hours': data['hours'],
                    'product_id': data['product_id'],
                    'subtotal': data['hours'] * rate,
                })
            return result
        else:
            # Una línea por effort line
            return [{
                'description': line.description,
                'hours': line.estimated_hours,
                'product_id': line.product_id.id if line.product_id else False,
                'subtotal': line.estimated_hours * rate,
            } for line in effort_lines]

    # ── Acción principal ───────────────────────────────────────────────────────

    def action_create(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError('Debes seleccionar un cliente para crear la cotización.')
        if self.hourly_rate <= 0:
            raise UserError('La tarifa hora debe ser mayor a cero.')

        project = self.project_id
        lines_data = self._build_lines_data()

        if not lines_data:
            raise UserError('No hay líneas de esfuerzo con horas para crear la cotización.')

        # Construir order lines para el sale.order
        order_lines = []
        for line in lines_data:
            product = (
                self.env['product.product'].browse(line['product_id'])
                if line['product_id'] else False
            )
            if not product:
                # Intentar resolver desde el mapeo global como fallback
                product = self.env['audit.category.product'].get_product_for_category(
                    line.get('category', 'other')
                )

            line_vals = {
                'name': line['description'],
                'product_uom_qty': line['hours'],
                'price_unit': self.hourly_rate,
            }
            if product:
                line_vals['product_id'] = product.id
                # Dejar que Odoo calcule el precio desde el producto si la tarifa
                # configurada es 0 (el producto puede tener su propio precio)
                if self.hourly_rate > 0:
                    line_vals['price_unit'] = self.hourly_rate

            order_lines.append((0, 0, line_vals))

        # Crear el sale.order
        so_vals = {
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'order_line': order_lines,
            'note': self.note or '',
            'origin': f'Auditoría: {project.name}',
        }
        sale_order = self.env['sale.order'].create(so_vals)

        # Vincular la SO al proyecto
        project.write({'sale_order_ids': [(4, sale_order.id)]})
        # Actualizar currency y rate del proyecto con los valores usados
        project.write({
            'currency_id': self.currency_id.id,
            'hourly_rate': self.hourly_rate,
        })

        # Abrir la cotización creada
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cotización creada',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': sale_order.id,
        }


class CreateSaleOrderWizardLine(models.TransientModel):
    """Líneas de preview en el wizard (solo para mostrar, no se persisten)."""
    _name = 'create.sale.order.wizard.line'
    _description = 'Línea de preview de cotización'

    wizard_id = fields.Many2one('create.sale.order.wizard', ondelete='cascade')
    description = fields.Char(readonly=True)
    hours = fields.Float(string='Horas', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    subtotal = fields.Float(readonly=True)
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 7. AGREGAR — Vista del wizard `create.sale.order.wizard`
##    Archivo: `views/audit_project_views.xml` (añadir al final del archivo)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```xml
<record id="view_create_sale_order_wizard_form" model="ir.ui.view">
    <field name="name">create.sale.order.wizard.form</field>
    <field name="model">create.sale.order.wizard</field>
    <field name="arch" type="xml">
        <form string="Crear cotización de venta">
            <sheet>
                <group string="Cliente y moneda">
                    <group>
                        <field name="partner_id"/>
                        <field name="currency_id"/>
                    </group>
                    <group>
                        <field name="hourly_rate"/>
                        <field name="preview_total" readonly="1"
                               widget="monetary"
                               options="{'currency_field': 'currency_id'}"/>
                    </group>
                </group>
                <group string="Opciones de líneas">
                    <field name="group_by_category"/>
                    <field name="include_zero_lines"/>
                </group>
                <separator string="Vista previa de líneas de la cotización"/>
                <field name="preview_line_ids" readonly="1" nolabel="1">
                    <tree>
                        <field name="description"/>
                        <field name="product_id"/>
                        <field name="hours" string="Horas"/>
                        <field name="subtotal" widget="monetary"
                               options="{'currency_field': 'currency_id'}"/>
                    </tree>
                </field>
                <separator string="Nota en la cotización"/>
                <field name="note" nolabel="1"
                       placeholder="Descripción del alcance del proyecto..."/>
            </sheet>
            <footer>
                <button name="action_create"
                        string="Crear cotización"
                        type="object"
                        class="oe_highlight"/>
                <button string="Cancelar"
                        class="btn-secondary"
                        special="cancel"/>
            </footer>
        </form>
    </field>
</record>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 8. AGREGAR — Vista de `audit.category.product`
##    Archivo nuevo: `views/audit_category_product_views.xml`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```xml
<odoo>
    <data>
        <record id="view_audit_category_product_tree" model="ir.ui.view">
            <field name="name">audit.category.product.tree</field>
            <field name="model">audit.category.product</field>
            <field name="arch" type="xml">
                <tree editable="bottom">
                    <field name="sequence" widget="handle"/>
                    <field name="category"/>
                    <field name="product_id"
                           domain="[('type', '=', 'service')]"
                           options="{'no_create': False}"/>
                </tree>
            </field>
        </record>

        <record id="action_audit_category_product" model="ir.actions.act_window">
            <field name="name">Productos por categoría</field>
            <field name="res_model">audit.category.product</field>
            <field name="view_mode">tree</field>
        </record>
    </data>
</odoo>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 9. AGREGAR — Vista de ajustes globales en `res.config.settings`
##    Archivo nuevo: `views/res_config_settings_views.xml`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```xml
<odoo>
    <data>
        <record id="res_config_settings_view_form" model="ir.ui.view">
            <field name="name">res.config.settings.view.migration.auditor</field>
            <field name="model">res.config.settings</field>
            <field name="inherit_id" ref="base_setup.action_general_configuration"/>
            <field name="arch" type="xml">
                <xpath expr="//div[hasclass('settings')]" position="before">
                    <div class="app_settings_block"
                         data-string="Migration Auditor"
                         data-key="migration_auditor">
                        <h2>Migration Auditor</h2>

                        <div class="row mt16 o_settings_container">

                            <!-- Moneda y tarifa -->
                            <div class="col-12 col-lg-6 o_setting_box">
                                <div class="o_setting_left_pane"/>
                                <div class="o_setting_right_pane">
                                    <label for="auditor_default_currency_id"
                                           string="Configuración financiera"/>
                                    <div class="text-muted">
                                        Moneda y tarifa hora usadas por defecto en nuevos proyectos.
                                    </div>
                                    <div class="content-group mt8">
                                        <div class="row">
                                            <label for="auditor_default_currency_id"
                                                   class="col-lg-4 o_light_label"/>
                                            <field name="auditor_default_currency_id"
                                                   class="col-lg-8"/>
                                        </div>
                                        <div class="row">
                                            <label for="auditor_default_hourly_rate"
                                                   class="col-lg-4 o_light_label"/>
                                            <field name="auditor_default_hourly_rate"
                                                   class="col-lg-8"/>
                                        </div>
                                        <div class="row">
                                            <label for="auditor_default_partner_id"
                                                   class="col-lg-4 o_light_label"/>
                                            <field name="auditor_default_partner_id"
                                                   class="col-lg-8"/>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            <!-- Producto por defecto -->
                            <div class="col-12 col-lg-6 o_setting_box">
                                <div class="o_setting_left_pane"/>
                                <div class="o_setting_right_pane">
                                    <label string="Producto de servicio por defecto"/>
                                    <div class="text-muted">
                                        Producto usado como fallback cuando una categoría
                                        no tiene producto asignado.
                                    </div>
                                    <div class="content-group mt8">
                                        <div class="row">
                                            <label for="auditor_default_product_id"
                                                   class="col-lg-4 o_light_label"/>
                                            <field name="auditor_default_product_id"
                                                   domain="[('type', '=', 'service')]"
                                                   class="col-lg-8"/>
                                        </div>
                                    </div>
                                    <div class="mt8">
                                        <button name="action_create_default_products"
                                                type="object"
                                                string="Crear productos por categoría automáticamente"
                                                class="btn btn-secondary"/>
                                    </div>
                                </div>
                            </div>

                        </div>

                        <!-- Tabla de mapeo categoría → producto -->
                        <h3 class="mt16">Producto por categoría de esfuerzo</h3>
                        <p class="text-muted">
                            Asigna un producto de servicio diferente a cada tipo
                            de tarea de migración. Al crear cotizaciones, cada línea
                            usará el producto correspondiente a su categoría.
                        </p>
                        <field name="auditor_default_product_id"
                               invisible="1"/>
                        <!-- Link directo a la tabla de mapeos -->
                        <button name="%(migration_auditor.action_audit_category_product)d"
                                type="action"
                                string="Gestionar mapeo de productos por categoría →"
                                class="btn btn-link p-0"/>

                    </div>
                </xpath>
            </field>
        </record>
    </data>
</odoo>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 10. REEMPLAZAR — Cambios en la form view de `audit.project`
##     Archivo: `views/audit_project_views.xml`
##     Modificaciones sobre la form view existente
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

En la form view de `audit.project`, aplicar estos cambios:

**a) Agregar smart button de cotizaciones** en el `oe_button_box`:

```xml
<button name="action_view_sale_orders" type="object"
        class="oe_stat_button" icon="fa-shopping-cart"
        attrs="{'invisible': [('sale_order_count', '=', 0)]}">
    <field name="sale_order_count" widget="statinfo" string="Cotizaciones"/>
</button>
```

**b) Agregar botón "Crear cotización"** en el header junto a los botones existentes:

```xml
<button name="action_create_sale_order"
        string="Crear cotización"
        type="object"
        icon="fa-file-text-o"
        attrs="{'invisible': [('state', '!=', 'done')]}"/>
```

**c) Agregar grupo "Configuración financiera"** en el sheet,
después del grupo de campos básicos (client_name, audit_mode, etc.):

```xml
<group string="Configuración financiera">
    <group>
        <field name="partner_id"/>
        <field name="currency_id"/>
        <field name="hourly_rate"/>
    </group>
    <group>
        <field name="override_product"/>
        <field name="project_product_id"
               attrs="{'invisible': [('override_product', '=', False)],
                       'required': [('override_product', '=', True)]}"
               domain="[('type', '=', 'service')]"/>
        <field name="total_hours" readonly="1"/>
        <field name="total_cost" readonly="1"
               widget="monetary"
               options="{'currency_field': 'currency_id'}"/>
    </group>
</group>
```

**d) Columna `product_id`** en el tree editable de `effort_line_ids`
dentro del notebook del proyecto (si se muestra inline):

```xml
<field name="product_id" domain="[('type', '=', 'service')]"/>
<field name="subtotal" widget="monetary"
       options="{'currency_field': 'parent.currency_id'}" readonly="1"/>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 11. REEMPLAZAR — Menús actualizados (`views/menus.xml`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```xml
<odoo>
    <data>
        <menuitem id="menu_auditor_root" name="Migration Auditor" sequence="81"/>

        <menuitem id="menu_audit_projects"
                  name="Proyectos de auditoría"
                  parent="menu_auditor_root"
                  action="action_audit_project"
                  sequence="10"/>

        <menuitem id="menu_audit_connections"
                  name="Conexiones XML-RPC"
                  parent="menu_auditor_root"
                  action="action_audit_connection"
                  sequence="20"/>

        <!-- ── Configuración ── -->
        <menuitem id="menu_auditor_config"
                  name="Configuración"
                  parent="menu_auditor_root"
                  sequence="90"/>

        <menuitem id="menu_audit_category_products"
                  name="Productos por categoría"
                  parent="menu_auditor_config"
                  action="action_audit_category_product"
                  sequence="91"/>

        <menuitem id="menu_auditor_settings"
                  name="Ajustes"
                  parent="menu_auditor_config"
                  action="base_setup.action_general_configuration"
                  sequence="92"/>
    </data>
</odoo>
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 12. REEMPLAZAR — `ir.model.access.csv` completo actualizado
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_audit_project,audit.project,model_audit_project,group_auditor_user,1,1,1,1
access_audit_connection,audit.connection,model_audit_connection,group_auditor_user,1,1,1,1
access_audit_backup,audit.backup,model_audit_backup,group_auditor_user,1,1,1,1
access_audit_module_finding,audit.module.finding,model_audit_module_finding,group_auditor_user,1,1,1,1
access_audit_field_finding,audit.field.finding,model_audit_field_finding,group_auditor_user,1,1,1,1
access_audit_model_finding,audit.model.finding,model_audit_model_finding,group_auditor_user,1,1,1,1
access_audit_volume_finding,audit.volume.finding,model_audit_volume_finding,group_auditor_user,1,1,1,1
access_audit_effort_line,audit.effort.line,model_audit_effort_line,group_auditor_user,1,1,1,1
access_audit_category_product,audit.category.product,model_audit_category_product,group_auditor_user,1,1,1,1
access_run_audit_wizard,run.audit.wizard,model_run_audit_wizard,group_auditor_user,1,1,1,1
access_generate_report_wizard,generate.report.wizard,model_generate_report_wizard,group_auditor_user,1,1,1,1
access_create_so_wizard,create.sale.order.wizard,model_create_sale_order_wizard,group_auditor_user,1,1,1,1
access_create_so_wizard_line,create.sale.order.wizard.line,model_create_sale_order_wizard_line,group_auditor_user,1,1,1,1
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## NOTAS TÉCNICAS ADICIONALES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### UoM hora en productos creados automáticamente

`create_default_products_and_mappings` usa `uom.product_uom_hour`. Ese xmlid existe
en el módulo `uom` que viene como dependencia transitiva de `sale`. No hace falta
agregar `uom` explícitamente en `depends`, pero si Claude Code reporta que el ref
no existe, agregar `'uom'` a la lista de depends del manifest.

### `config_parameter` con Many2one

Odoo 17 soporta `config_parameter` en campos Many2one en `res.config.settings`,
guardando el ID como string en `ir.config_parameter`. Al leer de vuelta con
`get_param`, el valor es un string — siempre convertir con `int(param)` antes
de usar como ID, y proteger con `if param` porque puede retornar `'0'` o `''`.

### Preview de líneas en el wizard con `@api.onchange`

El `One2many` hacia `create.sale.order.wizard.line` es un TransientModel.
Los registros se crean en memoria con `(0, 0, vals)` y se descartan al cerrar
el wizard. No persisten en BD hasta que se llama `action_create`.

### `origin` en sale.order

El campo `origin` del `sale.order` acepta texto libre. Se usa para trazar de
dónde vino la cotización: `f'Auditoría: {project.name}'`.

### Flujo configuración inicial (primer uso del módulo)

1. Ajustes > Migration Auditor
2. Definir moneda por defecto, tarifa hora y producto fallback
3. Clic "Crear productos por categoría automáticamente"
   → crea 10 productos de servicio tipo "Migración Odoo — {categoría}"
   → crea los 10 registros en `audit.category.product`
4. Opcionalmente ajustar nombre/precio de cada producto en Ventas > Productos
5. Listo — al generar effort lines en cualquier proyecto futuro, cada línea
   tendrá su producto asignado automáticamente
