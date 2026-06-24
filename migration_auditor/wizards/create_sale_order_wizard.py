from collections import defaultdict
from odoo import models, fields, api
from odoo.exceptions import UserError


class CreateSaleOrderWizard(models.TransientModel):
    _name = 'create.sale.order.wizard'
    _description = 'Crear cotización de venta desde auditoría'

    project_id = fields.Many2one('audit.project', required=True, readonly=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente',
        required=True,
        default=lambda self: self._default_partner(),
    )
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
    group_by_category = fields.Boolean(
        string='Agrupar líneas por categoría',
        default=True,
        help='Agrupa las líneas de la misma categoría sumando sus horas.',
    )
    include_zero_lines = fields.Boolean(
        string='Incluir líneas con 0 horas',
        default=False,
    )
    note = fields.Text(
        string='Nota en la cotización',
        default=lambda self: self._default_note(),
    )
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
        return int(param) if param and param != '0' else False

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
        return int(param) if param and param != '0' else self.env.company.currency_id.id

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
                f'→ Versión destino: {project.target_version or "17.0"}\n'
                f'Fecha de análisis: {project.scan_date}'
            )
        return ''

    # ── Compute y onchange ────────────────────────────────────────────────────

    @api.depends('preview_line_ids.subtotal')
    def _compute_preview_total(self):
        for wiz in self:
            wiz.preview_total = sum(wiz.preview_line_ids.mapped('subtotal'))

    @api.onchange('group_by_category', 'include_zero_lines', 'hourly_rate', 'project_id')
    def _onchange_compute_preview(self):
        self.preview_line_ids = [(5, 0, 0)]
        if not self.project_id:
            return
        lines_data = self._build_lines_data()
        self.preview_line_ids = [(0, 0, d) for d in lines_data]

    # ── Lógica de construcción de líneas ──────────────────────────────────────

    def _build_lines_data(self):
        effort_lines = self.project_id.effort_line_ids
        if not self.include_zero_lines:
            effort_lines = effort_lines.filtered(lambda l: l.estimated_hours > 0)

        rate = self.hourly_rate or self.project_id.hourly_rate
        cat_selection = dict(
            self.env['audit.effort.line']._fields['category'].selection
        )

        if self.group_by_category:
            groups = defaultdict(lambda: {'hours': 0.0, 'product_id': False,
                                          'description': '', 'category': ''})
            for line in effort_lines:
                cat = line.category
                groups[cat]['hours'] += line.estimated_hours
                groups[cat]['category'] = cat
                if not groups[cat]['product_id'] and line.product_id:
                    groups[cat]['product_id'] = line.product_id.id
                if not groups[cat]['description']:
                    groups[cat]['description'] = cat_selection.get(cat, cat)

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

        order_lines = []
        for line in lines_data:
            product = (
                self.env['product.product'].browse(line['product_id'])
                if line['product_id'] else False
            )
            if not product:
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
                if self.hourly_rate > 0:
                    line_vals['price_unit'] = self.hourly_rate

            order_lines.append((0, 0, line_vals))

        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'order_line': order_lines,
            'note': self.note or '',
            'origin': f'Auditoría: {project.name}',
        })

        project.write({
            'sale_order_ids': [(4, sale_order.id)],
            'currency_id': self.currency_id.id,
            'hourly_rate': self.hourly_rate,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'Cotización creada',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': sale_order.id,
        }


class CreateSaleOrderWizardLine(models.TransientModel):
    _name = 'create.sale.order.wizard.line'
    _description = 'Línea de preview de cotización'

    wizard_id = fields.Many2one('create.sale.order.wizard', ondelete='cascade')
    description = fields.Char(readonly=True)
    hours = fields.Float(string='Horas', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    subtotal = fields.Float(readonly=True)
