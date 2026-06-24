# Prompt — Claude Code: módulo `migration_engine` para Odoo 17.0

## Contexto

Construye un módulo Odoo 17.0 llamado `migration_engine`. El módulo implementa un motor ETL
(Extract-Transform-Load) interno que permite migrar registros entre modelos de Odoo de forma
configurable, transaccional y con log detallado por ejecución.

El módulo NO migra bases de datos completas entre versiones de Odoo. Migra registros de un
modelo origen a un modelo destino dentro de la misma instancia, aplicando reglas de
transformación campo a campo.

---

## Estructura de archivos a crear

```
migration_engine/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── migration_job.py
│   ├── migration_execution_run.py   ← NUEVO: agrupa logs por ejecución
│   ├── migration_rule.py
│   ├── migration_field_map.py
│   ├── migration_log.py
│   └── migration_execution.py
├── wizards/
│   ├── __init__.py
│   └── run_migration_wizard.py
├── views/
│   ├── migration_job_views.xml
│   ├── migration_execution_run_views.xml   ← NUEVO
│   ├── migration_rule_views.xml
│   ├── migration_log_views.xml
│   └── menus.xml
├── security/
│   ├── migration_security.xml
│   └── ir.model.access.csv
└── data/
    └── migration_data.xml
```

---

## `__manifest__.py`

```python
{
    'name': 'Migration Engine',
    'version': '17.0.1.0.0',
    'summary': 'Motor ETL configurable con transformación por capas, log por ejecución y export',
    'category': 'Technical',
    'author': 'AlejtoDev',
    'website': 'https://odoo.alejtodev.cl',
    'depends': ['base', 'web'],
    'data': [
        'security/migration_security.xml',
        'security/ir.model.access.csv',
        'data/migration_data.xml',
        'views/migration_log_views.xml',
        'views/migration_execution_run_views.xml',
        'views/migration_rule_views.xml',
        'views/migration_job_views.xml',
        'views/menus.xml',
    ],
    'license': 'OPL-1',
    'installable': True,
    'application': True,
}
```

---

## Modelo: `migration.job` (`models/migration_job.py`)

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre del trabajo, required |
| `source_model_id` | Many2one → `ir.model` | Modelo origen |
| `dest_model_id` | Many2one → `ir.model` | Modelo destino |
| `domain` | Char | Dominio de filtro sobre el modelo origen. Default `'[]'` |
| `mode` | Selection | `create_only`, `update_only`, `create_or_update`. Default `create_only` |
| `key_field_ids` | Many2many → `ir.model.fields` | Campos clave para modo `create_or_update` / `update_only`. Se usan para buscar el registro destino antes de crear o actualizar |
| `field_map_ids` | One2many → `migration.field.map` | Mapeos de campo |
| `rule_ids` | One2many → `migration.rule` | Reglas de transformación |
| `execution_run_ids` | One2many → `migration.execution.run` | Historial de ejecuciones |
| `state` | Selection | `draft`, `running`, `done`, `partial`, `error`. Default `draft` |
| `last_run` | Datetime | Fecha/hora de la última ejecución (compute desde la última `execution_run_id`) |
| `total_runs` | Integer | Cantidad de ejecuciones acumuladas (compute) |
| `notes` | Text | Notas internas |

### Métodos

- `action_run()`: Abre el wizard `run.migration.wizard` con `job_id = self.id`
- `action_view_runs()`: Acción del smart button "Ejecuciones" → abre `migration.execution.run` filtrado por job
- `_compute_last_run()`: Toma la `execution_date` de la última `execution_run_id` ordenada por fecha desc
- `_compute_total_runs()`: Cuenta `execution_run_ids`

### Nota sobre `key_field_ids`

El domain del Many2many en la vista debe filtrar por `model_id = source_model_id` del job, ya que
las claves se leen del modelo ORIGEN para construir el dominio de búsqueda en el modelo DESTINO.
Ver implementación en `migration.execution._resolve_dest_record()`.

---

## Modelo: `migration.execution.run` (`models/migration_execution_run.py`)

Agrupa todos los logs de una ejecución única (un "disparo" del job). Permite comparar
ejecuciones históricas sin mezclar logs.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre generado automáticamente: `"Ejecución #N — {job.name}"` con sequence |
| `job_id` | Many2one → `migration.job` | Trabajo padre, required |
| `execution_date` | Datetime | Fecha/hora de inicio, default `fields.Datetime.now()` |
| `end_date` | Datetime | Fecha/hora de fin |
| `dry_run` | Boolean | Si fue una ejecución de simulación |
| `state` | Selection | `running`, `done`, `partial`, `error` |
| `log_ids` | One2many → `migration.log` | Logs de esta ejecución |
| `total_records` | Integer | Total de registros procesados (compute desde log_ids) |
| `success_count` | Integer | Registros con log_type `info` (compute) |
| `warning_count` | Integer | Registros con log_type `warning` (compute) |
| `error_count` | Integer | Registros con log_type `error` (compute) |
| `duration_seconds` | Float | Duración en segundos (compute: `end_date - execution_date`) |

