# Prompt — Claude Code: módulo `migration_engine` para Odoo 17.0

## Contexto

Construye un módulo Odoo 17.0 llamado `migration_engine`. El módulo implementa un motor ETL (Extract-Transform-Load) interno que permite migrar datos entre modelos de Odoo de forma configurable, transaccional y con log detallado. El usuario configura trabajos de migración con reglas de transformación desde la interfaz, ejecuta el trabajo y revisa los resultados en una página de logs.

El módulo NO migra bases de datos completas entre versiones de Odoo. Migra registros de un modelo origen a un modelo destino dentro de la misma instancia, aplicando reglas de transformación campo a campo.

---

## Estructura de archivos a crear

```
migration_engine/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── migration_job.py
│   ├── migration_rule.py
│   ├── migration_field_map.py
│   ├── migration_log.py
│   └── migration_execution.py
├── wizards/
│   ├── __init__.py
│   └── run_migration_wizard.py
├── views/
│   ├── migration_job_views.xml
│   ├── migration_rule_views.xml
│   ├── migration_log_views.xml
│   └── menus.xml
├── security/
│   ├── migration_security.xml
│   └── ir.model.access.csv
└── data/
    └── migration_data.xml   (secuencia, categoría de menú)
```

---

## `__manifest__.py`

```python
{
    'name': 'Migration Engine',
    'version': '17.0.1.0.0',
    'summary': 'Motor ETL configurable con transformación por capas y log transaccional',
    'category': 'Technical',
    'author': 'AlejtoDev',
    'depends': ['base'],
    'data': [
        'security/migration_security.xml',
        'security/ir.model.access.csv',
        'data/migration_data.xml',
        'views/migration_log_views.xml',
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

Campos:

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre del trabajo |
| `source_model_id` | Many2one → `ir.model` | Modelo origen |
| `dest_model_id` | Many2one → `ir.model` | Modelo destino |
| `domain` | Char | Dominio de filtro sobre el modelo origen (default `[]`) |
| `field_map_ids` | One2many → `migration.field.map` | Mapeos de campo |
| `rule_ids` | One2many → `migration.rule` | Reglas de transformación |
| `log_ids` | One2many → `migration.log` | Logs del trabajo |
| `state` | Selection | `draft`, `running`, `done`, `partial`, `error` |
| `last_run` | Datetime | Última ejecución |
| `record_count` | Integer | Total de registros procesados (compute) |
| `error_count` | Integer | Total de errores (compute) |
| `warning_count` | Integer | Total de warnings (compute) |
| `notes` | Text | Notas internas |

Métodos:
- `action_run()`: Abre el wizard `run.migration.wizard`
- `action_dry_run()`: Llama a `migration.execution` con `dry_run=True`
- `action_view_logs()`: Acción smart button hacia los logs del trabajo
- `_compute_counts()`: Cuenta log_ids agrupando por `log_type`

---

## Modelo: `migration.field.map` (`models/migration_field_map.py`)

Mapeo campo a campo entre modelo origen y modelo destino.

Campos:

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre |
| `source_field_id` | Many2one → `ir.model.fields` | Campo del modelo origen |
| `dest_field_id` | Many2one → `ir.model.fields` | Campo del modelo destino |
| `transform_type` | Selection | `direct`, `fixed_value`, `python_expr`, `lookup` |
| `fixed_value` | Char | Valor fijo (si `transform_type == 'fixed_value'`) |
| `python_expr` | Text | Expresión Python evaluada con `value` como variable (si `transform_type == 'python_expr'`) |
| `lookup_model_id` | Many2one → `ir.model` | Modelo de lookup (si `transform_type == 'lookup'`) |
| `lookup_source_field_id` | Many2one → `ir.model.fields` | Campo de búsqueda en el modelo de lookup |
| `lookup_dest_field_id` | Many2one → `ir.model.fields` | Campo a retornar del modelo de lookup |
| `required` | Boolean | Si falla el mapeo, ¿es error fatal para el registro? |
| `sequence` | Integer | Orden de evaluación |

Restricciones: El `source_field_id` debe pertenecer al `source_model_id` del job. El `dest_field_id` debe pertenecer al `dest_model_id` del job. Agregar `@api.constrains` para esto.

---

## Modelo: `migration.rule` (`models/migration_rule.py`)

Reglas de validación y limpieza PRE-transformación.

Campos:

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre |
| `name` | Char | Nombre descriptivo de la regla |
| `field_id` | Many2one → `ir.model.fields` | Campo a validar (del modelo origen) |
| `rule_type` | Selection | `not_null`, `type_check`, `format_regex`, `python_expr` |
| `python_expr` | Text | Expresión Python con variable `value` y `record` |
| `regex_pattern` | Char | Patrón regex (si `rule_type == 'format_regex'`) |
| `on_failure` | Selection | `warning` (loguea y continúa) / `error` (rollback del registro) |
| `sequence` | Integer | Orden de evaluación |
| `active` | Boolean | Default True |

---

## Modelo: `migration.log` (`models/migration_log.py`)

Un registro de log por cada registro procesado (o por evento del job).

Campos:

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre |
| `execution_date` | Datetime | Fecha/hora del evento |
| `log_type` | Selection | `info`, `warning`, `error` |
| `source_record_id_int` | Integer | ID del registro origen |
| `source_model` | Char | Nombre técnico del modelo origen |
| `field_name` | Char | Campo involucrado (si aplica) |
| `message` | Text | Mensaje descriptivo del evento |
| `traceback` | Text | Traceback completo (si es error) |
| `was_rollback` | Boolean | Si el registro fue revertido por savepoint |

---

## Modelo: `migration.execution` (`models/migration_execution.py`)

Este es el corazón del módulo. Implementa la ejecución transaccional.

```python
class MigrationExecution(models.AbstractModel):
    _name = 'migration.execution'
    _description = 'Motor de ejecución ETL con savepoints'

    def run(self, job, dry_run=False):
        """
        Ejecuta la migración del job.

        Flujo por registro:
        1. Limpieza y normalización (migration.rule)
           - Evalúa cada regla activa sobre el registro origen
           - Si on_failure='warning': loguea warning, continúa
           - Si on_failure='error': loguea error, salta el registro (no hace SAVEPOINT aún)
        2. Mapeo dinámico (migration.field.map)
           - Aplica las transformaciones en orden de secuencia
           - Construye el dict de valores para el modelo destino
        3. Ejecución transaccional
           - SAVEPOINT sp_{job.id}_{record.id}
           - DestModel.create(vals) o write(vals) según configuración
           - RELEASE SAVEPOINT si OK
           - ROLLBACK TO SAVEPOINT + log error si falla
        4. Log de resultado (migration.log)
           - info: procesado OK
           - warning: procesado con advertencias
           - error: revertido por savepoint

        Si dry_run=True: ejecuta todo incluyendo el create/write dentro de
        un savepoint global que se hace ROLLBACK al final. Los logs se
        crean con prefix '[DRY RUN]' y se borran al terminar el dry run
        (o se mantienen con un campo booleano `dry_run` en migration.log).
        """
        pass
