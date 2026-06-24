from odoo import models, fields


class GenerateReportWizard(models.TransientModel):
    _name = 'generate.report.wizard'
    _description = 'Generar informe de auditoría'

    project_id = fields.Many2one('audit.project', required=True, readonly=True)
    report_type = fields.Selection([
        ('executive', 'Resumen ejecutivo (para el cliente)'),
        ('technical', 'Informe técnico completo'),
        ('budget', 'Solo presupuesto'),
    ], string='Tipo de informe', default='executive')
    include_modules = fields.Boolean(default=True, string='Incluir inventario de módulos')
    include_fields = fields.Boolean(default=True, string='Incluir campos custom')
    include_models = fields.Boolean(default=False, string='Incluir modelos custom')
    include_volume = fields.Boolean(default=True, string='Incluir volumen de datos')
    include_effort = fields.Boolean(default=True, string='Incluir estimación de horas')

    def action_generate_pdf(self):
        self.ensure_one()
        return self.env.ref('migration_auditor.action_audit_report').report_action(
            self.project_id,
            data={
                'report_type': self.report_type,
                'include_modules': self.include_modules,
                'include_fields': self.include_fields,
                'include_models': self.include_models,
                'include_volume': self.include_volume,
                'include_effort': self.include_effort,
            }
        )