### Métodos

- `_compute_counts()`: Agrupa `log_ids` por `log_type` y cuenta cada uno
- `_compute_duration()`: Calcula `(end_date - execution_date).total_seconds()`
- `action_export_logs_csv()`: Exporta los logs de esta ejecución a CSV. Ver sección "Export de logs"

---

## Modelo: `migration.field.map` (`models/migration_field_map.py`)

Mapeo campo a campo entre modelo origen y modelo destino.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre, required |
| `sequence` | Integer | Orden de evaluación, default 10 |
| `source_field_id` | Many2one → `ir.model.fields` | Campo del modelo origen |
| `dest_field_id` | Many2one → `ir.model.fields` | Campo del modelo destino |
| `transform_type` | Selection | `direct`, `fixed_value`, `python_expr`, `lookup` |
| `fixed_value` | Char | Valor fijo cuando `transform_type == 'fixed_value'` |
| `python_expr` | Text | Expresión Python evaluada con `safe_eval`. Variables disponibles: `value` (valor del campo origen), `record` (registro origen browse), `env` (self.env) |
| `lookup_model_id` | Many2one → `ir.model` | Modelo de lookup cuando `transform_type == 'lookup'` |
| `lookup_source_field_id` | Many2one → `ir.model.fields` | Campo de búsqueda en el modelo de lookup |
| `lookup_dest_field_id` | Many2one → `ir.model.fields` | Campo a retornar del modelo de lookup |
| `required` | Boolean | Si el mapeo falla y `required=True`, el registro entero falla (rollback). Si `required=False`, se omite el campo y continúa |

### Restricciones (`@api.constrains`)

- `source_field_id` debe pertenecer a `job_id.source_model_id`
- `dest_field_id` debe pertenecer a `job_id.dest_model_id`
- Cuando `transform_type == 'lookup'`: `lookup_source_field_id` debe pertenecer a `lookup_model_id`, `lookup_dest_field_id` también

### Filtros de dominio en la vista XML

```xml
<!-- source_field_id filtrado por modelo origen del job -->
<field name="source_field_id"
       domain="[('model_id', '=', parent.source_model_id)]"/>

<!-- dest_field_id filtrado por modelo destino del job -->
<field name="dest_field_id"
       domain="[('model_id', '=', parent.dest_model_id)]"/>
```

---

## Modelo: `migration.rule` (`models/migration_rule.py`)

Reglas de validación y limpieza PRE-transformación. Se evalúan sobre el registro origen antes
de construir el dict de valores destino.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre, required |
| `sequence` | Integer | Orden de evaluación, default 10 |
| `name` | Char | Nombre descriptivo, required |
| `field_id` | Many2one → `ir.model.fields` | Campo a validar (del modelo origen) |
| `rule_type` | Selection | `not_null`, `type_check`, `format_regex`, `python_expr` |
| `python_expr` | Text | Expresión Python con `safe_eval`. Variables: `value`, `record`, `env` |
| `regex_pattern` | Char | Patrón regex cuando `rule_type == 'format_regex'` |
| `on_failure` | Selection | `warning` (loguea y continúa con el registro) / `error` (salta el registro sin SAVEPOINT) |
| `active` | Boolean | Default True |

---

## Modelo: `migration.log` (`models/migration_log.py`)

Un registro por evento: un OK, un warning o un error. Siempre vinculado a una
`migration.execution.run`, que agrupa todos los logs de una ejecución.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `execution_run_id` | Many2one → `migration.execution.run` | Ejecución padre, required |
| `job_id` | Many2one → `migration.job` | Related de `execution_run_id.job_id`, store=True, para filtrar rápido |
| `execution_date` | Datetime | Fecha/hora del evento |
| `log_type` | Selection | `info`, `warning`, `error` |
| `source_record_id_int` | Integer | ID del registro origen |
| `source_model` | Char | Nombre técnico del modelo origen |
| `field_name` | Char | Campo involucrado (si aplica) |
| `rule_name` | Char | Nombre de la regla que falló (si aplica) |
| `message` | Text | Mensaje descriptivo del evento |
| `traceback` | Text | Traceback completo (si es error de excepción) |
| `was_rollback` | Boolean | Si el registro fue revertido por savepoint |
| `dry_run` | Boolean | Si el log pertenece a una ejecución de simulación |

---

## Modelo: `migration.execution` (`models/migration_execution.py`)

