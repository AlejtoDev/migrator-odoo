# Prompt — Claude Code: módulo `migration_engine` para Odoo 17.0
# Versión 3 — Community/Enterprise, Instance Snapshot, vista previa en wizard

---

## Contexto general

Construye un módulo Odoo 17.0 llamado `migration_engine`. El módulo tiene **dos bloques
funcionales independientes** pero conviven en el mismo menú raíz:

**Bloque A — Motor ETL**: Migra registros entre modelos dentro de la misma instancia,
aplicando reglas de transformación campo a campo, con ejecución transaccional por savepoints
y log acumulado por ejecución.

**Bloque B — Instance Snapshot**: Inventario técnico de la instancia. Registra qué módulos
custom/OCA están instalados y su estado, y detecta qué modelos tienen campos `x_studio_*`
(personalizaciones de Odoo Studio), generando fichas legibles para informar al cliente qué
hace cada campo y qué impacto tiene en una migración.

El módulo debe funcionar en **Odoo 17.0 Community y Enterprise**. Cualquier funcionalidad
que dependa de Enterprise (por ejemplo, el widget `studio` o vistas `cohort`) debe detectarse
en runtime y degradarse silenciosamente en Community, nunca romper la instalación.

---

## Estructura de archivos

```
migration_engine/
├── __init__.py
├── __manifest__.py
│
├── models/
│   ├── __init__.py
│   │
│   │   ── Bloque A: ETL ──
│   ├── migration_job.py
│   ├── migration_execution_run.py
│   ├── migration_rule.py
│   ├── migration_field_map.py
│   ├── migration_log.py
│   └── migration_execution.py          # AbstractModel, motor ETL
│   │
│   │   ── Bloque B: Snapshot ──
│   ├── instance_module_status.py       # módulos instalados
│   └── instance_studio_field.py        # campos x_studio_*
│
├── wizards/
│   ├── __init__.py
│   ├── run_migration_wizard.py         # wizard ETL con preview
│   └── snapshot_refresh_wizard.py      # reescanear la instancia
│
├── views/
│   ├── migration_job_views.xml
│   ├── migration_execution_run_views.xml
│   ├── migration_rule_views.xml
│   ├── migration_log_views.xml
│   ├── instance_module_status_views.xml
│   ├── instance_studio_field_views.xml
│   └── menus.xml
│
├── security/
│   ├── migration_security.xml
│   └── ir.model.access.csv
│
└── data/
    └── migration_data.xml
```

---

## `__manifest__.py`

```python
{
    'name': 'Migration Engine',
    'version': '17.0.1.0.0',
    'summary': 'Motor ETL + inventario técnico de instancia para proyectos de migración',
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
        'views/instance_module_status_views.xml',
        'views/instance_studio_field_views.xml',
        'views/menus.xml',
    ],
    'license': 'OPL-1',
    'installable': True,
    'application': True,
}
```

### Detección Community vs Enterprise en runtime

En cualquier modelo o método que necesite saber si corre en Enterprise:

```python
def _is_enterprise(self):
    return self.env['ir.module.module'].sudo().search_count([
        ('name', '=', 'web_enterprise'),
        ('state', '=', 'installed'),
    ]) > 0
```

Usar este helper antes de referenciar cualquier vista, widget o modelo exclusivo de Enterprise.
Nunca usar `try/except ImportError` sobre módulos Enterprise — en 17.0 todo está en el mismo
árbol y el import puede silenciosamente pasar aunque el módulo no esté activo.

---

## ══════════════════════════════════════
## BLOQUE A — MOTOR ETL
## ══════════════════════════════════════

---

## Modelo: `migration.job` (`models/migration_job.py`)

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre del trabajo, required |
| `source_model_id` | Many2one → `ir.model` | Modelo origen |
| `dest_model_id` | Many2one → `ir.model` | Modelo destino |
| `domain` | Char | Dominio de filtro. Default `'[]'` |
| `mode` | Selection | `create_only`, `update_only`, `create_or_update`. Default `create_only` |
| `key_field_ids` | Many2many → `ir.model.fields` | Campos clave para `update_only`/`create_or_update` |
| `field_map_ids` | One2many → `migration.field.map` | Mapeos de campo |
| `rule_ids` | One2many → `migration.rule` | Reglas de validación |
| `execution_run_ids` | One2many → `migration.execution.run` | Historial de ejecuciones |
| `state` | Selection | `draft`, `running`, `done`, `partial`, `error`. Default `draft` |
| `last_run` | Datetime | Compute: fecha del último `execution_run_id` por fecha desc |
| `total_runs` | Integer | Compute: count de `execution_run_ids` |
| `notes` | Text | Notas internas |

### Métodos

- `action_run()`: Abre el wizard `run.migration.wizard` con `job_id = self.id`
- `action_view_runs()`: Smart button → lista de `migration.execution.run` filtrada por job
- `_compute_last_run()`: `max(execution_run_ids.mapped('execution_date'))` o False
- `_compute_total_runs()`: `len(execution_run_ids)`

