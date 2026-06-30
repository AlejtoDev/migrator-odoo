from odoo import models, fields, api
from odoo.exceptions import UserError

ODOO_VERSIONS = [
    ('12.0', 'Odoo 12.0'),
    ('13.0', 'Odoo 13.0'),
    ('14.0', 'Odoo 14.0'),
    ('15.0', 'Odoo 15.0'),
    ('16.0', 'Odoo 16.0'),
    ('17.0', 'Odoo 17.0'),
    ('18.0', 'Odoo 18.0'),
    ('19.0', 'Odoo 19.0'),
]


class AuditProject(models.Model):
    _name = 'audit.project'
    _description = 'Proyecto de auditoría de migración'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scan_date desc, id desc'

    name = fields.Char(string='Nombre del proyecto', required=True, tracking=True)
    client_name = fields.Char(string='Cliente', required=True)
    client_email = fields.Char(string='Email de contacto')
    source_version = fields.Selection(ODOO_VERSIONS, string='Versión origen')
    target_version = fields.Selection(ODOO_VERSIONS, string='Versión destino')
    audit_mode = fields.Selection([
        ('xmlrpc', 'Conexión directa XML-RPC'),
        ('backup', 'Archivo de backup'),
    ], string='Modo de auditoría', required=True, default='xmlrpc', tracking=True)
    connection_id = fields.Many2one(
        'audit.connection',
        string='Credenciales XML-RPC',
    )
    backup_id = fields.Many2one('audit.backup', string='Backup procesado')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('scanning', 'Escaneando'),
        ('done', 'Completado'),
        ('error', 'Error'),
    ], string='Estado', default='draft', tracking=True)
    scan_date = fields.Datetime(string='Fecha de escaneo')
    odoo_version_detected = fields.Char(string='Versión detectada')
    is_enterprise = fields.Boolean(string='Enterprise')

    module_finding_ids = fields.One2many('audit.module.finding', 'project_id', string='Módulos')
    field_finding_ids = fields.One2many('audit.field.finding', 'project_id', string='Campos custom')
    model_finding_ids = fields.One2many('audit.model.finding', 'project_id', string='Modelos custom')
    volume_finding_ids = fields.One2many('audit.volume.finding', 'project_id', string='Volumen')
    effort_line_ids = fields.One2many('audit.effort.line', 'project_id', string='Estimación')

    # ── Configuración financiera del proyecto ───────────────────────────────────

    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente (res.partner)',
        help='Contacto en Odoo para crear la cotización de venta.',
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
        help='Si está activo, todas las líneas usarán el producto seleccionado aquí.',
    )
    project_product_id = fields.Many2one(
        'product.product',
        string='Producto único del proyecto',
        domain=[('type', '=', 'service')],
    )

    # ── Sale orders vinculadas ──────────────────────────────────────────────────

    sale_order_ids = fields.Many2many(
        'sale.order',
        'audit_project_sale_order_rel',
        'project_id',
        'sale_order_id',
        string='Cotizaciones generadas',
        readonly=True,
    )
    sale_order_count = fields.Integer(compute='_compute_sale_order_count', string='Cotizaciones')

    # ── Totales ────────────────────────────────────────────────────────────────

    total_hours = fields.Float(string='Total horas', compute='_compute_totals', store=True)
    total_cost = fields.Float(string='Costo total', compute='_compute_totals', store=True)

    # ── Contenido editorial ────────────────────────────────────────────────────

    consultant_notes = fields.Html(string='Notas internas del consultor', sanitize=False)
    executive_summary = fields.Html(string='Resumen ejecutivo', sanitize=False)

    # ── Contadores smart buttons ───────────────────────────────────────────────

    module_count = fields.Integer(compute='_compute_counts')
    field_count = fields.Integer(compute='_compute_counts')
    model_count = fields.Integer(compute='_compute_counts')

    # ── Defaults desde ir.config_parameter ────────────────────────────────────

    @api.model
    def _default_currency(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'migration_auditor.default_currency_id'
        )
        if param and param != '0':
            return int(param)
        return self.env.company.currency_id.id

    @api.model
    def _default_hourly_rate(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'migration_auditor.default_hourly_rate'
        )
        return float(param) if param and param != '0' else 0.0

    # ── Computes ───────────────────────────────────────────────────────────────

    @api.depends('effort_line_ids', 'effort_line_ids.estimated_hours', 'hourly_rate')
    def _compute_totals(self):
        for project in self:
            total_h = sum(project.effort_line_ids.mapped('estimated_hours'))
            project.total_hours = total_h
            project.total_cost = total_h * project.hourly_rate

    def _compute_counts(self):
        for project in self:
            project.module_count = len(project.module_finding_ids)
            project.field_count = len(project.field_finding_ids)
            project.model_count = len(project.model_finding_ids)

    def _compute_sale_order_count(self):
        for rec in self:
            rec.sale_order_count = len(rec.sale_order_ids)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _get_product_for_line(self, category):
        if self.override_product and self.project_product_id:
            return self.project_product_id
        return self.env['audit.category.product'].get_product_for_category(category)

    # ── Acciones ──────────────────────────────────────────────────────────────

    def action_run_audit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Ejecutar diagnóstico',
            'res_model': 'run.audit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_generate_report(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Generar informe',
            'res_model': 'generate.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_reset_draft(self):
        self.ensure_one()
        self.module_finding_ids.unlink()
        self.field_finding_ids.unlink()
        self.model_finding_ids.unlink()
        self.volume_finding_ids.unlink()
        self.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()
        self.write({'state': 'draft', 'scan_date': False, 'odoo_version_detected': False})

    def action_create_sale_order(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError('El proyecto debe estar en estado "Completado" para crear una cotización.')
        return {
            'type': 'ir.actions.act_window',
            'name': 'Crear cotización',
            'res_model': 'create.sale.order.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cotizaciones',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sale_order_ids.ids)],
            'context': {'default_partner_id': self.partner_id.id},
        }

    def action_view_modules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Módulos detectados',
            'res_model': 'audit.module.finding',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
        }

    def action_view_fields(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Campos custom detectados',
            'res_model': 'audit.field.finding',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
        }

    def action_view_models(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modelos custom detectados',
            'res_model': 'audit.model.finding',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
        }

    def action_create_implementation_project(self):
        self.ensure_one()
        if not self.env['ir.module.module'].sudo().search([
            ('name', '=', 'project'), ('state', '=', 'installed')
        ], limit=1):
            raise UserError('El módulo "Proyecto" debe estar instalado para usar esta función.')

        version_label = self.target_version or self.odoo_version_detected or '?'
        proj = self.env['project.project'].create({
            'name': f'Migración Odoo {version_label} — {self.client_name}',
            'partner_id': self.partner_id.id if self.partner_id else False,
        })

        for line in self.effort_line_ids:
            self.env['project.task'].create({
                'name': line.description or line.category,
                'project_id': proj.id,
                'planned_hours': line.estimated_hours,
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'project.project',
            'view_mode': 'form',
            'res_id': proj.id,
        }