AbstractModel. Corazón del módulo. Implementa la ejecución transaccional completa.

```python
from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval
import traceback as tb
import logging

_logger = logging.getLogger(__name__)


class MigrationExecution(models.AbstractModel):
    _name = 'migration.execution'
    _description = 'Motor de ejecución ETL con savepoints'
    _auto = False  # AbstractModel sin tabla propia
```

### Método principal: `run(self, job, dry_run=False)`

```python
def run(self, job, dry_run=False):
    """
    Punto de entrada de la ejecución. Crea un migration.execution.run,
    procesa cada registro del modelo origen y actualiza el run al terminar.
    """
    # 1. Crear el execution run
    run = self.env['migration.execution.run'].create({
        'job_id': job.id,
        'dry_run': dry_run,
        'state': 'running',
        'execution_date': fields.Datetime.now(),
    })
    job.write({'state': 'running'})

    SourceModel = self.env[job.source_model_id.model]
    domain = safe_eval(job.domain or '[]')
    records = SourceModel.search(domain)

    has_errors = False
    has_warnings = False

    # 2. Savepoint global para dry_run
    global_sp = f'migration_dry_run_{run.id}'
    if dry_run:
        self.env.cr.execute(f'SAVEPOINT {global_sp}')

    for record in records:
        result = self._process_record(job, run, record, dry_run)
        if result == 'error':
            has_errors = True
        elif result == 'warning':
            has_warnings = True

    # 3. Rollback global si es dry_run
    if dry_run:
        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {global_sp}')
        # Limpiar cache después del rollback global
        self.env.invalidate_all()
        # Re-crear el run y sus logs (fueron revertidos por el rollback global)
        # Nota: los logs del dry_run se crean DESPUÉS del rollback global,
        # por eso _process_record acumula resultados en memoria durante dry_run
        # y los persiste aquí. Ver implementación de _process_record.

    # 4. Actualizar estado del run y del job
    final_state = 'error' if has_errors and not has_warnings else \
                  'partial' if has_errors else \
                  'done'
    run.write({
        'state': final_state,
        'end_date': fields.Datetime.now(),
    })
    job.write({'state': final_state})

    return run
```

### Método: `_process_record(self, job, run, record, dry_run)`

```python
def _process_record(self, job, run, record, dry_run):
    """
    Procesa un único registro origen. Retorna 'ok', 'warning' o 'error'.
    """
    # FASE 1: Validación
    validation_result, validation_logs = self._validate_record(job, run, record)
    if validation_result == 'fatal':
        # Loguear y saltar sin savepoint
        for log_vals in validation_logs:
            self._write_log(run, log_vals, dry_run)
        return 'error'

    # FASE 2: Mapeo dinámico
    try:
        vals = self._apply_field_maps(job, record)
    except Exception as e:
        self._write_log(run, {
            'log_type': 'error',
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': f'Error en mapeo de campos: {str(e)}',
            'traceback': tb.format_exc(),
        }, dry_run)
        return 'error'

    # FASE 3: Resolución del registro destino (para update_only / create_or_update)
    dest_record = None
    if job.mode in ('update_only', 'create_or_update'):
        dest_record = self._resolve_dest_record(job, record, vals)
        if not dest_record and job.mode == 'update_only':
            self._write_log(run, {
                'log_type': 'warning',
                'source_record_id_int': record.id,
                'source_model': record._name,
                'message': 'Modo update_only: no se encontró registro destino. Registro omitido.',
            }, dry_run)
            return 'warning'

    # FASE 4: Ejecución transaccional (solo si no es dry_run)
    if dry_run:
        action = 'CREATE' if not dest_record else 'UPDATE'
        self._write_log(run, {
            'log_type': 'info',
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': f'[DRY RUN] {action} procesable. Vals: {vals}',
        }, dry_run)
        # Emitir logs de validación con warnings si los hay
        for log_vals in validation_logs:
            self._write_log(run, log_vals, dry_run)
        return 'warning' if validation_logs else 'ok'

    DestModel = self.env[job.dest_model_id.model]
    sp_name = f'migration_sp_{run.id}_{record.id}'
    self.env.cr.execute(f'SAVEPOINT {sp_name}')
    try:
        if dest_record:
            dest_record.write(vals)
        else:
            DestModel.create(vals)
        self.env.cr.execute(f'RELEASE SAVEPOINT {sp_name}')

        # Loguear OK + warnings de validación si los hubo
        log_type = 'warning' if validation_logs else 'info'
        self._write_log(run, {
            'log_type': log_type,
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': 'Registro migrado correctamente' + (
                f' (con {len(validation_logs)} warning(s) de validación)' if validation_logs else ''
            ),
        }, dry_run)
        for log_vals in validation_logs:
            self._write_log(run, log_vals, dry_run)

        return 'warning' if validation_logs else 'ok'

    except Exception as e:
        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp_name}')
        self.env.invalidate_all()
        self._write_log(run, {
            'log_type': 'error',
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': f'Error en create/write: {str(e)}',
            'traceback': tb.format_exc(),
            'was_rollback': True,
        }, dry_run)
        return 'error'
```

