from odoo import models, fields, api


class InstanceStudioField(models.Model):
    _name = 'instance.studio.field'
    _description = 'Inventario de campos x_studio_* de la instancia'
    _order = 'model_name, name'

    name = fields.Char(string='Nombre técnico', required=True)
    field_description = fields.Char(string='Etiqueta del campo')
    model_id = fields.Many2one('ir.model', string='Modelo', ondelete='cascade')
    model_name = fields.Char(string='Modelo (técnico)', related='model_id.model', store=True)
    field_type = fields.Char(string='Tipo de campo')
    last_scanned = fields.Datetime(string='Último escaneo')
    migration_impact = fields.Selection([
        ('0', 'Ninguno'),
        ('1', 'Bajo'),
        ('2', 'Medio'),
        ('3', 'Alto'),
    ], string='Impacto en migración', default='0')
    client_description = fields.Text(
        string='Descripción para el cliente',
        help='Qué hace este campo en términos de negocio: para qué se usa, quién lo llena, qué impacto tiene.',
    )
    migration_notes = fields.Text(
        string='Notas técnicas de migración',
        help='Cómo manejar este campo en la migración: ¿se mantiene?, ¿se mapea a otro campo?, ¿se puede perder?',
    )
    sample_values = fields.Text(string='Muestra de valores', store=False)

    @api.model
    def refresh_studio_fields(self):
        studio_fields = self.env['ir.model.fields'].sudo().search([
            ('name', 'like', 'x_studio_'),
            ('state', '=', 'manual'),
        ])
        existing = {
            (r.name, r.model_id.id): r
            for r in self.search([])
        }
        for sf in studio_fields:
            key = (sf.name, sf.model_id.id)
            vals = {
                'name': sf.name,
                'field_description': sf.field_description,
                'model_id': sf.model_id.id,
                'field_type': sf.ttype,
                'last_scanned': fields.Datetime.now(),
            }
            if key in existing:
                existing[key].write(vals)
            else:
                self.create(vals)
        return True

    def _compute_sample_values(self):
        for record in self:
            try:
                Model = self.env[record.model_name].sudo()
                results = Model.search(
                    [(record.name, 'not in', [False, ''])], limit=20
                ).mapped(record.name)
                seen = []
                for v in results:
                    sv = str(v)[:80]
                    if sv not in seen:
                        seen.append(sv)
                    if len(seen) >= 5:
                        break
                record.sample_values = '\n'.join(seen) if seen else '(sin valores)'
            except Exception as e:
                record.sample_values = f'Error: {e}'

    def action_load_sample_values(self):
        self._compute_sample_values()