### `key_field_ids` — Many2many explícito

```python
key_field_ids = fields.Many2many(
    'ir.model.fields',
    'migration_job_key_fields_rel',
    'job_id',
    'field_id',
    string='Campos clave',
    domain="[('model_id', '=', source_model_id)]",
    help='Campos del modelo ORIGEN usados para buscar el registro en el modelo DESTINO '
         'en los modos update_only y create_or_update.',
)
```

---

## Modelo: `migration.execution.run` (`models/migration_execution_run.py`)

Agrupa todos los logs de una ejecución única. Permite historial acumulado sin mezclar corridas.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Auto: `"Ejecución #N — {job.name}"` con `ir.sequence` |
| `job_id` | Many2one → `migration.job` | Trabajo padre, required |
| `execution_date` | Datetime | Inicio. Default `fields.Datetime.now()` |
| `end_date` | Datetime | Fin |
| `dry_run` | Boolean | Si fue simulación |
| `state` | Selection | `running`, `done`, `partial`, `error` |
| `log_ids` | One2many → `migration.log` | Logs de esta ejecución |
| `total_records` | Integer | Compute: count de log_ids |
| `success_count` | Integer | Compute: count donde `log_type == 'info'` |
| `warning_count` | Integer | Compute: count donde `log_type == 'warning'` |
| `error_count` | Integer | Compute: count donde `log_type == 'error'` |
| `duration_seconds` | Float | Compute: `(end_date - execution_date).total_seconds()` |

### Métodos

- `_compute_counts()`: Agrupa `log_ids` por `log_type` y cuenta cada bucket
- `_compute_duration()`: diferencia entre `end_date` y `execution_date` en segundos
- `action_export_logs_csv()`: exporta logs de esta ejecución a CSV descargable

### Export CSV

```python
def action_export_logs_csv(self):
    import csv, io, base64
    self.ensure_one()
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow([
        'Fecha', 'Tipo', 'Dry Run', 'Modelo Origen', 'ID Origen',
        'Campo', 'Regla', 'Mensaje', 'Rollback', 'Traceback',
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
    fname = (
        f'migration_logs_{self.job_id.name}_'
        f'{self.execution_date.strftime("%Y%m%d_%H%M%S")}.csv'
    )
    att = self.env['ir.attachment'].create({
        'name': fname,
        'type': 'binary',
        'datas': base64.b64encode(csv_content.encode('utf-8')),
        'mimetype': 'text/csv',
        'res_model': self._name,
        'res_id': self.id,
    })
    return {
        'type': 'ir.actions.act_url',
        'url': f'/web/content/{att.id}?download=true',
        'target': 'self',
    }
```

---

## Modelo: `migration.field.map` (`models/migration_field_map.py`)

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre, required |
| `sequence` | Integer | Orden, default 10 |
| `source_field_id` | Many2one → `ir.model.fields` | Campo origen |
| `dest_field_id` | Many2one → `ir.model.fields` | Campo destino |
| `transform_type` | Selection | `direct`, `fixed_value`, `python_expr`, `lookup` |
| `fixed_value` | Char | Valor fijo cuando `transform_type == 'fixed_value'` |
| `python_expr` | Text | Expresión `safe_eval`. Variables: `value`, `record`, `env` |
| `lookup_model_id` | Many2one → `ir.model` | Modelo lookup |
| `lookup_source_field_id` | Many2one → `ir.model.fields` | Campo de búsqueda en lookup |
| `lookup_dest_field_id` | Many2one → `ir.model.fields` | Campo a retornar del lookup |
| `required` | Boolean | Si falla: rollback del registro (True) o continúa sin el campo (False) |

### `@api.constrains`

- `source_field_id.model_id` == `job_id.source_model_id`
- `dest_field_id.model_id` == `job_id.dest_model_id`
- Si `transform_type == 'lookup'`: ambos `lookup_*_field_id` pertenecen a `lookup_model_id`

---

## Modelo: `migration.rule` (`models/migration_rule.py`)

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `job_id` | Many2one → `migration.job` | Trabajo padre, required |
| `sequence` | Integer | Orden, default 10 |
| `name` | Char | Nombre descriptivo, required |
| `field_id` | Many2one → `ir.model.fields` | Campo a validar (modelo origen) |
| `rule_type` | Selection | `not_null`, `type_check`, `format_regex`, `python_expr` |
| `python_expr` | Text | `safe_eval`. Variables: `value`, `record`, `env` |
| `regex_pattern` | Char | Patrón regex para `format_regex` |
| `on_failure` | Selection | `warning` (continúa) / `error` (salta el registro) |
| `active` | Boolean | Default True |

---