### Método: `_validate_record(self, job, run, record)`

```python
def _validate_record(self, job, run, record):
    """
    Evalúa todas las reglas activas del job sobre el registro origen.
    Retorna ('ok'|'fatal', [lista de log_vals pendientes]).
    'fatal' = al menos una regla con on_failure='error' falló.
    """
    pending_logs = []
    for rule in job.rule_ids.filtered('active').sorted('sequence'):
        try:
            field_value = record[rule.field_id.name]
            passed = self._evaluate_rule(rule, field_value, record)
            if not passed:
                log_vals = {
                    'log_type': 'warning' if rule.on_failure == 'warning' else 'error',
                    'source_record_id_int': record.id,
                    'source_model': record._name,
                    'field_name': rule.field_id.name,
                    'rule_name': rule.name,
                    'message': f"Regla '{rule.name}' falló en campo '{rule.field_id.name}'",
                }
                if rule.on_failure == 'error':
                    pending_logs.append(log_vals)
                    return 'fatal', pending_logs
                pending_logs.append(log_vals)
        except Exception as e:
            log_vals = {
                'log_type': 'error',
                'source_record_id_int': record.id,
                'source_model': record._name,
                'field_name': rule.field_id.name,
                'rule_name': rule.name,
                'message': f"Excepción evaluando regla '{rule.name}': {str(e)}",
                'traceback': tb.format_exc(),
            }
            pending_logs.append(log_vals)
            return 'fatal', pending_logs
    return 'ok', pending_logs
```

### Método: `_evaluate_rule(self, rule, value, record)`

```python
def _evaluate_rule(self, rule, value, record):
    import re
    if rule.rule_type == 'not_null':
        return bool(value) or value == 0  # 0 es válido para enteros
    elif rule.rule_type == 'type_check':
        return value is not None
    elif rule.rule_type == 'format_regex':
        return bool(re.match(rule.regex_pattern or '', str(value or '')))
    elif rule.rule_type == 'python_expr':
        local_dict = {'value': value, 'record': record, 'env': self.env}
        return bool(safe_eval(rule.python_expr, local_dict))
    return True
```

### Método: `_apply_field_maps(self, job, record)`

```python
def _apply_field_maps(self, job, record):
    """
    Construye el dict de valores para el modelo destino aplicando
    los field_maps en orden de secuencia.
    """
    vals = {}
    for fmap in job.field_map_ids.sorted('sequence'):
        source_val = record[fmap.source_field_id.name]
        dest_field = fmap.dest_field_id.name
        dest_field_type = fmap.dest_field_id.ttype

        try:
            if fmap.transform_type == 'direct':
                transformed = source_val
            elif fmap.transform_type == 'fixed_value':
                transformed = fmap.fixed_value
            elif fmap.transform_type == 'python_expr':
                local_dict = {'value': source_val, 'record': record, 'env': self.env}
                transformed = safe_eval(fmap.python_expr, local_dict)
            elif fmap.transform_type == 'lookup':
                LookupModel = self.env[fmap.lookup_model_id.model]
                lookup_rec = LookupModel.search(
                    [(fmap.lookup_source_field_id.name, '=', source_val)], limit=1
                )
                transformed = lookup_rec[fmap.lookup_dest_field_id.name] if lookup_rec else False
            else:
                transformed = source_val

            # Conversión de tipo para Many2one: asegurarse de pasar el ID entero
            if dest_field_type == 'many2one' and hasattr(transformed, 'id'):
                transformed = transformed.id

            vals[dest_field] = transformed

        except Exception as e:
            if fmap.required:
                raise ValueError(
                    f"Mapeo requerido '{fmap.source_field_id.name}' → "
                    f"'{dest_field}' falló: {str(e)}"
                ) from e
            # Si no es required, omitir el campo silenciosamente
            _logger.warning(
                'migration_engine: campo no-required omitido: %s → %s: %s',
                fmap.source_field_id.name, dest_field, str(e)
            )

    return vals
```

### Método: `_resolve_dest_record(self, job, source_record, vals)`

