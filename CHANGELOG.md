# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.

El formato está basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/)
y el proyecto sigue [Versionado Semántico](https://semver.org/lang/es/) con el prefijo de versión de Odoo (`17.0.X.Y.Z`).

---

## [migration_auditor — 17.0.1.0.0] — 2026-06-24

### Añadido

**Nuevo módulo: `migration_auditor`**

- **`audit.project`** — registro central de la auditoría por cliente. Estados: `draft → scanning → done / error`. Heredado de `mail.thread` y `mail.activity.mixin` (chatter + actividades). Smart buttons hacia módulos, campos y modelos detectados. Campos `hourly_rate` y `currency_id` para presupuesto. Métodos `action_run_audit()` (abre wizard), `action_generate_report()` y `action_reset_draft()`.
- **`audit.connection`** — credenciales XML-RPC del cliente (`url`, `database`, `username`, `password`). Campo `last_test_result` (Selection: ok/error) + `last_test_detail`. Botón `action_test_connection()` que llama a `OdooXmlRpcClient` y guarda la versión detectada.
- **`audit.backup`** — tracking del archivo de backup subido: formato detectado, schema temporal, estado de procesamiento, fecha.
- **`audit.module.finding`** — módulo instalado detectado. Categorías: `odoo_official`, `oca`, `custom`, `enterprise`, `localization`. Campo `is_relevant` (computed: True si es custom u OCA). Campo `compatibility_risk`.
- **`audit.field.finding`** — campo manual (`state='manual'`) detectado. Origen: `studio`, `custom_dev`, `other_manual`. Campos `has_data` y `record_count_with_value`.
- **`audit.model.finding`** — modelo custom (`state='manual'`) detectado. `field_count`, `record_count`, `migration_decision`.
- **`audit.volume.finding`** — recuento de registros en 14 modelos estándar de negocio. `volume_tier` computed: `low` (<10k), `medium` (10k-100k), `high` (>100k).
- **`audit.effort.line`** — línea de estimación de horas. Categorías: `analysis`, `custom_module`, `oca_module`, `studio_fields`, `custom_model`, `data_volume`, `testing`, `training`, `contingency`, `other`. Campo `source` (auto/manual) para distinguir las líneas generadas automáticamente.

**Servicios**

- **`OdooXmlRpcClient`** (`services/xmlrpc_client.py`) — wrapper sobre `/xmlrpc/2/common` y `/xmlrpc/2/object`. `socket.setdefaulttimeout(30)`. Métodos: `get_installed_modules()`, `get_custom_fields()`, `get_custom_models()`, `get_record_count()`, `get_field_value_count()`.
- **`BackupProcessor`** (`services/backup_processor.py`) — procesador de backups dentro del mismo schema PostgreSQL (nunca crea bases separadas). Detecta formato (`zip_odoo`, `sql_plain`, `pg_custom`). Extrae dump del ZIP nativo. Importa SQL statement a statement con tolerancia a errores. Llama `pg_restore` vía `subprocess` para pg_custom. Métodos de análisis via SQL directo: `get_installed_modules()`, `get_custom_fields()`, `get_custom_models()`, `get_record_count()`, `get_field_value_count()`, `table_exists()`.

**Wizards**

- **`run.audit.wizard`** — escaneo completo en Modo A (XML-RPC) y Modo B (backup). Método `action_scan()` centraliza el flujo: borra findings anteriores, invoca el scanner correcto, genera líneas de esfuerzo, actualiza estado. `_generate_effort_lines()` crea líneas automáticas con contingencia del 10%.
- **`generate.report.wizard`** — selección del tipo de informe (ejecutivo / técnico / solo presupuesto) e inclusión de cada sección.

**Informe PDF**

- Template QWeb `report_audit_project` con secciones: datos generales, resumen ejecutivo, módulos relevantes, campos custom, modelos custom, volumen de datos, estimación de horas y presupuesto, notas del consultor.
- `ir.actions.report` con `binding_model_id` para mostrar en el menú Imprimir del proyecto.

**Infraestructura**

- `ir.sequence` para nombrado automático de proyectos (`AUDIT/YYYY/XXXX`).
- 6 `ir.config_parameter` con valores por defecto ajustables para tasas de esfuerzo.
- Grupo único `group_auditor_user` bajo categoría `Migration Auditor` (sequence 81).
- `ir.model.access.csv` con 10 filas — CRUD completo para todos los modelos.
- Menús: raíz `Migration Auditor` (seq 52) + `Proyectos de Auditoría` + `Conexiones XML-RPC`.

---

## [17.0.2.0.0] — 2026-06-24

### Añadido

**Bloque B — Instance Snapshot (nuevo)**

- **`instance.module.status`** — inventario de módulos instalados en la instancia. Detecta automáticamente la categoría: `odoo_official`, `oca`, `custom`, `enterprise`, `localization`. Campo `is_relevant_for_migration` (compute: True para custom y OCA). Campo `dependency_ids` (self-relation Many2many). Método `refresh_snapshot()` que sincroniza desde `ir.module.module` sin borrar registros existentes (preserva notas manuales). Helper `_detect_category()` basado en autor y prefijos de nombre.
- **`instance.studio.field`** — inventario de campos `x_studio_*` de la instancia. Campos: `migration_impact` (Selection 0-3, widget `priority`), `client_description`, `migration_notes`, `sample_values` (store=False). Método `refresh_studio_fields()` que sincroniza desde `ir.model.fields` filtrando `state='manual'`. Botón "Cargar muestra de valores" (`action_load_sample_values`) que lee hasta 5 valores distintos no nulos bajo demanda.
- **`snapshot.refresh.wizard`** — wizard para reescanear módulos y/o campos Studio. Muestra resumen post-escaneo (N módulos, M campos) sin cerrar el wizard.
- Vistas completas para ambos modelos nuevos: form, tree, search con decorations por categoría/impacto.
- Helper `_is_enterprise()` en `instance.module.status` para detección de Enterprise en runtime via `ir.module.module`.
- Nuevos permisos en `ir.model.access.csv`: `snapshot.refresh.wizard`, `instance.module.status`, `instance.studio.field`.
- Menús: Módulos Instalados, Campos Studio, Refrescar Snapshot (secuencias 30-32).

**Bloque A — Motor ETL (modificaciones)**

- **`run.migration.wizard`**: nuevo campo `preview_html` (`fields.Html`, `sanitize=False`) que genera una tabla HTML con los primeros 10 registros reales del modelo origen y sus campos mapeados. El campo `record_preview` se renombra a `record_total`. Ambos se computan juntos en `_compute_preview`.
- **`migration.execution`**: `_process_record` refactorizado para aceptar `dry_run` como parámetro y retornar siempre `(result_str, [log_vals])`. En modo real, persiste logs via nuevo método `_flush_logs` (busca el run activo via `job.execution_run_ids.filtered(state='running')`). En dry_run, acumula en memoria para persistir tras el ROLLBACK global.
- Nombres de `migration.execution.run` generados con `ir.sequence` (código `migration.execution.run`, prefijo `RUN/%(year)s/`).
- `__manifest__.py` versión bump a `17.0.2.0.0`, summary actualizado, añadidos `instance_module_status_views.xml` e `instance_studio_field_views.xml` al array `data`.

### Modificado

- `migration.execution._process_record`: firma cambia de `(job, run, record)` a `(job, record, dry_run)`. Ya no recibe el `run` como parámetro; lo resuelve internamente via `_flush_logs`.
- `views/menus.xml`: reestructurado con Bloque B. Eliminados los `menuitem` separadores sin `action` (no válidos en Odoo 17).

---

## [17.0.1.0.0] — 2026-06-24

### Añadido

- **`migration.job`** — modelo principal de configuración del trabajo ETL. Campos: nombre, modelo origen/destino, dominio de filtro, modo (`create_only`, `update_only`, `create_or_update`), campos clave, notas. Smart button con total de ejecuciones.
- **`migration.execution.run`** — agrupa todos los logs de una ejecución concreta. Campos calculados: `success_count`, `warning_count`, `error_count`, `duration_seconds`. Permite comparar historial de ejecuciones independientemente.
- **`migration.field.map`** — mapeo campo a campo con 4 tipos de transformación: `direct`, `fixed_value`, `python_expr`, `lookup`. Campo `required` para controlar si un fallo en el mapeo cancela el registro completo.
- **`migration.rule`** — reglas de validación PRE-transformación con tipos `not_null`, `type_check`, `format_regex`, `python_expr`. Severidad configurable: `warning` (continúa) o `error` (salta el registro sin abrir savepoint).
- **`migration.log`** — un registro de log por evento. Vinculado a `migration.execution.run` con campo `job_id` related y `store=True` para filtrado rápido.
- **`migration.execution`** — `AbstractModel` (`_auto = False`) con el motor ETL completo:
  - Flujo por registro: validación → mapeo → resolución destino → savepoint → log.
  - Savepoint individual por registro; los fallos no afectan los demás registros.
  - `self.env.invalidate_all()` tras cada `ROLLBACK TO SAVEPOINT`.
  - Dry run con savepoint global y acumulación de logs en memoria (Opción B).
- **`run.migration.wizard`** — wizard de lanzamiento con estimado de registros y checkbox de confirmación obligatorio para ejecuciones reales.
- **Modos de operación:** `create_only`, `update_only`, `create_or_update`. Los dos últimos usan `key_field_ids` para resolver el registro destino antes de crear o actualizar.
- **Export CSV** de logs desde `migration.execution.run` usando `csv` + `io.StringIO` + `ir.attachment`.
- **Vistas completas:** form, tree y search para todos los modelos. Widget `domain` con constructor visual para el filtro del job. Decoraciones por tipo de log y estado de ejecución.
- **Seguridad:** categoría `Migration Engine` con grupos `Usuario` (solo lectura) y `Manager` (CRUD completo). Permisos definidos en `ir.model.access.csv`.
- **Menú principal** `Migration Engine` con submenús: Trabajos de Migración, Historial de Ejecuciones, Logs.

---

<!-- Plantilla para próximas versiones:

## [17.0.X.Y.Z] — YYYY-MM-DD

### Añadido
-

### Modificado
-

### Corregido
-

### Eliminado
-

-->