```

### Implementación del método `run`:

```python
def run(self, job, dry_run=False):
    SourceModel = self.env[job.source_model_id.model]
    DestModel = self.env[job.dest_model_id.model]

    domain = safe_eval(job.domain or '[]')
    records = SourceModel.search(domain)

    job.write({'state': 'running', 'last_run': fields.Datetime.now()})
    # Limpiar logs anteriores del job (o acumular, según preferencia)
    # job.log_ids.unlink()  <- decisión de diseño: limpiar o acumular

    has_errors = False

    for record in records:
        sp_name = f'migration_sp_{job.id}_{record.id}'

        # --- FASE 1: Validación / Limpieza ---
        validation_passed = True
        for rule in job.rule_ids.filtered('active').sorted('sequence'):
            try:
                field_value = record[rule.field_id.name]
                rule_passed = self._evaluate_rule(rule, field_value, record)
                if not rule_passed:
                    self._create_log(job, record, 'warning' if rule.on_failure == 'warning' else 'error',
                                     f"Regla '{rule.name}' falló en campo '{rule.field_id.name}'",
                                     dry_run=dry_run)
                    if rule.on_failure == 'error':
                        validation_passed = False
                        has_errors = True
                        break
            except Exception as e:
                self._create_log(job, record, 'error',
                                 f"Error evaluando regla '{rule.name}': {str(e)}",
                                 traceback=traceback.format_exc(), dry_run=dry_run)
                validation_passed = False
                has_errors = True
                break

        if not validation_passed:
            continue

        # --- FASE 2: Mapeo dinámico ---
        try:
            vals = self._apply_field_maps(job, record)
        except Exception as e:
            self._create_log(job, record, 'error',
                             f"Error en mapeo de campos: {str(e)}",
                             traceback=traceback.format_exc(), dry_run=dry_run)
            has_errors = True
            continue

        # --- FASE 3: Ejecución transaccional ---
        if dry_run:
            self._create_log(job, record, 'info',
                             f"[DRY RUN] Registro procesable. Vals: {vals}", dry_run=True)
            continue

        self.env.cr.execute(f'SAVEPOINT {sp_name}')
        try:
            DestModel.create(vals)
            self.env.cr.execute(f'RELEASE SAVEPOINT {sp_name}')
            self._create_log(job, record, 'info', 'Registro migrado correctamente')
        except Exception as e:
            self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp_name}')
            self._create_log(job, record, 'error',
                             f"Error en create/write: {str(e)}",
                             traceback=traceback.format_exc(),
                             was_rollback=True)
            has_errors = True

    # Actualizar estado del job
    if not dry_run:
        job.state = 'partial' if has_errors else 'done'
