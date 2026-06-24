# Migration Engine — Odoo 17.0

Módulo Odoo 17.0 con dos bloques funcionales para proyectos de migración:

- **Bloque A — Motor ETL:** migra registros entre modelos dentro de la misma instancia, con transformaciones campo a campo, ejecución transaccional por savepoints y log detallado por ejecución.
- **Bloque B — Instance Snapshot:** inventario técnico de la instancia — módulos instalados categorizados y campos `x_studio_*` con ficha descriptiva de impacto para el cliente.

Compatible con **Odoo 17.0 Community y Enterprise**. La detección Community/Enterprise se hace en runtime; ninguna funcionalidad rompe la instalación en Community.

> **Importante:** El motor ETL NO migra bases de datos entre versiones de Odoo. Opera exclusivamente dentro de una misma instancia.

---

## Características

### Bloque A — Motor ETL

- **Configuración sin código:** define origen, destino, dominio de filtro y mapeos desde la interfaz.
- **4 tipos de transformación por campo:** copia directa, valor fijo, expresión Python, lookup a modelo externo.
- **Reglas de validación PRE-transformación:** `not_null`, `type_check`, `format_regex`, expresión Python. Con severidad configurable (warning / error fatal).
- **3 modos de operación:** `create_only`, `update_only`, `create_or_update` con campos clave configurables.
- **Ejecución transaccional por registro:** savepoint individual por cada registro; un fallo no cancela el resto.
- **Dry Run:** simulación completa con rollback global. Los logs muestran exactamente qué habría ocurrido.
- **Vista previa de datos en el wizard:** tabla HTML con los primeros 10 registros reales del modelo origen antes de ejecutar.
- **Historial de ejecuciones:** cada "disparo" queda como `migration.execution.run` independiente con duración y contadores.
- **Export de logs a CSV** desde la vista de cada ejecución.

### Bloque B — Instance Snapshot

- **Inventario de módulos:** detecta automáticamente categoría (`odoo_official`, `oca`, `custom`, `enterprise`, `localization`). Marca los relevantes para migración (custom + OCA).
- **Inventario de campos Studio:** lista todos los `x_studio_*` de la instancia con tipo, modelo, descripción para el cliente, impacto en migración (ninguno / bajo / medio / alto) y muestra de valores reales bajo demanda.
- **Wizard de reescaneo:** un botón actualiza módulos y/o campos Studio y muestra el resumen post-escaneo.

---

## Estructura del módulo

```
migration_engine/
├── models/
│   ├── migration_job.py             # Configuración del trabajo ETL
│   ├── migration_execution_run.py   # Agrupa logs de una ejecución
│   ├── migration_rule.py            # Reglas de validación PRE-transformación
│   ├── migration_field_map.py       # Mapeos campo → campo
│   ├── migration_log.py             # Un log por evento (OK / warning / error)
│   ├── migration_execution.py       # Motor de ejecución (AbstractModel)
│   ├── instance_module_status.py    # Inventario de módulos instalados
│   └── instance_studio_field.py     # Inventario de campos x_studio_*
├── wizards/
│   ├── run_migration_wizard.py      # Wizard de lanzamiento con preview
│   └── snapshot_refresh_wizard.py   # Wizard de reescaneo de instancia
├── views/                           # Vistas XML de Odoo
├── security/                        # Grupos y permisos
└── data/                            # Secuencias
```

---

## Instalación

1. Copia la carpeta `migration_engine/` al directorio de addons de tu instancia Odoo 17.
2. Reinicia el servidor Odoo.
3. Activa el modo desarrollador.
4. Ve a **Aplicaciones**, busca "Migration Engine" e instala.

```bash
# Alternativamente, desde CLI:
./odoo-bin -u migration_engine -d <nombre_base_de_datos>
```

---

## Flujo de uso

### Bloque A — ETL

