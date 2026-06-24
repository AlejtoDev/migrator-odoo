from odoo import models, fields, api

ENTERPRISE_MODULES = {
    'web_enterprise', 'account_reports', 'account_accountant',
    'sale_subscription', 'sale_renting', 'sign', 'documents',
    'quality_control', 'maintenance', 'helpdesk', 'studio',
    'social', 'marketing_automation', 'voip', 'whatsapp',
}

OFFICIAL_PREFIXES = (
    'account', 'sale', 'purchase', 'stock', 'mrp', 'project',
    'hr', 'mail', 'web', 'base', 'bus', 'auth', 'calendar',
    'crm', 'lunch', 'fleet', 'point_of_sale', 'website',
    'payment', 'delivery', 'repair', 'survey',
)


class InstanceModuleStatus(models.Model):
    _name = 'instance.module.status'
    _description = 'Inventario de módulos instalados en la instancia'
    _order = 'module_category, name'

    name = fields.Char(string='Nombre técnico', required=True, index=True)
    display_name_module = fields.Char(string='Nombre legible')
    state = fields.Selection([
        ('installed', 'Instalado'),
        ('uninstalled', 'No instalado'),
        ('to upgrade', 'Por actualizar'),
        ('to remove', 'Por eliminar'),
    ], string='Estado')
    module_category = fields.Selection([
        ('odoo_official', 'Odoo Oficial'),
        ('oca', 'OCA'),
        ('custom', 'Custom'),
        ('enterprise', 'Enterprise'),
        ('localization', 'Localización'),
        ('unknown', 'Desconocido'),
    ], string='Categoría')
    author = fields.Char(string='Autor')
    version = fields.Char(string='Versión')
    last_scanned = fields.Datetime(string='Último escaneo')
    is_relevant_for_migration = fields.Boolean(
        string='Relevante para migración',
        compute='_compute_relevant',
        store=True,
    )
    notes = fields.Text(string='Notas del consultor')
    dependency_ids = fields.Many2many(
        'instance.module.status',
        'instance_module_dep_rel',
        'module_id',
        'dependency_id',
        string='Depende de',
    )

    @api.depends('module_category')
    def _compute_relevant(self):
        for rec in self:
            rec.is_relevant_for_migration = rec.module_category in ('custom', 'oca')

    @api.model
    def refresh_snapshot(self):
        installed = self.env['ir.module.module'].sudo().search([
            ('state', '=', 'installed')
        ])
        existing = {r.name: r for r in self.search([])}

        for mod in installed:
            category = self._detect_category(mod)
            vals = {
                'name': mod.name,
                'display_name_module': mod.shortdesc or mod.name,
                'state': mod.state,
                'author': mod.author or '',
                'version': mod.installed_version or '',
                'module_category': category,
                'last_scanned': fields.Datetime.now(),
            }
            if mod.name in existing:
                existing[mod.name].write(vals)
            else:
                self.create(vals)

        return True

    @api.model
    def _detect_category(self, mod):
        name = mod.name or ''
        author = (mod.author or '').lower()

        if name in ENTERPRISE_MODULES:
            return 'enterprise'
        if name.startswith('l10n_'):
            return 'localization'
        if 'oca' in author or 'odoo community association' in author:
            return 'oca'
        if 'odoo s.a.' in author or 'odoo sa' in author:
            return 'odoo_official'
        if any(name.startswith(p) for p in OFFICIAL_PREFIXES):
            return 'odoo_official'
        return 'custom'

    @api.model
    def _is_enterprise(self):
        return bool(self.env['ir.module.module'].sudo().search([
            ('name', '=', 'web_enterprise'),
            ('state', '=', 'installed'),
        ], limit=1))