```

### Método `_evaluate_rule`:

```python
def _evaluate_rule(self, rule, value, record):
    if rule.rule_type == 'not_null':
        return bool(value)
    elif rule.rule_type == 'type_check':
        # Verificar tipo del campo vs tipo esperado
        return value is not None
    elif rule.rule_type == 'format_regex':
        import re
        return bool(re.match(rule.regex_pattern, str(value or '')))
    elif rule.rule_type == 'python_expr':
        local_dict = {'value': value, 'record': record, 'env': self.env}
        return bool(safe_eval(rule.python_expr, local_dict))
    return True
```

### Método `_apply_field_maps`:

```python
def _apply_field_maps(self, job, record):
    vals = {}
    for fmap in job.field_map_ids.sorted('sequence'):
        source_val = record[fmap.source_field_id.name]
        dest_field = fmap.dest_field_id.name

        try:
            if fmap.transform_type == 'direct':
                vals[dest_field] = source_val
            elif fmap.transform_type == 'fixed_value':
                vals[dest_field] = fmap.fixed_value
            elif fmap.transform_type == 'python_expr':
                local_dict = {'value': source_val, 'record': record, 'env': self.env}
                vals[dest_field] = safe_eval(fmap.python_expr, local_dict)
            elif fmap.transform_type == 'lookup':
                LookupModel = self.env[fmap.lookup_model_id.model]
                lookup_rec = LookupModel.search(
                    [(fmap.lookup_source_field_id.name, '=', source_val)], limit=1
                )
                vals[dest_field] = lookup_rec[fmap.lookup_dest_field_id.name] if lookup_rec else False
        except Exception as e:
            if fmap.required:
                raise
            # Si no es required, continúa sin ese campo
    return vals
