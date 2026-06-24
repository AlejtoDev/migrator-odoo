from odoo import models, fields, api


class AuditModuleFinding(models.Model):
    _name = 'audit.module.finding'
    _description = 'Módulo instalado detectado en auditoría'
    _order = 'module_category, name'

    project_id = fields.Many2one('audit.project', required=True, ondelete='cascade')
    name = fields.Char(string='Nombre técnico', required=True)
    display_name_module = fields.Char(string='Nombre legible')
    author = fields.Char(string='Autor')
    version = fields.Char(string='Versión')
    module_category = fields.Selection([
        ('odoo_official', 'Odoo Oficial'),
        ('oca', 'OCA'),
        ('custom', 'Custom'),
        ('enterprise', 'Enterprise'),
        ('localization', 'Localización'),
        ('unknown', 'Desconocido'),
    ], string='Categoría')
    is_relevant = fields.Boolean(
        string='Relevante para migración',
        compute='_compute_relevant',
        store=True,
    )
    compatibility_risk = fields.Selection([
        ('low', 'Bajo'),
        ('medium', 'Medio'),
        ('high', 'Alto'),
    ], string='Riesgo de compatibilidad', default='low')
    notes = fields.Text(string='Notas de migración')
    effort_hours = fields.Float(string='Horas estimadas')

    @api.depends('module_category')
    def _compute_relevant(self):
        for rec in self:
            rec.is_relevant = rec.module_category in ('custom', 'oca')
