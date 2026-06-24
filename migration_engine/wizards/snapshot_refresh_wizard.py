from odoo import models, fields


class SnapshotRefreshWizard(models.TransientModel):
    _name = 'snapshot.refresh.wizard'
    _description = 'Asistente de reescaneo de instancia'

    refresh_modules = fields.Boolean(string='Refrescar módulos instalados', default=True)
    refresh_studio_fields = fields.Boolean(string='Refrescar campos Studio (x_studio_*)', default=True)
    modules_found = fields.Integer(string='Módulos detectados', readonly=True)
    studio_fields_found = fields.Integer(string='Campos Studio detectados', readonly=True)
    scan_done = fields.Boolean(default=False)

    def action_refresh(self):
        self.ensure_one()
        if self.refresh_modules:
            self.env['instance.module.status'].refresh_snapshot()
            self.modules_found = self.env['instance.module.status'].search_count([])
        if self.refresh_studio_fields:
            self.env['instance.studio.field'].refresh_studio_fields()
            self.studio_fields_found = self.env['instance.studio.field'].search_count([])
        self.scan_done = True
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