## Modelo: `migration.log` (`models/migration_log.py`)

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `execution_run_id` | Many2one → `migration.execution.run` | Ejecución padre, required |
| `job_id` | Many2one → `migration.job` | Related store=True para filtros rápidos |
| `execution_date` | Datetime | Fecha/hora del evento |
| `log_type` | Selection | `info`, `warning`, `error` |
| `source_record_id_int` | Integer | ID del registro origen |
| `source_model` | Char | Nombre técnico del modelo origen |
| `field_name` | Char | Campo involucrado (si aplica) |
| `rule_name` | Char | Nombre de la regla que falló (si aplica) |
| `message` | Text | Mensaje descriptivo |
| `traceback` | Text | Traceback completo (si es excepción) |
| `was_rollback` | Boolean | Si fue revertido por savepoint |
| `dry_run` | Boolean | Si pertenece a simulación |

---

## Modelo: `migration.execution` (`models/migration_execution.py`)

AbstractModel sin tabla. Corazón del ETL.

```python
from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval
import traceback as tb
import logging

_logger = logging.getLogger(__name__)


class MigrationExecution(models.AbstractModel):
    _name = 'migration.execution'
    _description = 'Motor ETL con savepoints'
    _auto = False
```

### `run(self, job, dry_run=False)` — flujo completo

```python
def run(self, job, dry_run=False):
    # Crear el execution run
    run_vals = {
        'job_id': job.id,
        'dry_run': dry_run,
        'state': 'running',
        'execution_date': fields.Datetime.now(),
    }
    if not dry_run:
        run = self.env['migration.execution.run'].create(run_vals)

    job.write({'state': 'running'})

    SourceModel = self.env[job.source_model_id.model]
    domain = safe_eval(job.domain or '[]')
    records = SourceModel.search(domain)

    # Para dry_run: acumular resultados en memoria, crear run y logs DESPUÉS del rollback
    pending_entries = []   # lista de (result_str, [log_vals_dicts])
    has_errors = has_warnings = False

    global_sp = f'migration_dry_{job.id}_{fields.Datetime.now().strftime("%H%M%S%f")}'
    if dry_run:
        self.env.cr.execute(f'SAVEPOINT {global_sp}')

    for record in records:
        result, log_list = self._process_record(job, record, dry_run)
        if dry_run:
            pending_entries.append((result, log_list))
        else:
            # Los logs ya fueron escritos dentro de _process_record
            pass
        if result == 'error':
            has_errors = True
        elif result == 'warning':
            has_warnings = True

    # Rollback global del dry_run y persistir logs en cursor limpio
    if dry_run:
        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {global_sp}')
        self.env.invalidate_all()
        # Crear el run (fue revertido con el rollback global)
        run = self.env['migration.execution.run'].create(run_vals)
        for result, log_list in pending_entries:
            for log_vals in log_list:
                self.env['migration.log'].create({
                    'execution_run_id': run.id,
                    'job_id': job.id,
                    'dry_run': True,
                    **log_vals,
                })

    final_state = (
        'error'   if has_errors and not has_warnings else
        'partial' if has_errors else
        'done'
    )
    run.write({'state': final_state, 'end_date': fields.Datetime.now()})
    job.write({'state': final_state})
    return run
```

### `_process_record(self, job, record, dry_run)` → `(result_str, [log_vals])`

```python
def _process_record(self, job, record, dry_run):
    """
    Retorna (result, log_list).
    - result: 'ok' | 'warning' | 'error'
    - log_list: lista de dicts de log (SIN execution_run_id ni job_id,
      se agregan en run() para ambos modos).
    En modo no-dry_run los logs se escriben aquí mismo; en dry_run se
    devuelven para que run() los persista después del ROLLBACK global.
    """
    collected_logs = []

    # FASE 1: Validación
    validation_result, validation_logs = self._validate_record(job, record)
    collected_logs.extend(validation_logs)
    if validation_result == 'fatal':
        if not dry_run:
            self._flush_logs(job, collected_logs)
        return 'error', collected_logs

    # FASE 2: Mapeo dinámico
    try:
        vals = self._apply_field_maps(job, record)
    except Exception as e:
        collected_logs.append({
            'log_type': 'error',
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': f'Error en mapeo de campos: {e}',
            'traceback': tb.format_exc(),
            'execution_date': fields.Datetime.now(),
        })
        if not dry_run:
            self._flush_logs(job, collected_logs)
        return 'error', collected_logs

    # FASE 3: Resolución de registro destino (update_only / create_or_update)
    dest_record = None
    if job.mode in ('update_only', 'create_or_update'):
        dest_record = self._resolve_dest_record(job, record, vals)
        if not dest_record and job.mode == 'update_only':
            collected_logs.append({
                'log_type': 'warning',
                'source_record_id_int': record.id,
                'source_model': record._name,
                'message': 'Modo update_only: no se encontró registro destino. Omitido.',
                'execution_date': fields.Datetime.now(),
            })
            if not dry_run:
                self._flush_logs(job, collected_logs)
            return 'warning', collected_logs

    # FASE 4: Dry run — solo registrar intención
    if dry_run:
        action = 'UPDATE' if dest_record else 'CREATE'
        collected_logs.append({
            'log_type': 'info' if not validation_logs else 'warning',
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': f'[DRY RUN] {action} procesable. Vals: {vals}',
            'execution_date': fields.Datetime.now(),
        })
        result = 'warning' if validation_logs else 'ok'
        return result, collected_logs

    # FASE 5: Ejecución transaccional con savepoint
    DestModel = self.env[job.dest_model_id.model]
    sp = f'migration_sp_{record.id}_{fields.Datetime.now().strftime("%f")}'
    self.env.cr.execute(f'SAVEPOINT {sp}')
    try:
        if dest_record:
            dest_record.write(vals)
        else:
            DestModel.create(vals)
        self.env.cr.execute(f'RELEASE SAVEPOINT {sp}')
        log_type = 'warning' if validation_logs else 'info'
        collected_logs.append({
            'log_type': log_type,
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': 'Registro migrado correctamente'
                + (f' (con {len(validation_logs)} warning(s))' if validation_logs else ''),
            'execution_date': fields.Datetime.now(),
        })
        self._flush_logs(job, collected_logs)
        return 'warning' if validation_logs else 'ok', collected_logs

    except Exception as e:
        self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp}')
        self.env.invalidate_all()
        collected_logs.append({
            'log_type': 'error',
            'source_record_id_int': record.id,
            'source_model': record._name,
            'message': f'Error en create/write: {e}',
            'traceback': tb.format_exc(),
            'was_rollback': True,
            'execution_date': fields.Datetime.now(),
        })
        self._flush_logs(job, collected_logs)
        return 'error', collected_logs
```