```python
def _resolve_dest_record(self, job, source_record, vals):
    """
    Para modos 'update_only' y 'create_or_update'.
    Busca el registro destino usando los key_field_ids del job.
    Los key_field_ids son campos del modelo ORIGEN; sus valores
    se usan para buscar campos homónimos en el modelo DESTINO.
    Retorna el browse del registro destino o False si no se encuentra.
    """
    if not job.key_field_ids:
        return False

    DestModel = self.env[job.dest_model_id.model]
    domain = []
    for key_field in job.key_field_ids:
        field_name = key_field.name
        # El valor puede venir de vals (ya transformado) o del source_record
        value = vals.get(field_name, source_record[field_name])
        if hasattr(value, 'id'):
            value = value.id
        domain.append((field_name, '=', value))

    return DestModel.search(domain, limit=1)
```

### Método: `_write_log(self, run, log_vals, dry_run)`

```python
def _write_log(self, run, log_vals, dry_run=False):
    """
    Crea un migration.log vinculado al execution run.
    Agrega campos automáticos: execution_run_id, job_id, execution_date, dry_run.
    """
    self.env['migration.log'].create({
        'execution_run_id': run.id,
        'job_id': run.job_id.id,
        'execution_date': fields.Datetime.now(),
        'dry_run': dry_run,
        'was_rollback': False,
        **log_vals,
    })
```

---

## Wizard: `run.migration.wizard` (`wizards/run_migration_wizard.py`)

```python
from odoo import models, fields, api
from odoo.exceptions import UserError


class RunMigrationWizard(models.TransientModel):
    _name = 'run.migration.wizard'
    _description = 'Wizard de ejecución de migración'

    job_id = fields.Many2one('migration.job', required=True, readonly=True)
    mode_display = fields.Char(related='job_id.mode', string='Modo', readonly=True)
    dry_run = fields.Boolean(
        string='Dry Run (simulación)',
        help='Ejecuta la migración completa incluyendo validaciones y mapeos, '
             'pero hace ROLLBACK al final. Los logs muestran exactamente qué '
             'habría ocurrido sin modificar ningún dato.'
    )
    confirm = fields.Boolean(
        string='Confirmo que deseo ejecutar esta migración en producción'
    )
    record_preview = fields.Integer(
        string='Registros a procesar (estimado)',
        compute='_compute_record_preview',
    )

    @api.depends('job_id')
    def _compute_record_preview(self):
        from odoo.tools.safe_eval import safe_eval
        for wizard in self:
            try:
                SourceModel = self.env[wizard.job_id.source_model_id.model]
                domain = safe_eval(wizard.job_id.domain or '[]')
                wizard.record_preview = SourceModel.search_count(domain)
            except Exception:
                wizard.record_preview = -1

    def action_execute(self):
        self.ensure_one()
        if not self.dry_run and not self.confirm:
            raise UserError(
                'Debes marcar la casilla de confirmación para ejecutar la migración en producción.'
            )
        run = self.env['migration.execution'].run(self.job_id, dry_run=self.dry_run)
        # Redirigir al execution run creado
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resultado de la ejecución',
            'res_model': 'migration.execution.run',
            'view_mode': 'form',
            'res_id': run.id,
        }
```

---

## Vistas

### `migration_job_views.xml`

**Form view de `migration.job`**:

```xml
<record id="view_migration_job_form" model="ir.ui.view">
    <field name="name">migration.job.form</field>
    <field name="model">migration.job</field>
    <field name="arch" type="xml">
        <form>
            <header>
                <button name="action_run" string="Ejecutar / Dry Run"
                        type="object" class="oe_highlight"
                        attrs="{'invisible': [('state', '=', 'running')]}"/>
                <field name="state" widget="statusbar"
                       statusbar_visible="draft,running,done,partial,error"/>
            </header>
            <sheet>
                <!-- Smart buttons -->
                <div class="oe_button_box" name="button_box">
                    <button name="action_view_runs" type="object"
                            class="oe_stat_button" icon="fa-history">
                        <field name="total_runs" widget="statinfo" string="Ejecuciones"/>
                    </button>
                </div>
                <group>
                    <group>
                        <field name="name"/>
                        <field name="source_model_id"/>
                        <field name="dest_model_id"/>
                        <field name="mode"/>
                    </group>
                    <group>
                        <field name="domain" widget="domain"
                               options="{'model': 'source_model_id'}"/>
                        <field name="key_field_ids"
                               domain="[('model_id', '=', source_model_id)]"
                               widget="many2many_tags"
                               attrs="{'invisible': [('mode', '=', 'create_only')],
                                       'required': [('mode', 'in', ['update_only', 'create_or_update'])]}"/>
                        <field name="last_run"/>
                    </group>
                </group>
                <field name="notes" placeholder="Notas internas..."/>
                <notebook>
                    <page string="Mapeo de campos">
                        <field name="field_map_ids" context="{'default_job_id': active_id}">
                            <tree editable="bottom">
                                <field name="sequence" widget="handle"/>
                                <field name="source_field_id"
                                       domain="[('model_id', '=', parent.source_model_id)]"/>
                                <field name="dest_field_id"
                                       domain="[('model_id', '=', parent.dest_model_id)]"/>
                                <field name="transform_type"/>
                                <field name="fixed_value"
                                       attrs="{'invisible': [('transform_type', '!=', 'fixed_value')],
                                               'required': [('transform_type', '=', 'fixed_value')]}"/>
                                <field name="required"/>
                            </tree>
                        </field>
                    </page>
                    <page string="Reglas de validación">
                        <field name="rule_ids" context="{'default_job_id': active_id}">
                            <tree editable="bottom">
                                <field name="sequence" widget="handle"/>
                                <field name="name"/>
                                <field name="field_id"
                                       domain="[('model_id', '=', parent.source_model_id)]"/>
                                <field name="rule_type"/>
                                <field name="on_failure"/>
                                <field name="active"/>
                            </tree>
                        </field>
                    </page>
                </notebook>
            </sheet>
        </form>
    </field>
</record>
```

