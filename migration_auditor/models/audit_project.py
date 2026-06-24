from odoo import models, fields, api

ODOO_VERSIONS = [
    ('12.0', 'Odoo 12.0'),
    ('13.0', 'Odoo 13.0'),
    ('14.0', 'Odoo 14.0'),
    ('15.0', 'Odoo 15.0'),
    ('16.0', 'Odoo 16.0'),
    ('17.0', 'Odoo 17.0'),
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
        attrs="{'required': [('audit_mode', '=', 'xmlrpc')]}",
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
    hourly_rate = fields.Float(string='Tarifa hora', default=0.0)
    total_hours = fields.Float(string='Total horas', compute='_compute_totals', store=True)
    total_cost = fields.Float(string='Costo total', compute='_compute_totals', store=True)
    currency_id = fields.Many2one('res.currency', string='Moneda',
                                  default=lambda self: self.env.company.currency_id)
    consultant_notes = fields.Html(string='Notas internas del consultor', sanitize=False)
    executive_summary = fields.Html(string='Resumen ejecutivo', sanitize=False)

    # Contadores para smart buttons
    module_count = fields.Integer(compute='_compute_counts')
    field_count = fields.Integer(compute='_compute_counts')
    model_count = fields.Integer(compute='_compute_counts')

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

    def action_view_modules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Módulos detectados',
            'res_model': 'audit.module.finding',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
        }

    def action_view_fields(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Campos custom detectados',
            'res_model': 'audit.field.finding',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
        }

    def action_view_models(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modelos custom detectados',
            'res_model': 'audit.model.finding',
            'view_mode': 'tree,form',
            'domain': [('project_id', '=', self.id)],
        }