```

### Método `_create_log`:

```python
def _create_log(self, job, record, log_type, message,
                traceback=None, was_rollback=False, dry_run=False):
    self.env['migration.log'].create({
        'job_id': job.id,
        'execution_date': fields.Datetime.now(),
        'log_type': log_type,
        'source_record_id_int': record.id,
        'source_model': record._name,
        'message': ('[DRY RUN] ' if dry_run else '') + message,
        'traceback': traceback,
        'was_rollback': was_rollback,
    })
```

---

## Wizard: `run.migration.wizard` (`wizards/run_migration_wizard.py`)

```python
class RunMigrationWizard(models.TransientModel):
    _name = 'run.migration.wizard'
    _description = 'Wizard de ejecución de migración'

    job_id = fields.Many2one('migration.job', required=True)
    dry_run = fields.Boolean(
        string='Dry Run (simulación)',
        help='Ejecuta la migración completa pero hace rollback al final. '
             'Los logs muestran qué habría ocurrido.'
    )
    confirm = fields.Boolean(
        string='Confirmo que deseo ejecutar esta migración'
    )

    def action_execute(self):
        self.ensure_one()
        if not self.dry_run and not self.confirm:
            raise UserError('Debes confirmar la ejecución antes de proceder.')
        self.env['migration.execution'].run(self.job_id, dry_run=self.dry_run)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Logs de Migración',
            'res_model': 'migration.log',
            'view_mode': 'tree,form',
            'domain': [('job_id', '=', self.job_id.id)],
        }
```

---

## Vistas

### `migration_job_views.xml`

Crear los siguientes elementos:

1. **Form view de `migration.job`** con:
   - Header con botones de estado (`action_run`, `action_dry_run`) y statusbar (`draft → running → done/partial/error`)
   - Smart buttons: total de logs, errores, warnings (con colores: rojo para errores, amarillo para warnings)
   - Campos generales en group: name, source_model_id, dest_model_id, domain, last_run, notes
   - Notebook con pestañas:
     - **Mapeo de campos**: tree editable de `field_map_ids`
     - **Reglas de validación**: tree editable de `rule_ids`
     - **Logs**: tree de `log_ids` (readonly, filtrado por el job)

2. **Tree view** de `migration.job` con columnas: name, source_model_id, dest_model_id, state, last_run, record_count, error_count

3. **Search view** con filtros: Por estado, con errores, sin errores; group by: estado, modelo origen

### `migration_rule_views.xml`

1. **Form view** de `migration.rule` como popup (target new) con todos los campos
2. **Tree view** editable inline para usar dentro del job form

### `migration_log_views.xml`

1. **Tree view** de `migration.log` con columnas: execution_date, log_type (con decoration-danger/warning/success según tipo), source_model, source_record_id_int, field_name, message, was_rollback
   - Decorations: `decoration-danger="log_type == 'error'"`, `decoration-warning="log_type == 'warning'"`

2. **Form view** de `migration.log` con traceback visible en `<pre>` dentro de un campo text

3. **Search view** con:
   - Filtros rápidos: Solo errores, Solo warnings, Con rollback, Dry run
   - Group by: log_type, job_id, source_model, fecha

### `menus.xml`

```xml
<!-- Menú raíz -->
<menuitem id="menu_migration_root" name="Migration Engine" sequence="80"/>

<!-- Submenús -->
<menuitem id="menu_migration_jobs" name="Trabajos" parent="menu_migration_root" action="action_migration_job"/>
<menuitem id="menu_migration_logs" name="Logs" parent="menu_migration_root" action="action_migration_log_all"/>
```

---

## Seguridad

### Grupos (`security/migration_security.xml`):

```xml
<record id="group_migration_user" model="res.groups">
    <field name="name">Migration Engine / User</field>
</record>
<record id="group_migration_manager" model="res.groups">
    <field name="name">Migration Engine / Manager</field>
    <field name="implied_ids" eval="[(4, ref('group_migration_user'))]"/>