**Tree view de `migration.job`**:

Columnas: `name`, `source_model_id`, `dest_model_id`, `mode`, `state`, `last_run`, `total_runs`.
Decorations: `decoration-danger="state == 'error'"`, `decoration-warning="state == 'partial'"`,
`decoration-success="state == 'done'"`.

**Search view de `migration.job`**:

Filtros: `state == 'draft'`, `state == 'done'`, `state in ('error', 'partial')`.
Group by: `state`, `source_model_id`, `mode`.

---

### `migration_execution_run_views.xml`

**Form view de `migration.execution.run`**:

```xml
<record id="view_migration_execution_run_form" model="ir.ui.view">
    <field name="name">migration.execution.run.form</field>
    <field name="model">migration.execution.run</field>
    <field name="arch" type="xml">
        <form>
            <header>
                <button name="action_export_logs_csv" string="Exportar logs CSV"
                        type="object" icon="fa-download"/>
                <field name="state" widget="statusbar"
                       statusbar_visible="running,done,partial,error"/>
            </header>
            <sheet>
                <!-- Badges de resumen -->
                <div class="oe_button_box" name="button_box">
                    <button class="oe_stat_button" icon="fa-check-circle" attrs="{'invisible': [('success_count', '=', 0)]}">
                        <field name="success_count" widget="statinfo" string="OK"/>
                    </button>
                    <button class="oe_stat_button" icon="fa-exclamation-triangle" attrs="{'invisible': [('warning_count', '=', 0)]}">
                        <field name="warning_count" widget="statinfo" string="Warnings"/>
                    </button>
                    <button class="oe_stat_button" icon="fa-times-circle" attrs="{'invisible': [('error_count', '=', 0)]}">
                        <field name="error_count" widget="statinfo" string="Errores"/>
                    </button>
                </div>
                <group>
                    <group>
                        <field name="name"/>
                        <field name="job_id"/>
                        <field name="dry_run"/>
                    </group>
                    <group>
                        <field name="execution_date"/>
                        <field name="end_date"/>
                        <field name="duration_seconds" string="Duración (seg)"/>
                        <field name="total_records"/>
                    </group>
                </group>
                <!-- Logs inline -->
                <field name="log_ids" readonly="1">
                    <tree decoration-danger="log_type == 'error'"
                          decoration-warning="log_type == 'warning'"
                          decoration-success="log_type == 'info'">
                        <field name="execution_date"/>
                        <field name="log_type" widget="badge"
                               decoration-danger="log_type == 'error'"
                               decoration-warning="log_type == 'warning'"
                               decoration-success="log_type == 'info'"/>
                        <field name="source_model"/>
                        <field name="source_record_id_int"/>
                        <field name="field_name"/>
                        <field name="rule_name"/>
                        <field name="message"/>
                        <field name="was_rollback"/>
                    </tree>
                </field>
            </sheet>
        </form>
    </field>
</record>
```

**Tree view de `migration.execution.run`**:

Columnas: `name`, `job_id`, `execution_date`, `duration_seconds`, `dry_run`, `state`,
`total_records`, `success_count`, `warning_count`, `error_count`.
Decorations por `state`.

**Search view de `migration.execution.run`**:

Filtros: Solo dry run, Solo ejecuciones reales, Con errores, Hoy.
Group by: `job_id`, `state`, `dry_run`.

---

### `migration_log_views.xml`

**Tree view de `migration.log`**:

