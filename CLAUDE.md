# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Propósito

Este repositorio contiene la especificación de diseño y la implementación del módulo Odoo 17.0 `migration_engine`. El módulo tiene dos bloques funcionales:

- **Bloque A — Motor ETL:** migra registros entre modelos dentro de la misma instancia de Odoo.
- **Bloque B — Instance Snapshot:** inventario técnico de módulos instalados y campos `x_studio_*`.

Los documentos de especificación son los prompts v1/v2/v3. El **v3** es el definitivo y está completamente implementado.

## Estructura del módulo

```
migration_engine/
├── models/
│   ├── migration_job.py             # Configuración del trabajo ETL
│   ├── migration_execution_run.py   # Agrupa logs de una ejecución (con export CSV)
│   ├── migration_rule.py            # Reglas de validación PRE-transformación
│   ├── migration_field_map.py       # Mapeos campo → campo con constrains
│   ├── migration_log.py             # Un log por evento
│   ├── migration_execution.py       # AbstractModel: motor ETL central
│   ├── instance_module_status.py    # Bloque B: módulos instalados
│   └── instance_studio_field.py     # Bloque B: campos x_studio_*
├── wizards/
│   ├── run_migration_wizard.py      # Wizard ETL con preview HTML
│   └── snapshot_refresh_wizard.py   # Wizard de reescaneo
├── views/                           # XMLs de vistas Odoo
├── security/                        # Grupos y permisos
└── data/                            # Secuencia ir.sequence para runs
```

## Arquitectura central — Bloque A (ETL)

### Flujo de ejecución por registro (`migration.execution`)

1. **Validación** (`_validate_record`): evalúa `migration.rule` activas en orden de `sequence`. Si una regla falla con `on_failure='error'`, retorna `'fatal'` y el registro se salta sin abrir savepoint.
2. **Mapeo** (`_apply_field_maps`): construye el dict `vals` aplicando `migration.field.map` en orden de `sequence`.
3. **Resolución destino** (`_resolve_dest_record`): solo para `update_only`/`create_or_update`; usa `key_field_ids` del job.
4. **Ejecución transaccional**: `SAVEPOINT` por registro → `create`/`write` → `RELEASE` o `ROLLBACK TO`.
5. **Log** (`_flush_logs`): persiste logs en `migration.log` buscando el run activo via `job.execution_run_ids.filtered(state='running')`.

### Firma de `_process_record`

```python
def _process_record(self, job, record, dry_run) -> (str, [dict])
```

Retorna `(result, log_list)` siempre. En modo real llama a `_flush_logs` internamente. En dry_run retorna los log_vals para que `run()` los persista tras el ROLLBACK global.

### Dry run (Opción B)

Savepoint global envuelve toda la ejecución. `_process_record` acumula en memoria. Tras `ROLLBACK TO SAVEPOINT`, `run()` re-crea el `migration.execution.run` y persiste todos los logs. El `ir.sequence` también se llama antes del savepoint para que el nombre del run sea correcto.

### Nombres de ejecución

Generados con `ir.sequence` (código `migration.execution.run`, prefijo `RUN/%(year)s/`).

## Bloque B — Instance Snapshot

- `instance.module.status.refresh_snapshot()`: sincroniza desde `ir.module.module` sin borrar (preserva notas manuales).
- `instance.studio.field.refresh_studio_fields()`: busca `ir.model.fields` con `name like 'x_studio_'` y `state='manual'`.
- `migration_impact`: Selection con valores string `'0'`/`'1'`/`'2'`/`'3'` para compatibilidad con widget `priority`.
- `sample_values`: campo `store=False`; se carga bajo demanda via botón `action_load_sample_values`.
- Ambos modelos usan `.sudo()` en lecturas de `ir.module.module` e `ir.model.fields`.

## Decisiones técnicas críticas para Odoo 17

- **`safe_eval` siempre** para expresiones Python del usuario. Nunca `eval()` directo.
- **Cache del ORM tras rollback**: después de cualquier `ROLLBACK TO SAVEPOINT`, ejecutar `self.env.invalidate_all()`.
- **`migration.execution` es AbstractModel**: requiere `_auto = False`.
- **Many2one en `vals`**: convertir a ID entero cuando `dest_field_id.ttype == 'many2one'`.
- **`key_field_ids`**: tabla intermedia explícita `'migration_job_key_fields_rel'`.
- **Widget `domain`**: `options="{'model': 'source_model_id'}"` — idéntico en Community y Enterprise en Odoo 17.
- **Detección Enterprise**: via `ir.module.module.sudo().search([('name','=','web_enterprise'), ('state','=','installed')])`. Nunca con `try/except ImportError`.
- **`preview_html`**: `fields.Html` con `sanitize=False` para que los estilos inline de la tabla de preview no sean eliminados.
- **`_flush_logs`**: solo se llama en modo no-dry_run. Busca el run activo; si no existe, retorna silenciosamente.

## Seguridad

Dos grupos bajo la categoría `Migration Engine`:
- `group_migration_user`: solo lectura en jobs, runs, logs, módulos y campos studio.
- `group_migration_manager`: CRUD completo en todos los modelos y wizards.