### `_flush_logs(self, job, log_list)` — escribe logs al run activo

```python
def _flush_logs(self, job, log_list):
    """Solo se llama en modo no-dry_run. Obtiene el run activo del job."""
    active_run = job.execution_run_ids.filtered(
        lambda r: r.state == 'running'
    )[:1]
    if not active_run:
        return
    for log_vals in log_list:
        self.env['migration.log'].create({
            'execution_run_id': active_run.id,
            'job_id': job.id,
            'dry_run': False,
            **log_vals,
        })
```

### `_validate_record`, `_evaluate_rule`, `_apply_field_maps`, `_resolve_dest_record`

Estos métodos son idénticos a la versión v2. Copiarlos sin cambios:

- `_validate_record(self, job, record)` → `('ok'|'fatal', [log_vals])`
  Evalúa `job.rule_ids.filtered('active').sorted('sequence')`.
  Si `on_failure == 'error'` en una regla que falla → retorna `'fatal'` y detiene la iteración.

- `_evaluate_rule(self, rule, value, record)` → `bool`
  Maneja `not_null`, `type_check`, `format_regex` (con `re.match`), `python_expr` (con `safe_eval`).

- `_apply_field_maps(self, job, record)` → `dict`
  Itera `job.field_map_ids.sorted('sequence')`.
  Maneja `direct`, `fixed_value`, `python_expr`, `lookup`.
  Convierte Many2one a ID entero cuando `dest_field_id.ttype == 'many2one'`.
  Si `fmap.required` y falla → `raise`. Si no → loguea warning y omite el campo.

- `_resolve_dest_record(self, job, source_record, vals)` → `browse | False`
  Usa `job.key_field_ids` para construir domain sobre el modelo destino.
  Retorna `DestModel.search(domain, limit=1)` o `False`.

---

## Wizard: `run.migration.wizard` (`wizards/run_migration_wizard.py`)

El wizard muestra un resumen previo de los datos reales que se van a procesar antes de
ejecutar. La preview lee los primeros N registros del modelo origen con el domain configurado
y muestra sus valores en una tabla HTML inline.

```python
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
    # Estadísticas
    record_total = fields.Integer(
        string='Registros a procesar',
        compute='_compute_preview',
    )
    # Vista previa como HTML (tabla con primeros 10 registros y los campos mapeados)
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

                # Leer primeros 10 registros
                sample = SourceModel.search(domain, limit=10)
                mapped_fields = job.field_map_ids.mapped('source_field_id.name')
                # Siempre incluir 'name' o 'display_name' si existe
                display_fields = list(dict.fromkeys(
                    ['id'] + ([f for f in ['name', 'display_name']
                               if f in [mf.name for mf in SourceModel._fields.values()]][:1])
                    + mapped_fields
                ))

                # Construir tabla HTML
                header_cells = ''.join(
                    f'<th style="padding:4px 8px;border:1px solid #ccc;">{f}</th>'
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
                            cells += (
                                f'<td style="padding:4px 8px;border:1px solid #ccc;">'
                                f'{val}</td>'
                            )
                        except Exception:
                            cells += '<td style="padding:4px 8px;border:1px solid #ccc;">—</td>'
                    rows += f'<tr>{cells}</tr>'

                wizard.preview_html = f"""
                    <div style="overflow-x:auto;">
                    <table style="border-collapse:collapse;font-size:12px;width:100%;">
                        <thead style="background:#f0f0f0;">
                            <tr>{header_cells}</tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                    </div>
                    <p style="color:#888;font-size:11px;">
                        Mostrando {min(10, len(sample))} de {wizard.record_total} registros.
                        Columnas: campos mapeados en este job.
                    </p>
                """
            except Exception as e:
                wizard.record_total = -1
                wizard.preview_html = (
                    f'<p style="color:red;">Error generando preview: {e}</p>'
                )

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
```