```xml
<tree decoration-danger="log_type == 'error'"
      decoration-warning="log_type == 'warning'"
      decoration-success="log_type == 'info'">
    <field name="execution_date"/>
    <field name="log_type" widget="badge"
           decoration-danger="log_type == 'error'"
           decoration-warning="log_type == 'warning'"
           decoration-success="log_type == 'info'"/>
    <field name="dry_run"/>
    <field name="job_id"/>
    <field name="source_model"/>
    <field name="source_record_id_int" string="ID origen"/>
    <field name="field_name"/>
    <field name="rule_name"/>
    <field name="message"/>
    <field name="was_rollback"/>
</tree>
```

**Form view de `migration.log`**:

Todos los campos. El campo `traceback` se muestra en un widget `text` con `style="font-family: monospace; white-space: pre-wrap;"` aplicado via `attrs` o directamente en el elemento `<field>`.

**Search view de `migration.log`**:

Filtros rápidos: Solo errores, Solo warnings, Solo info, Con rollback, Dry run, Hoy.
Group by: `log_type`, `job_id`, `execution_run_id`, `source_model`, fecha.

---

### `menus.xml`

```xml
<menuitem id="menu_migration_root" name="Migration Engine" sequence="80"
          web_icon="migration_engine,static/description/icon.png"/>

<menuitem id="menu_migration_jobs" name="Trabajos de Migración"
          parent="menu_migration_root"
          action="action_migration_job" sequence="10"/>

<menuitem id="menu_migration_runs" name="Historial de Ejecuciones"
          parent="menu_migration_root"
          action="action_migration_execution_run_all" sequence="20"/>

<menuitem id="menu_migration_logs" name="Logs"
          parent="menu_migration_root"
          action="action_migration_log_all" sequence="30"/>
```

---

## Export de logs a CSV (`action_export_logs_csv`)

Implementar en `migration.execution.run` como método que genera y descarga un CSV con todos
los logs de la ejecución. Usar la librería estándar `csv` de Python + `io.StringIO`.

```python
def action_export_logs_csv(self):
    import csv
    import io
    import base64
    from odoo.exceptions import UserError

    self.ensure_one()

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)

    # Cabecera
    writer.writerow([
        'Fecha',
        'Tipo',
        'Dry Run',
        'Modelo Origen',
        'ID Origen',
        'Campo',
        'Regla',
        'Mensaje',
        'Rollback',
        'Traceback',
    ])

    for log in self.log_ids.sorted('execution_date'):
        writer.writerow([
            log.execution_date.strftime('%Y-%m-%d %H:%M:%S') if log.execution_date else '',
            log.log_type,
            'Sí' if log.dry_run else 'No',
            log.source_model,
            log.source_record_id_int,
            log.field_name or '',
            log.rule_name or '',
            log.message or '',
            'Sí' if log.was_rollback else 'No',
            (log.traceback or '').replace('\n', ' | '),
        ])

    csv_content = output.getvalue()
    output.close()

    filename = f'migration_logs_{self.job_id.name}_{self.execution_date.strftime("%Y%m%d_%H%M%S")}.csv'

    # Crear adjunto temporal y devolver acción de descarga
    attachment = self.env['ir.attachment'].create({
        'name': filename,
        'type': 'binary',
        'datas': base64.b64encode(csv_content.encode('utf-8')),
        'mimetype': 'text/csv',
        'res_model': self._name,
        'res_id': self.id,
    })

    return {
        'type': 'ir.actions.act_url',
        'url': f'/web/content/{attachment.id}?download=true',
        'target': 'self',
    }
```

---

## Seguridad

### Grupos (`security/migration_security.xml`)

```xml
<odoo>
    <data>
        <record id="module_category_migration" model="ir.module.category">
            <field name="name">Migration Engine</field>
            <field name="sequence">80</field>
        </record>

        <record id="group_migration_user" model="res.groups">
            <field name="name">Usuario</field>
            <field name="category_id" ref="module_category_migration"/>
        </record>

        <record id="group_migration_manager" model="res.groups">
            <field name="name">Manager</field>
            <field name="category_id" ref="module_category_migration"/>
            <field name="implied_ids" eval="[(4, ref('group_migration_user'))]"/>
        </record>
    </data>
</odoo>
```

