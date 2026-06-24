from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval


class RunMigrationWizard(models.TransientModel):
    _name = 'run.migration.wizard'
    _description = 'Wizard de ejecución de migración'

    job_id = fields.Many2one('migration.job', required=True, readonly=True)
    dry_run = fields.Boolean(
        string='Dry Run (simulación)',
        help='Ejecuta validaciones y mapeos completos pero revierte todos los '
             'cambios al terminar. Los logs muestran exactamente qué habría ocurrido.',
    )
    confirm = fields.Boolean(
        string='Confirmo que deseo ejecutar esta migración en producción',
    )
    record_total = fields.Integer(
        string='Registros a procesar',
        compute='_compute_preview',
    )
    preview_html = fields.Html(
        string='Vista previa de datos (primeros 10 registros)',
        compute='_compute_preview',
        sanitize=False,
    )

    @api.depends('job_id')
    def _compute_preview(self):
        for wizard in self:
            if not wizard.job_id or not wizard.job_id.source_model_id:
                wizard.record_total = 0
                wizard.preview_html = '<p>Selecciona un trabajo de migración.</p>'
                continue
            try:
                job = wizard.job_id
                SourceModel = self.env[job.source_model_id.model]
                domain = safe_eval(job.domain or '[]')
                wizard.record_total = SourceModel.search_count(domain)

                sample = SourceModel.search(domain, limit=10)
                mapped_fields = job.field_map_ids.mapped('source_field_id.name')

                # Siempre incluir id + primer campo de nombre disponible + campos mapeados
                name_field = next(
                    (f for f in ('name', 'display_name') if f in SourceModel._fields),
                    None,
                )
                base_cols = ['id'] + ([name_field] if name_field else [])
                display_fields = list(dict.fromkeys(base_cols + mapped_fields))

                header_cells = ''.join(
                    f'<th style="padding:4px 8px;border:1px solid #ccc;background:#f0f0f0;">{f}</th>'
                    for f in display_fields
                )
                rows = ''
                for rec in sample:
                    cells = ''
                    for f in display_fields:
                        try:
                            val = rec[f]
                            if hasattr(val, 'display_name'):
                                val = val.display_name
                            cells += f'<td style="padding:4px 8px;border:1px solid #ccc;">{val}</td>'
                        except Exception:
                            cells += '<td style="padding:4px 8px;border:1px solid #ccc;">—</td>'
                    rows += f'<tr>{cells}</tr>'

                wizard.preview_html = f"""
                    <div style="overflow-x:auto;">
                    <table style="border-collapse:collapse;font-size:12px;width:100%;">
                        <thead><tr>{header_cells}</tr></thead>
                        <tbody>{rows}</tbody>
                    </table>
                    </div>
                    <p style="color:#888;font-size:11px;">
                        Mostrando {min(10, len(sample))} de {wizard.record_total} registros.
                        Columnas: id + campos mapeados en este job.
                    </p>
                """
            except Exception as e:
                wizard.record_total = -1
                wizard.preview_html = f'<p style="color:red;">Error generando preview: {e}</p>'

    def action_execute(self):
        self.ensure_one()
        if not self.dry_run and not self.confirm:
            raise UserError(
                'Debes marcar la casilla de confirmación para ejecutar en producción.'
            )
        run = self.env['migration.execution'].run(self.job_id, dry_run=self.dry_run)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resultado de la ejecución',
            'res_model': 'migration.execution.run',
            'view_mode': 'form',
            'res_id': run.id,
        }