**Vista del wizard** (`views/migration_job_views.xml` — incluir al final del archivo):

```xml
<record id="view_run_migration_wizard_form" model="ir.ui.view">
    <field name="name">run.migration.wizard.form</field>
    <field name="model">run.migration.wizard</field>
    <field name="arch" type="xml">
        <form string="Ejecutar migración">
            <sheet>
                <group>
                    <group>
                        <field name="job_id" readonly="1"/>
                        <field name="record_total" readonly="1"/>
                    </group>
                    <group>
                        <field name="dry_run"/>
                        <field name="confirm"
                               attrs="{'invisible': [('dry_run', '=', True)],
                                       'required': [('dry_run', '=', False)]}"/>
                    </group>
                </group>
                <separator string="Vista previa de datos (primeros 10 registros del modelo origen)"/>
                <field name="preview_html" readonly="1" widget="html" nolabel="1"/>
            </sheet>
            <footer>
                <button name="action_execute" string="Ejecutar" type="object"
                        class="oe_highlight"/>
                <button string="Cancelar" class="btn-secondary" special="cancel"/>
            </footer>
        </form>
    </field>
</record>

<record id="action_run_migration_wizard" model="ir.actions.act_window">
    <field name="name">Ejecutar migración</field>
    <field name="res_model">run.migration.wizard</field>
    <field name="view_mode">form</field>
    <field name="target">new</field>
</record>
```

---

## ══════════════════════════════════════
## BLOQUE B — INSTANCE SNAPSHOT
## ══════════════════════════════════════

---

## Modelo: `instance.module.status` (`models/instance_module_status.py`)

Inventario de módulos instalados en la instancia. Se refresca manualmente desde un wizard.
**No** hace `ir.cron` — el usuario controla cuándo escanear.

### Categorías de módulo detectadas automáticamente

| Categoría | Criterio de detección |
|---|---|
| `odoo_official` | `author` contiene 'Odoo S.A.' o nombre empieza con `l10n_`, `account`, `sale`, `purchase`, `stock`, etc. |
| `oca` | `author` contiene 'OCA' o repositorio contiene 'OCA' |
| `custom` | No encaja en ninguna categoría anterior y `state == 'installed'` |
| `enterprise` | `name` está en la lista de módulos Enterprise conocidos (`web_enterprise`, `account_reports`, `sale_subscription`, etc.) |
| `localization` | `name` empieza con `l10n_` |

El criterio exacto no es perfecto (Odoo no expone una tabla de módulos Enterprise),
pero cubre el 95% de los casos reales.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | `ir.module.module.name`, required |
| `display_name_module` | Char | `ir.module.module.shortdesc` (nombre legible) |
| `state` | Selection | `installed`, `uninstalled`, `to upgrade`, `to remove` |
| `module_category` | Selection | `odoo_official`, `oca`, `custom`, `enterprise`, `localization`, `unknown` |
| `author` | Char | Autor del módulo |
| `version` | Char | Versión instalada |
| `last_scanned` | Datetime | Última vez que fue registrado/actualizado por el scanner |
| `is_relevant_for_migration` | Boolean | Compute: True si `module_category in ('custom', 'oca')` |
| `notes` | Text | Notas manuales del consultor sobre el módulo |
| `dependency_ids` | Many2many → `instance.module.status` | Módulos de los que depende (self-relation) |

### Método estático: `action_refresh_snapshot()` (se llama desde el wizard)

```python
@api.model
def refresh_snapshot(self):
    """
    Lee todos los módulos instalados desde ir.module.module y sincroniza
    instance.module.status. Crea registros para módulos nuevos, actualiza
    los existentes, no borra los que ya no estén (para mantener notas manuales).
    """
    installed = self.env['ir.module.module'].sudo().search([
        ('state', '=', 'installed')
    ])
    existing = {r.name: r for r in self.search([])}

    for mod in installed:
        category = self._detect_category(mod)
        vals = {
            'name': mod.name,
            'display_name_module': mod.shortdesc or mod.name,
            'state': mod.state,
            'author': mod.author or '',
            'version': mod.installed_version or '',
            'module_category': category,
            'last_scanned': fields.Datetime.now(),
        }
        if mod.name in existing:
            existing[mod.name].write(vals)
        else:
            self.create(vals)

    return True

@api.model
def _detect_category(self, mod):
    name = mod.name or ''
    author = (mod.author or '').lower()
    ENTERPRISE_MODULES = {
        'web_enterprise', 'account_reports', 'account_accountant',
        'sale_subscription', 'sale_renting', 'sign', 'documents',
        'quality_control', 'maintenance', 'helpdesk', 'studio',
        'social', 'marketing_automation', 'voip', 'whatsapp',
        # Agregar más según necesidad
    }
    if name in ENTERPRISE_MODULES:
        return 'enterprise'
    if name.startswith('l10n_'):
        return 'localization'
    if 'oca' in author or 'odoo community association' in author:
        return 'oca'
    if 'odoo s.a.' in author or 'odoo sa' in author:
        return 'odoo_official'
    # Heurística: si el nombre no empieza con ningún prefijo estándar, es custom
    OFFICIAL_PREFIXES = (
        'account', 'sale', 'purchase', 'stock', 'mrp', 'project',
        'hr', 'mail', 'web', 'base', 'bus', 'auth', 'calendar',
        'crm', 'lunch', 'fleet', 'point_of_sale', 'website',
        'payment', 'delivery', 'repair', 'survey',
    )
    if any(name.startswith(p) for p in OFFICIAL_PREFIXES):
        return 'odoo_official'
    return 'custom'
```