### `ir.model.access.csv`

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_migration_job_mgr,migration.job manager,model_migration_job,group_migration_manager,1,1,1,1
access_migration_job_usr,migration.job user,model_migration_job,group_migration_user,1,0,0,0
access_migration_exec_run_mgr,migration.execution.run manager,model_migration_execution_run,group_migration_manager,1,1,1,1
access_migration_exec_run_usr,migration.execution.run user,model_migration_execution_run,group_migration_user,1,0,0,0
access_migration_field_map_mgr,migration.field.map manager,model_migration_field_map,group_migration_manager,1,1,1,1
access_migration_rule_mgr,migration.rule manager,model_migration_rule,group_migration_manager,1,1,1,1
access_migration_log_mgr,migration.log manager,model_migration_log,group_migration_manager,1,1,1,1
access_migration_log_usr,migration.log user,model_migration_log,group_migration_user,1,0,0,0
access_run_migration_wizard_mgr,run.migration.wizard manager,model_run_migration_wizard,group_migration_manager,1,1,1,1
```

---

## Consideraciones técnicas críticas para Odoo 17

### 1. `safe_eval` siempre

```python
from odoo.tools.safe_eval import safe_eval
# NUNCA usar eval() directo para expresiones de usuario
```

### 2. Savepoints y cache del ORM

Después de `ROLLBACK TO SAVEPOINT`, el cache interno del environment de Odoo queda
desincronizado con la base de datos. Siempre limpiar:

```python
self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp_name}')
self.env.invalidate_all()
```

Esto aplica tanto al savepoint por registro como al savepoint global del dry_run.

### 3. `AbstractModel` sin tabla

`migration.execution` no genera tabla en PostgreSQL. Requiere `_auto = False` explícito.

### 4. Widget `domain` en vistas

Para el campo `domain` del job, usar el widget `domain` de Odoo con la opción `model` apuntando
al campo `source_model_id`. Esto muestra el constructor visual de dominio:

```xml
<field name="domain" widget="domain" options="{'model': 'source_model_id'}"/>
```

### 5. Dry run con logs persistidos correctamente

El dry run usa un `SAVEPOINT` global que revierte todos los `create`/`write` del modelo destino.
Sin embargo, los logs (`migration.log`) son creados por `_write_log` que también usa el mismo
cursor. Hay dos aproximaciones:

**Opción A (recomendada)**: Usar un cursor separado para los logs del dry run:
```python
# En _write_log, cuando dry_run=True:
with self.env.registry.cursor() as new_cr:
    env2 = api.Environment(new_cr, self.env.uid, self.env.context)
    env2['migration.log'].create(log_vals)
    new_cr.commit()
```

**Opción B (más simple)**: Los logs se crean después del ROLLBACK global. Durante el dry_run,
`_process_record` acumula los resultados en una lista en memoria y al final de `run()`,
después del `ROLLBACK TO SAVEPOINT global_sp`, se crean todos los logs.

Implementar la **Opción B** por simplicidad. La lista de resultados acumulados en `run()`:

```python
# En run(), durante dry_run:
pending_log_entries = []  # lista de dicts

# _process_record retorna además la lista de log_vals en lugar de escribirlos directamente
# Al final, después del ROLLBACK:
self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {global_sp}')
self.env.invalidate_all()
# Re-crear el run (fue revertido)
run = self.env['migration.execution.run'].create({...final_state...})
for log_vals in pending_log_entries:
    self.env['migration.log'].create({'execution_run_id': run.id, **log_vals})
```

Adaptar `_process_record` para retornar `(result_str, [log_vals_list])` cuando `dry_run=True`
en lugar de escribir directamente.

### 6. Campo `domain` en `migration.job` vs `key_field_ids`

El campo `key_field_ids` es `Many2many → ir.model.fields`. En Odoo 17, los Many2many a
`ir.model.fields` funcionan bien, pero asegurarse de agregar el campo de relación intermedia
explícitamente en la definición si Odoo no lo infiere:

```python
key_field_ids = fields.Many2many(
    'ir.model.fields',
    'migration_job_key_fields_rel',  # tabla intermedia explícita
    'job_id',
    'field_id',
    string='Campos clave',
    domain="[('model_id', '=', source_model_id)]",
)
```

### 7. Nombre único del savepoint por ejecución

El formato `migration_sp_{run.id}_{record.id}` garantiza unicidad siempre que no haya dos
runs simultáneos del mismo job para el mismo record. Para mayor seguridad, agregar un UUID
corto o timestamp al prefijo del run.

---

## Flujo de usuario completo

1. **Migration Engine > Trabajos** → Nuevo trabajo
2. Seleccionar modelo origen y destino; elegir modo (`create_only` / `create_or_update` / etc.)
3. Si el modo requiere clave: seleccionar `key_field_ids`
4. Definir domain visual de filtro
5. Pestaña **Mapeo de campos**: agregar correspondencias con tipo de transformación
6. Pestaña **Reglas de validación**: agregar validaciones con severidad
7. Botón **Ejecutar / Dry Run** → Wizard muestra estimado de registros
8. Marcar "Dry Run" → Ejecutar → Ver resultado en `migration.execution.run` form
9. Revisar logs inline: filtrar por tipo, ver traceback en el form del log
10. Exportar CSV si necesario
11. Si dry run OK: volver al wizard, desmarcar Dry Run, marcar confirmación → Ejecutar en producción
12. **Migration Engine > Historial de Ejecuciones**: comparar ejecuciones anteriores