1. **Migration Engine → Trabajos** → Crear nuevo trabajo.
2. Seleccionar modelo origen y destino; elegir modo (`create_only` / `create_or_update` / etc.).
3. Si el modo requiere clave: seleccionar los **Campos clave**.
4. Definir el **dominio de filtro** (constructor visual).
5. Pestaña **Mapeo de campos** y **Reglas de validación**.
6. Botón **Ejecutar / Dry Run** → el wizard muestra el total de registros y una tabla con los primeros 10 reales.
7. Marcar **Dry Run** y ejecutar → revisar logs en el `migration.execution.run` resultante.
8. Si el dry run es satisfactorio: ejecutar en producción (requiere checkbox de confirmación).
9. **Historial de Ejecuciones**: comparar corridas, exportar logs a CSV.

### Bloque B — Instance Snapshot

1. **Migration Engine → Refrescar Snapshot** → Marcar qué escanear → "Escanear ahora".
2. **Módulos Instalados**: filtrar por categoría, agregar notas del consultor por módulo.
3. **Campos Studio**: por cada `x_studio_*`, completar la descripción para el cliente, definir el impacto en migración y cargar muestra de valores.
4. Usar estos registros como base para el informe de análisis previo a migración.

---

## Tipos de transformación de campos

| Tipo | Descripción |
|---|---|
| `direct` | Copia el valor del campo origen tal cual |
| `fixed_value` | Asigna siempre un valor fijo (string) |
| `python_expr` | Evalúa una expresión Python con `safe_eval`. Variables: `value`, `record`, `env` |
| `lookup` | Busca un registro en un modelo externo y retorna el campo indicado |

## Tipos de reglas de validación

| Tipo | Descripción |
|---|---|
| `not_null` | El valor debe ser no vacío (`0` es válido para enteros) |
| `type_check` | El valor no debe ser `None` |
| `format_regex` | El valor debe coincidir con el patrón regex configurado |
| `python_expr` | Expresión Python que retorna `True`/`False`. Variables: `value`, `record`, `env` |

## Categorías de módulos (Bloque B)

| Categoría | Criterio |
|---|---|
| `enterprise` | Nombre en lista de módulos Enterprise conocidos (`web_enterprise`, `sign`, etc.) |
| `localization` | Nombre empieza con `l10n_` |
| `oca` | Autor contiene "OCA" u "Odoo Community Association" |
| `odoo_official` | Autor contiene "Odoo S.A." o nombre con prefijo estándar (`sale`, `account`, etc.) |
| `custom` | No encaja en ninguna categoría anterior |

---

## Notas técnicas

- Las expresiones Python del usuario se evalúan siempre con `safe_eval` (nunca `eval()` directo).
- Tras cualquier `ROLLBACK TO SAVEPOINT`, se ejecuta `self.env.invalidate_all()`.
- El dry run usa un savepoint global: los logs se acumulan en memoria y se persisten después del rollback global.
- `migration.execution` es un `AbstractModel` con `_auto = False`.
- La detección Community/Enterprise se hace via `ir.module.module` con `.sudo()`, nunca con `try/except ImportError`.
- `migration_impact` usa valores `'0'`/`'1'`/`'2'`/`'3'` (strings) para compatibilidad con el widget `priority` de Odoo.

---

## Versión y compatibilidad

| Campo | Valor |
|---|---|
| Versión del módulo | `17.0.2.0.0` |
| Versión de Odoo | `17.0` (Community y Enterprise) |
| Licencia | OPL-1 |
| Autor | AlejtoDev |
| Website | https://odoo.alejtodev.cl |

---

## Roadmap (fase 3)

- Scheduler automático por job (`ir.cron` configurable).
- Export del snapshot (módulos + campos Studio) a Excel/PDF para el informe al cliente.
- Estadísticas gráficas: tasa de éxito por ejecución, progreso acumulado.
- Versionado de configuración del job (snapshots de field_maps y rules).