---

## Modelo: `instance.studio.field` (`models/instance_studio_field.py`)

Inventario de todos los campos `x_studio_*` existentes en la instancia, con ficha
descriptiva para el cliente.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre técnico del campo (ej. `x_studio_cliente_vip`) |
| `field_description` | Char | Descripción/label del campo en Odoo (`ir.model.fields.field_description`) |
| `model_id` | Many2one → `ir.model` | Modelo al que pertenece |
| `model_name` | Char | Nombre técnico del modelo (related, store=True) |
| `field_type` | Char | Tipo de campo (`ttype` de `ir.model.fields`) |
| `last_scanned` | Datetime | Última vez detectado |
| `migration_impact` | Selection | `none`, `low`, `medium`, `high`. Editable manualmente |
| `client_description` | Text | Descripción legible para el cliente: qué hace este campo, por qué existe |
| `migration_notes` | Text | Notas técnicas del consultor: cómo manejar este campo en la migración |
| `sample_values` | Text | Muestra de hasta 5 valores distintos no nulos del campo (compute, store=False) |

### Método: `refresh_studio_fields()`

```python
@api.model
def refresh_studio_fields(self):
    """
    Busca todos los campos en ir.model.fields cuyo nombre empieza con 'x_studio_'
    y sincroniza instance.studio.field.
    """
    studio_fields = self.env['ir.model.fields'].sudo().search([
        ('name', 'like', 'x_studio_'),
        ('state', '=', 'manual'),  # campos manuales/studio
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
            'model_name': sf.model_id.model,
            'field_type': sf.ttype,
            'last_scanned': fields.Datetime.now(),
        }
        if key in existing:
            existing[key].write(vals)
        else:
            self.create(vals)
    return True

def _compute_sample_values(self):
    """
    Lee hasta 5 valores distintos no nulos del campo en el modelo real.
    Solo se ejecuta cuando el usuario lo solicita explícitamente (botón).
    """
    for record in self:
        try:
            Model = self.env[record.model_name].sudo()
            results = Model.search(
                [(record.name, 'not in', [False, ''])], limit=20
            ).mapped(record.name)
            # Deduplicate y truncar
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
    """Botón en form view para cargar muestra de valores bajo demanda."""
    self._compute_sample_values()
```

---

## Wizard: `snapshot.refresh.wizard` (`wizards/snapshot_refresh_wizard.py`)

```python
from odoo import models, fields, api


class SnapshotRefreshWizard(models.TransientModel):
    _name = 'snapshot.refresh.wizard'
    _description = 'Asistente de reescaneo de instancia'

    refresh_modules = fields.Boolean(
        string='Refrescar módulos instalados', default=True
    )
    refresh_studio_fields = fields.Boolean(
        string='Refrescar campos Studio (x_studio_*)', default=True
    )
    # Estadísticas post-escaneo (readonly, se calculan al ejecutar)
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
        # Reabrir el mismo wizard para mostrar el resumen
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
```

**Vista del wizard** (incluir en `instance_module_status_views.xml`):

```xml
<record id="view_snapshot_refresh_wizard_form" model="ir.ui.view">
    <field name="name">snapshot.refresh.wizard.form</field>
    <field name="model">snapshot.refresh.wizard</field>
    <field name="arch" type="xml">
        <form string="Refrescar snapshot de instancia">
            <sheet>
                <group>
                    <field name="refresh_modules"/>
                    <field name="refresh_studio_fields"/>
                </group>
                <group attrs="{'invisible': [('scan_done', '=', False)]}">
                    <separator string="Resultado del escaneo"/>
                    <field name="modules_found" readonly="1"/>
                    <field name="studio_fields_found" readonly="1"/>
                </group>
            </sheet>
            <footer>
                <button name="action_refresh" string="Escanear ahora" type="object"
                        class="oe_highlight"
                        attrs="{'invisible': [('scan_done', '=', True)]}"/>
                <button string="Cerrar" class="btn-secondary" special="cancel"/>
            </footer>
        </form>
    </field>
</record>

<record id="action_snapshot_refresh_wizard" model="ir.actions.act_window">
    <field name="name">Refrescar snapshot</field>
    <field name="res_model">snapshot.refresh.wizard</field>
    <field name="view_mode">form</field>
    <field name="target">new</field>
</record>
```

---

## Vistas del Bloque B

### `instance_module_status_views.xml`

**Form view de `instance.module.status`**:

