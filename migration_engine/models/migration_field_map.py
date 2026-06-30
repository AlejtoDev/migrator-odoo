from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MigrationFieldMap(models.Model):
    _name = 'migration.field.map'
    _description = 'Mapeo de campo en trabajo de migración'
    _order = 'job_id, sequence, id'

    job_id = fields.Many2one('migration.job', string='Trabajo', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Secuencia', default=10)
    source_field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo origen',
        domain="[('model_id', '=', parent.source_model_id)]",
        ondelete='cascade',
    )
    dest_field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo destino',
        domain="[('model_id', '=', parent.dest_model_id)]",
        required=True,
        ondelete='cascade',
    )
    transform_type = fields.Selection([
        ('direct', 'Directo'),
        ('fixed_value', 'Valor fijo'),
        ('python_expr', 'Expresión Python'),
        ('lookup', 'Lookup'),
    ], string='Transformación', required=True, default='direct')
    fixed_value = fields.Char(string='Valor fijo')
    python_expr = fields.Text(
        string='Expresión Python',
        help='Variables disponibles: value, record, env.',
    )
    lookup_model_id = fields.Many2one('ir.model', string='Modelo de lookup', ondelete='cascade')
    lookup_source_field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo búsqueda (lookup)',
        domain="[('model_id', '=', lookup_model_id)]",
        ondelete='cascade',
    )
    lookup_dest_field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo retorno (lookup)',
        domain="[('model_id', '=', lookup_model_id)]",
        ondelete='cascade',
    )
    required = fields.Boolean(
        string='Requerido',
        help='Si el mapeo falla y está marcado, el registro completo falla (rollback).',
        default=False,
    )

    @api.constrains('source_field_id', 'job_id')
    def _check_source_field_model(self):
        for rec in self:
            if rec.source_field_id and rec.source_field_id.model_id != rec.job_id.source_model_id:
                raise ValidationError(
                    f"El campo origen '{rec.source_field_id.name}' no pertenece al modelo origen del trabajo."
                )

    @api.constrains('dest_field_id', 'job_id')
    def _check_dest_field_model(self):
        for rec in self:
            if rec.dest_field_id and rec.dest_field_id.model_id != rec.job_id.dest_model_id:
                raise ValidationError(
                    f"El campo destino '{rec.dest_field_id.name}' no pertenece al modelo destino del trabajo."
                )

    @api.constrains('lookup_source_field_id', 'lookup_dest_field_id', 'lookup_model_id')
    def _check_lookup_fields(self):
        for rec in self:
            if rec.transform_type != 'lookup':
                continue
            if rec.lookup_source_field_id and rec.lookup_source_field_id.model_id != rec.lookup_model_id:
                raise ValidationError("El campo de búsqueda (lookup) no pertenece al modelo de lookup.")
            if rec.lookup_dest_field_id and rec.lookup_dest_field_id.model_id != rec.lookup_model_id:
                raise ValidationError("El campo de retorno (lookup) no pertenece al modelo de lookup.")