</record>
```

### `ir.model.access.csv`:

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_migration_job_manager,migration.job manager,model_migration_job,group_migration_manager,1,1,1,1
access_migration_job_user,migration.job user,model_migration_job,group_migration_user,1,0,0,0
access_migration_field_map_manager,migration.field.map manager,model_migration_field_map,group_migration_manager,1,1,1,1
access_migration_rule_manager,migration.rule manager,model_migration_rule,group_migration_manager,1,1,1,1
access_migration_log_manager,migration.log manager,model_migration_log,group_migration_manager,1,1,1,1
access_migration_log_user,migration.log user,model_migration_log,group_migration_user,1,0,0,0
access_run_migration_wizard_manager,run.migration.wizard manager,model_run_migration_wizard,group_migration_manager,1,1,1,1
```

---

## Consideraciones técnicas importantes

1. **`safe_eval`**: Usar siempre `from odoo.tools.safe_eval import safe_eval` para evaluar expresiones Python de usuario. Nunca `eval()` directo.

2. **Savepoints y el cursor de Odoo**: Los savepoints SQL (`SAVEPOINT`, `RELEASE`, `ROLLBACK TO`) se ejecutan con `self.env.cr.execute(...)`. Son compatibles con el sistema de ORM de Odoo en Odoo 17 porque operan a nivel del cursor PostgreSQL actual. Importante: después de un `ROLLBACK TO SAVEPOINT`, el environment de Odoo puede tener el cache sucio — hacer `self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp_name}')` y luego limpiar el cache con `self.env.invalidate_all()` si es necesario.

3. **`domain` field**: Almacenar el domain como string. Validar con `safe_eval` al leer. Considerar usar un widget `domain` en la vista form para que el usuario construya el domain visualmente.

4. **Filtro de `source_field_id`** en `migration.field.map`: En la vista form, el campo `source_field_id` debe estar filtrado por `model_id = source_model_id del job`. Usar `domain="[('model_id', '=', parent.source_model_id)]"` en la vista XML.

5. **Manejo de Many2one en mapeo**: Cuando un campo destino es Many2one, el valor en `vals` debe ser el ID entero. El `_apply_field_maps` debe detectar el tipo del campo destino y convertir adecuadamente.

6. **Compatibilidad Odoo 17**: 
   - Usar `fields.Html` con `sanitize=False` solo si es necesario
   - El `__manifest__.py` debe tener `'license': 'OPL-1'`
   - Asegurarse que el `AbstractModel` `migration.execution` tenga `_auto = False` para evitar que Odoo intente crear una tabla para él

---

## Flujo de usuario esperado

1. Ir a **Migration Engine > Trabajos**
2. Crear nuevo trabajo: seleccionar modelo origen y destino
3. Definir domain de filtro (qué registros migrar)
4. En pestaña **Mapeo de campos**: agregar las correspondencias campo → campo con el tipo de transformación
5. En pestaña **Reglas de validación**: agregar validaciones previas a la transformación
6. Botón **Dry Run**: ejecutar en modo simulación para revisar qué pasaría
7. Revisar la pestaña **Logs** o ir a **Migration Engine > Logs** para ver el resultado del dry run
8. Si todo está correcto, botón **Ejecutar migración** (con checkbox de confirmación en el wizard)
9. Revisar logs finales: filtrar por errores, ver traceback de los registros fallidos

---

## Mejoras opcionales (fase 2, no en este sprint)

- Campo `mode` en el job: `create_only`, `update_only`, `create_or_update` (busca registro existente antes de crear)
- Campo `key_field_ids`: campos que identifican unicidad para el modo `create_or_update`
- Scheduler automático: `ir.cron` configurable por job
- Export de logs a Excel/CSV desde la vista de logs
- Estadísticas por job: gráfico de progreso, tasa de éxito
- Versionado de configuración del job (guardar snapshots de field_maps y rules)