- Group izquierdo: `name`, `display_name_module`, `module_category` (con badge), `version`, `author`
- Group derecho: `state`, `last_scanned`, `is_relevant_for_migration`
- Campo `notes` con placeholder "Notas del consultor sobre este módulo..."
- Pestaña "Dependencias": `dependency_ids` en tree readonly

**Tree view de `instance.module.status`**:

Columnas: `display_name_module`, `name`, `module_category` (badge), `state`, `version`,
`is_relevant_for_migration`, `last_scanned`.

Decorations:
- `decoration-info="module_category == 'custom'"` (destacar los custom)
- `decoration-warning="module_category == 'oca'"`
- `decoration-muted="module_category == 'odoo_official'"`

**Search view de `instance.module.status`**:

Filtros: Solo custom, Solo OCA, Solo Enterprise, Relevantes para migración.
Group by: `module_category`, `state`.

### `instance_studio_field_views.xml`

**Form view de `instance.studio.field`**:

```xml
<form string="Campo Studio">
    <sheet>
        <div class="oe_button_box" name="button_box">
            <button name="action_load_sample_values" type="object"
                    string="Cargar muestra de valores" icon="fa-database"
                    class="oe_stat_button"/>
        </div>
        <group>
            <group string="Identificación">
                <field name="name"/>
                <field name="field_description"/>
                <field name="model_id"/>
                <field name="field_type"/>
                <field name="last_scanned"/>
            </group>
            <group string="Impacto en migración">
                <field name="migration_impact" widget="priority"/>
                <!-- widget priority renderiza como estrellas 0-3,
                     perfecto para low/medium/high/none -->
            </group>
        </group>
        <separator string="Descripción para el cliente"/>
        <field name="client_description"
               placeholder="Explica qué hace este campo en términos de negocio: para qué se usa, quién lo llena, qué impacto tiene..."/>
        <separator string="Notas técnicas de migración"/>
        <field name="migration_notes"
               placeholder="Cómo manejar este campo en la migración: ¿se mantiene?, ¿se mapea a otro campo?, ¿se puede perder?..."/>
        <separator string="Muestra de valores actuales"/>
        <field name="sample_values" readonly="1"
               style="font-family: monospace; white-space: pre-wrap;"/>
    </sheet>
</form>
```

**Tree view de `instance.studio.field`**:

Columnas: `model_id`, `name`, `field_description`, `field_type`, `migration_impact`,
`last_scanned`.

Decoration: `decoration-danger="migration_impact == 'high'"`,
`decoration-warning="migration_impact == 'medium'"`.

**Search view de `instance.studio.field`**:

Filtros: Alto impacto, Sin descripción de cliente, Por modelo.
Group by: `model_id`, `migration_impact`.

---

## Menús (`views/menus.xml`)

```xml
<odoo>
    <data>
        <!-- Raíz -->
        <menuitem id="menu_migration_root"
                  name="Migration Engine"
                  sequence="80"/>

        <!-- ── Bloque A: ETL ── -->
        <menuitem id="menu_migration_etl_sep"
                  name="── ETL ──"
                  parent="menu_migration_root"
                  sequence="10"/>

        <menuitem id="menu_migration_jobs"
                  name="Trabajos de Migración"
                  parent="menu_migration_root"
                  action="action_migration_job"
                  sequence="11"/>

        <menuitem id="menu_migration_runs"
                  name="Historial de Ejecuciones"
                  parent="menu_migration_root"
                  action="action_migration_execution_run_all"
                  sequence="12"/>

        <menuitem id="menu_migration_logs"
                  name="Logs"
                  parent="menu_migration_root"
                  action="action_migration_log_all"
                  sequence="13"/>

        <!-- ── Bloque B: Snapshot ── -->
        <menuitem id="menu_migration_snapshot_sep"
                  name="── Instance Snapshot ──"
                  parent="menu_migration_root"
                  sequence="30"/>

        <menuitem id="menu_instance_modules"
                  name="Módulos Instalados"
                  parent="menu_migration_root"
                  action="action_instance_module_status"
                  sequence="31"/>

        <menuitem id="menu_instance_studio_fields"
                  name="Campos Studio"
                  parent="menu_migration_root"
                  action="action_instance_studio_field"
                  sequence="32"/>

        <menuitem id="menu_snapshot_refresh"
                  name="Refrescar Snapshot"
                  parent="menu_migration_root"
                  action="action_snapshot_refresh_wizard"
                  sequence="33"/>
    </data>
</odoo>
```

---

## Seguridad

