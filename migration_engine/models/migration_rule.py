from odoo import models, fields


class MigrationRule(models.Model):
    _name = 'migration.rule'
    _description = 'Regla de validación PRE-transformación'
    _order = 'job_id, sequence, id'

    job_id = fields.Many2one('migration.job', string='Trabajo', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Secuencia', default=10)
    name = fields.Char(string='Nombre', required=True)
    field_id = fields.Many2one(
        'ir.model.fields',
        string='Campo',
        domain="[('model_id', '=', parent.source_model_id)]",
        required=True,
        ondelete='cascade',
    )
    rule_type = fields.Selection([
        ('not_null', 'No nulo'),
        ('type_check', 'Verificación de tipo'),
        ('format_regex', 'Formato regex'),
        ('python_expr', 'Expresión Python'),
    ], string='Tipo de regla', required=True, default='not_null')
    python_expr = fields.Text(
        string='Expresión Python',
        help='Variables disponibles: value, record, env. Debe retornar True/False.',
    )
    regex_pattern = fields.Char(string='Patrón regex')
    on_failure = fields.Selection([
        ('warning', 'Warning (continúa)'),
        ('error', 'Error (salta el registro)'),
    ], string='Al fallar', required=True, default='warning')
    active = fields.Boolean(string='Activo', default=True)