### `security/migration_security.xml`

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
access_run_wizard_mgr,run.migration.wizard manager,model_run_migration_wizard,group_migration_manager,1,1,1,1
access_snapshot_wizard_mgr,snapshot.refresh.wizard manager,model_snapshot_refresh_wizard,group_migration_manager,1,1,1,1
access_instance_module_mgr,instance.module.status manager,model_instance_module_status,group_migration_manager,1,1,1,1
access_instance_module_usr,instance.module.status user,model_instance_module_status,group_migration_user,1,0,0,0
access_instance_studio_mgr,instance.studio.field manager,model_instance_studio_field,group_migration_manager,1,1,1,1
access_instance_studio_usr,instance.studio.field user,model_instance_studio_field,group_migration_user,1,0,0,0
```

---

## Consideraciones técnicas críticas para Odoo 17

### 1. `safe_eval` siempre para expresiones de usuario
```python
from odoo.tools.safe_eval import safe_eval
# Nunca eval() directo
```

### 2. Savepoints + `invalidate_all()`
```python
self.env.cr.execute(f'ROLLBACK TO SAVEPOINT {sp}')
self.env.invalidate_all()  # SIEMPRE después de cualquier rollback
```

### 3. `AbstractModel` sin tabla
```python
class MigrationExecution(models.AbstractModel):
    _name = 'migration.execution'
    _auto = False  # Sin tabla PostgreSQL
```

### 4. Widget `domain` en Community vs Enterprise
El widget `domain` es idéntico en Community y Enterprise en Odoo 17. No requiere detección.
```xml
<field name="domain" widget="domain" options="{'model': 'source_model_id'}"/>
```

### 5. `fields.Html` con `sanitize=False`
El campo `preview_html` del wizard usa HTML construido en Python. Necesita `sanitize=False`
para que Odoo no elimine los estilos inline de la tabla de preview.

### 6. Detección Enterprise solo cuando sea necesario
```python
def _is_enterprise(self):
    return bool(self.env['ir.module.module'].sudo().search([
        ('name', '=', 'web_enterprise'), ('state', '=', 'installed')
    ], limit=1))
```
Llamar solo antes de referenciar modelos/vistas/widgets exclusivos de Enterprise.
En este módulo no hay vistas exclusivas Enterprise, así que el helper es de referencia.

### 7. `sudo()` en lecturas de `ir.module.module` e `ir.model.fields`
Estos modelos requieren permisos de administrador para lectura completa.
Siempre usar `.sudo()` en los métodos `refresh_snapshot()` y `refresh_studio_fields()`.

### 8. `migration_impact` como Selection, no `priority`
El widget `priority` de Odoo requiere exactamente los valores `0`, `1`, `2`, `3`.
Definir el campo así para que el widget funcione:
```python
migration_impact = fields.Selection([
    ('0', 'Ninguno'),
    ('1', 'Bajo'),
    ('2', 'Medio'),
    ('3', 'Alto'),
], default='0', string='Impacto en migración')
```

### 9. Self-relation en `instance.module.status`
```python
dependency_ids = fields.Many2many(
    'instance.module.status',
    'instance_module_dep_rel',
    'module_id',
    'dependency_id',
    string='Depende de',
)
```

### 10. Dry run: logs creados fuera del savepoint global
El patrón correcto es acumular en memoria durante el savepoint global y crear los logs
DESPUÉS del `ROLLBACK TO SAVEPOINT`. Ver implementación en `migration.execution.run()`.
Esto garantiza que los logs del dry run persisten aunque toda la transacción de negocio
haya sido revertida.

---

## Flujo de usuario completo

### Bloque A — ETL

1. **Migration Engine > Trabajos** → Nuevo trabajo
2. Seleccionar modelo origen / destino / modo / domain visual
3. Si `mode != create_only`: seleccionar `key_field_ids`
4. Pestaña **Mapeo de campos**: definir transformaciones campo a campo
5. Pestaña **Reglas de validación**: definir validaciones con severidad
6. Botón **Ejecutar** → wizard muestra:
   - Total de registros que serán procesados
   - Tabla HTML con los primeros 10 registros reales y sus campos mapeados
7. Marcar **Dry Run** → Ejecutar → ver `migration.execution.run` con logs
8. Revisar logs: filtrar por tipo, ver traceback en form, exportar CSV
9. Si dry run OK: desmarcar Dry Run, marcar confirmación → Ejecutar en producción
10. **Historial de Ejecuciones**: comparar corridas, ver duración y tasas de error

### Bloque B — Instance Snapshot

1. **Migration Engine > Refrescar Snapshot** → Wizard → "Escanear ahora"
   - Marca qué escanear: módulos, campos Studio, o ambos
   - Muestra resumen: N módulos detectados, M campos Studio detectados
2. **Migration Engine > Módulos Instalados**:
   - Filtrar por categoría: custom, OCA, Enterprise, localization
   - Ver qué módulos son relevantes para migración (custom + OCA)
   - Agregar notas del consultor por módulo
3. **Migration Engine > Campos Studio**:
   - Ver todos los campos `x_studio_*` de la instancia agrupados por modelo
   - En cada campo: completar **Descripción para el cliente** (qué hace el campo en términos de negocio)
   - Definir **Impacto en migración** (ninguno / bajo / medio / alto)
   - Agregar **Notas técnicas** (cómo tratarlo en la migración)
   - Botón "Cargar muestra de valores" → carga hasta 5 valores reales del campo
4. Usar estos registros como base para el **informe de análisis previo a migración**
   que se entrega al cliente

