# Prompt — Claude Code: módulo `migration_auditor` para Odoo 17.0
# Herramienta interna de AlejtoDev para auditoría remota y presupuesto de migraciones

---

## Contexto general

Construye un módulo Odoo 17.0 llamado `migration_auditor`. Es una herramienta interna que
vive en el Odoo propio del consultor (ej. odoo.alejtodev.cl) y NO se instala en el cliente.

El módulo permite auditar la instancia Odoo de un cliente de **dos formas**:

**Modo A — Conexión directa XML-RPC**: el consultor ingresa la URL y credenciales del Odoo
del cliente. El sistema se conecta remotamente, escanea módulos, campos custom, modelos
custom y volumen de datos.

**Modo B — Backup upload**: el cliente sube o envía un backup de su Odoo. Puede ser un
`.zip` (backup nativo de Odoo con filestore + dump) o un `.sql`/`.dump` (dump PostgreSQL
puro). El sistema detecta el formato automáticamente, extrae el dump SQL, lo carga en un
schema temporal dentro del PostgreSQL propio de tu Odoo (mismo servidor, diferente schema),
ejecuta queries directas de análisis, y al terminar elimina el schema temporal.

En ambos modos el resultado es idéntico: un proyecto de auditoría con inventario de módulos,
campos custom, modelos custom, volumen de datos, estimación de esfuerzo en horas y un
informe PDF/HTML entregable al cliente.

---

## Estructura de archivos

```
migration_auditor/
├── __init__.py
├── __manifest__.py
│
├── models/
│   ├── __init__.py
│   ├── audit_project.py           # proyecto de auditoría por cliente
│   ├── audit_connection.py        # credenciales XML-RPC (Modo A)
│   ├── audit_backup.py            # gestión del backup subido (Modo B)
│   ├── audit_module_finding.py    # módulos detectados
│   ├── audit_field_finding.py     # campos custom/studio detectados
│   ├── audit_model_finding.py     # modelos custom completos
│   ├── audit_volume_finding.py    # conteo de registros por modelo clave
│   └── audit_effort_line.py       # líneas de estimación de horas
│
├── services/
│   ├── __init__.py
│   ├── xmlrpc_client.py           # wrapper XML-RPC para Modo A
│   └── backup_processor.py        # extractor y analizador para Modo B
│
├── wizards/
│   ├── __init__.py
│   ├── run_audit_wizard.py        # dispara el escaneo (ambos modos)
│   └── generate_report_wizard.py  # previsualiza y genera el informe
│
├── report/
│   ├── audit_report_template.xml  # template QWeb del informe
│   └── audit_report_action.xml    # acción ir.actions.report
│
├── security/
│   ├── auditor_security.xml
│   └── ir.model.access.csv
│
└── data/
    ├── auditor_data.xml            # secuencias, parámetros base
    └── effort_rules_data.xml       # reglas de esfuerzo predeterminadas
```

---

## `__manifest__.py`

```python
{
    'name': 'Migration Auditor',
    'version': '17.0.1.0.0',
    'summary': 'Auditoría remota de instancias Odoo y presupuesto de migraciones',
    'category': 'Technical',
    'author': 'AlejtoDev',
    'website': 'https://odoo.alejtodev.cl',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/auditor_security.xml',
        'security/ir.model.access.csv',
        'data/auditor_data.xml',
        'data/effort_rules_data.xml',
        'report/audit_report_action.xml',
        'report/audit_report_template.xml',
        'views/audit_project_views.xml',
        'views/audit_connection_views.xml',
        'views/audit_backup_views.xml',
        'views/audit_finding_views.xml',
        'views/audit_effort_line_views.xml',
        'views/menus.xml',
    ],
    'external_dependencies': {
        'python': ['xmlrpc.client', 'zipfile', 'psycopg2'],
    },
    'license': 'OPL-1',
    'installable': True,
    'application': True,
}
```

---

## ══════════════════════════════════════
## MODELOS
## ══════════════════════════════════════

---

## `audit.project` (`models/audit_project.py`)

Registro central de un proyecto de auditoría. Agrupa todo lo detectado de un cliente.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre del proyecto, ej. "Auditoría Empresa ABC — Mayo 2025" |
| `client_name` | Char | Nombre del cliente |
| `client_email` | Char | Email de contacto del cliente |
| `source_version` | Selection | Versión Odoo origen: `12.0`, `13.0`, `14.0`, `15.0`, `16.0`, `17.0` |
| `target_version` | Selection | Versión Odoo destino: mismas opciones |
| `audit_mode` | Selection | `xmlrpc` (conexión directa) / `backup` (archivo subido) |
| `connection_id` | Many2one → `audit.connection` | Credenciales XML-RPC (Modo A) |
| `backup_id` | Many2one → `audit.backup` | Backup procesado (Modo B) |
| `state` | Selection | `draft`, `scanning`, `done`, `error` |
| `scan_date` | Datetime | Fecha del último escaneo |
| `odoo_version_detected` | Char | Versión detectada automáticamente del cliente |
| `is_enterprise` | Boolean | Si el cliente usa Enterprise (detectado) |
| `module_finding_ids` | One2many → `audit.module.finding` | Módulos detectados |
| `field_finding_ids` | One2many → `audit.field.finding` | Campos custom detectados |
| `model_finding_ids` | One2many → `audit.model.finding` | Modelos custom detectados |
| `volume_finding_ids` | One2many → `audit.volume.finding` | Volumen de datos |
| `effort_line_ids` | One2many → `audit.effort.line` | Líneas de estimación |
| `hourly_rate` | Float | Tarifa hora del consultor (para calcular costo total) |
| `total_hours` | Float | Compute: suma de `effort_line_ids.estimated_hours` |
| `total_cost` | Float | Compute: `total_hours * hourly_rate` |
| `currency_id` | Many2one → `res.currency` | Moneda para el presupuesto |
| `consultant_notes` | Text | Notas internas del consultor |
| `executive_summary` | Text | Resumen ejecutivo para el cliente (editable) |
| `message_ids` | One2many (mail.thread) | Chatter |

### Herencia

```python
class AuditProject(models.Model):
    _name = 'audit.project'
    _description = 'Proyecto de auditoría de migración'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scan_date desc, id desc'
```

### Métodos

- `action_run_audit()`: Abre `run.audit.wizard` con `project_id = self.id`
- `action_generate_report()`: Abre `generate.report.wizard` con `project_id = self.id`
- `action_reset_draft()`: Limpia todos los findings y vuelve a `draft`
- `_compute_totals()`: Suma horas y calcula costo total
- `action_view_modules()`: Smart button → módulos del proyecto
- `action_view_fields()`: Smart button → campos custom del proyecto
- `action_view_models()`: Smart button → modelos custom del proyecto

---

## `audit.connection` (`models/audit_connection.py`)

Credenciales de conexión XML-RPC al Odoo del cliente. Reutilizable entre proyectos.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre identificador, ej. "Empresa ABC — Producción" |
| `url` | Char | URL base del Odoo del cliente, ej. `https://cliente.odoo.com` |
| `database` | Char | Nombre de la base de datos |
| `username` | Char | Usuario administrador |
| `password` | Char | Contraseña (usar `password=True` para enmascarar) |
| `last_test_date` | Datetime | Última prueba de conexión exitosa |
| `last_test_result` | Text | Resultado del último test |
| `odoo_version` | Char | Versión detectada al conectar |

### Métodos

```python
def action_test_connection(self):
    """
    Prueba la conexión XML-RPC y actualiza last_test_date y odoo_version.
    Usa xmlrpc_client.py para conectarse.
    """
    from ..services.xmlrpc_client import OdooXmlRpcClient
    try:
        client = OdooXmlRpcClient(self.url, self.database, self.username, self.password)
        version = client.get_server_version()
        self.write({
            'last_test_date': fields.Datetime.now(),
            'odoo_version': version.get('server_version', 'desconocida'),
            'last_test_result': f'OK — Odoo {version.get("server_version")}',
        })
        return self._notify_success('Conexión exitosa')
    except Exception as e:
        self.write({
            'last_test_date': fields.Datetime.now(),
            'last_test_result': f'ERROR: {str(e)}',
        })
        raise UserError(f'No se pudo conectar: {e}')
```

---

## `audit.backup` (`models/audit_backup.py`)

Gestiona el archivo de backup subido por el cliente. Detecta el formato y controla
el ciclo de vida del schema temporal en PostgreSQL.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `name` | Char | Nombre descriptivo |
| `backup_file` | Binary | Archivo subido (attachment) |
| `backup_filename` | Char | Nombre original del archivo |
| `backup_format` | Selection | `zip_odoo`, `sql_plain`, `pg_custom` — detectado automáticamente |
| `file_size_mb` | Float | Tamaño en MB (compute) |
| `state` | Selection | `pending`, `processing`, `ready`, `error`, `cleaned` |
| `schema_name` | Char | Nombre del schema temporal creado en PostgreSQL |
| `processing_log` | Text | Log del proceso de extracción e importación |
| `odoo_version_detected` | Char | Versión detectada dentro del backup |
| `processed_date` | Datetime | Cuándo terminó el procesamiento |

### Métodos clave (implementados en `backup_processor.py`, llamados desde aquí)

- `action_process_backup()`: Detecta formato, extrae dump, crea schema, importa
- `action_clean_schema()`: Elimina el schema temporal de PostgreSQL
- `_detect_format()`: Retorna `zip_odoo`, `sql_plain` o `pg_custom` según el archivo

---

## `audit.module.finding` (`models/audit_module_finding.py`)

Un registro por cada módulo instalado detectado en el cliente.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `project_id` | Many2one → `audit.project` | Proyecto padre |
| `name` | Char | Nombre técnico del módulo |
| `display_name_module` | Char | Nombre legible |
| `author` | Char | Autor |
| `version` | Char | Versión instalada |
| `module_category` | Selection | `odoo_official`, `oca`, `custom`, `enterprise`, `localization`, `unknown` |
| `is_relevant` | Boolean | Compute: True si `custom` o `oca` |
| `compatibility_risk` | Selection | `low`, `medium`, `high` — editable manualmente |
| `migration_notes` | Text | Notas del consultor sobre este módulo |
| `effort_hours` | Float | Horas estimadas solo para este módulo |

---

## `audit.field.finding` (`models/audit_field_finding.py`)

Un registro por cada campo custom detectado (`x_studio_*`, `x_*`, campos `state=manual`).

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `project_id` | Many2one → `audit.project` | Proyecto padre |
| `name` | Char | Nombre técnico del campo |
| `field_description` | Char | Label del campo |
| `model_name` | Char | Modelo al que pertenece |
| `field_type` | Char | Tipo (`char`, `integer`, `many2one`, etc.) |
| `field_origin` | Selection | `studio` (empieza con `x_studio_`), `custom_dev` (empieza con `x_` pero no studio), `other_manual` |
| `has_data` | Boolean | Si tiene registros con valor no nulo (detectado en Modo B vía SQL) |
| `record_count_with_value` | Integer | Cantidad de registros con valor (Modo B) |
| `migration_decision` | Selection | `migrate`, `recreate_studio`, `drop`, `pending` |
| `effort_hours` | Float | Horas estimadas para este campo |
| `consultant_notes` | Text | Notas del consultor |

---

## `audit.model.finding` (`models/audit_model_finding.py`)

Un registro por cada modelo completamente custom (`state=manual` en `ir.model`).

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `project_id` | Many2one → `audit.project` | Proyecto padre |
| `name` | Char | Nombre técnico del modelo (`model` en `ir.model`) |
| `description` | Char | Descripción del modelo |
| `field_count` | Integer | Cantidad de campos propios del modelo |
| `record_count` | Integer | Cantidad de registros (Modo B vía SQL, Modo A vía search_count) |
| `has_menu` | Boolean | Si tiene ítem de menú asociado |
| `migration_decision` | Selection | `migrate_full`, `migrate_data_only`, `drop`, `pending` |
| `effort_hours` | Float | Horas estimadas |
| `consultant_notes` | Text | Notas del consultor |

---

## `audit.volume.finding` (`models/audit_volume_finding.py`)

Conteo de registros en los modelos estándar más importantes para estimar esfuerzo.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `project_id` | Many2one → `audit.project` | Proyecto padre |
| `model_name` | Char | Nombre técnico del modelo |
| `display_name` | Char | Nombre legible |
| `record_count` | Integer | Total de registros |
| `volume_tier` | Selection | Compute: `low` (<10k), `medium` (10k-100k), `high` (>100k) |
| `effort_extra_hours` | Float | Horas adicionales por volumen (compute basado en tier) |

### Modelos estándar siempre escaneados

```python
VOLUME_MODELS = [
    ('res.partner', 'Contactos'),
    ('account.move', 'Facturas / Asientos'),
    ('account.move.line', 'Líneas contables'),
    ('sale.order', 'Órdenes de venta'),
    ('sale.order.line', 'Líneas de venta'),
    ('purchase.order', 'Órdenes de compra'),
    ('stock.move', 'Movimientos de stock'),
    ('stock.picking', 'Transferencias'),
    ('mrp.production', 'Órdenes de producción'),
    ('hr.employee', 'Empleados'),
    ('project.task', 'Tareas'),
    ('crm.lead', 'Oportunidades CRM'),
    ('product.template', 'Productos'),
    ('product.product', 'Variantes de producto'),
]
```

---

## `audit.effort.line` (`models/audit_effort_line.py`)

Líneas de estimación de horas. Se generan automáticamente al terminar el escaneo
y son editables manualmente por el consultor.

### Campos

| Campo | Tipo | Descripción |
|---|---|---|
| `project_id` | Many2one → `audit.project` | Proyecto padre |
| `sequence` | Integer | Orden |
| `category` | Selection | `analysis`, `custom_module`, `oca_module`, `studio_fields`, `custom_model`, `data_volume`, `testing`, `training`, `contingency`, `other` |
| `description` | Char | Descripción de la línea |
| `source` | Selection | `auto` (generada por el scanner) / `manual` (agregada por el consultor) |
| `estimated_hours` | Float | Horas estimadas |
| `unit_price` | Float | Related de `project_id.hourly_rate` |
| `subtotal` | Float | Compute: `estimated_hours * unit_price` |
| `reference` | Char | Referencia al finding que generó esta línea (ej. nombre del módulo) |

---

## ══════════════════════════════════════
## SERVICIOS
## ══════════════════════════════════════

---

## `services/xmlrpc_client.py` — Modo A

```python
import xmlrpc.client
import logging

_logger = logging.getLogger(__name__)


class OdooXmlRpcClient:
    """
    Wrapper sobre el XML-RPC de Odoo.
    Maneja autenticación y ejecuta llamadas con manejo de errores.
    """

    def __init__(self, url, database, username, password):
        self.url = url.rstrip('/')
        self.database = database
        self.username = username
        self.password = password
        self._uid = None
        self._authenticate()

    def _authenticate(self):
        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        self._uid = common.authenticate(
            self.database, self.username, self.password, {}
        )
        if not self._uid:
            raise ConnectionError(
                f'Autenticación fallida para {self.username}@{self.database}'
            )

    def get_server_version(self):
        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        return common.version()

    def execute(self, model, method, domain=None, fields=None, **kwargs):
        models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
        args = [domain or []]
        if fields:
            kwargs['fields'] = fields
        return models.execute_kw(
            self.database, self._uid, self.password,
            model, method, args, kwargs
        )

    def search_read(self, model, domain=None, fields=None, limit=0, offset=0):
        return self.execute(
            model, 'search_read',
            domain=domain or [],
            fields=fields or [],
            limit=limit,
            offset=offset,
        )

    def search_count(self, model, domain=None):
        return self.execute(model, 'search_count', domain=domain or [])

    # ── Métodos de auditoría ──────────────────────────────────────────────

    def get_installed_modules(self):
        return self.search_read(
            'ir.module.module',
            domain=[('state', '=', 'installed')],
            fields=['name', 'shortdesc', 'author', 'installed_version', 'state'],
        )

    def get_custom_fields(self):
        """Campos con state=manual: incluye x_studio_*, x_* y otros campos manuales."""
        return self.search_read(
            'ir.model.fields',
            domain=[('state', '=', 'manual')],
            fields=['name', 'field_description', 'model_id', 'ttype', 'state'],
        )

    def get_custom_models(self):
        return self.search_read(
            'ir.model',
            domain=[('state', '=', 'manual')],
            fields=['name', 'model', 'field_id', 'info'],
        )

    def get_record_count(self, model_name):
        """
        Retorna el conteo de registros del modelo. Si el modelo no existe
        en esa instancia, retorna -1 silenciosamente.
        """
        try:
            return self.search_count(model_name)
        except Exception:
            return -1

    def get_field_value_count(self, model_name, field_name):
        """
        Retorna cuántos registros tienen un valor no nulo/False en el campo.
        Solo disponible en Modo A.
        """
        try:
            return self.search_count(
                model_name,
                domain=[(field_name, 'not in', [False, '', 0])]
            )
        except Exception:
            return -1
```

---

## `services/backup_processor.py` — Modo B

```python
import os
import re
import zipfile
import tempfile
import logging
import psycopg2

_logger = logging.getLogger(__name__)

# Prefijo único para schemas temporales de auditoría
SCHEMA_PREFIX = 'audit_tmp_'


class BackupProcessor:
    """
    Procesa backups de Odoo (zip nativo o dump SQL/pg_custom).
    Crea un schema temporal en el PostgreSQL local del Odoo del consultor,
    importa el dump en ese schema, expone métodos de consulta, y permite
    limpieza posterior.

    NUNCA crea una base de datos separada. Trabaja con schemas dentro de
    la misma base de datos del Odoo del consultor.
    """

    def __init__(self, db_connection_string, schema_name):
        """
        db_connection_string: DSN de la BD del Odoo propio del consultor.
        Se obtiene desde odoo.conf o desde tools.config.
        schema_name: nombre del schema temporal a crear/usar.
        """
        self.dsn = db_connection_string
        self.schema = schema_name
        self._conn = None

    def _get_conn(self):
        if not self._conn or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
        return self._conn

    # ── Detección de formato ───────────────────────────────────────────────

    @staticmethod
    def detect_format(filename, file_bytes):
        """
        Detecta el formato del backup a partir del nombre y los primeros bytes.
        Retorna: 'zip_odoo' | 'sql_plain' | 'pg_custom'
        """
        name_lower = filename.lower()
        magic = file_bytes[:8] if len(file_bytes) >= 8 else file_bytes

        if name_lower.endswith('.zip') or magic[:2] == b'PK':
            return 'zip_odoo'

        # pg_custom: empieza con 'PGDMP'
        if magic[:5] == b'PGDMP':
            return 'pg_custom'

        # SQL plano: texto que empieza con '--' o 'SET ' o 'CREATE '
        try:
            head = file_bytes[:200].decode('utf-8', errors='ignore').strip()
            if head.startswith('--') or head.upper().startswith(('SET ', 'CREATE ', 'BEGIN')):
                return 'sql_plain'
        except Exception:
            pass

        # Por defecto asumir SQL si tiene extensión .sql
        if name_lower.endswith('.sql'):
            return 'sql_plain'

        return 'sql_plain'  # fallback

    # ── Extracción del dump ────────────────────────────────────────────────

    @staticmethod
    def extract_dump_from_zip(zip_bytes):
        """
        Extrae el dump SQL del zip de backup nativo de Odoo.
        El backup nativo tiene esta estructura:
            backup.zip
            ├── dump.sql       ← SQL plano (en versiones ≤ 15)
            ├── filestore/     ← archivos adjuntos
            └── manifest.json  ← metadata (incluye versión Odoo)

        A partir de Odoo 16 el dump puede ser dump.sql o dump.pg (pg_custom).
        Retorna (dump_bytes, manifest_dict).
        """
        import json
        import io

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()

            # Leer manifest si existe
            manifest = {}
            if 'manifest.json' in names:
                manifest = json.loads(zf.read('manifest.json'))

            # Buscar el dump — puede llamarse dump.sql, dump.pg, o dump
            dump_name = next(
                (n for n in names if re.match(r'dump(\.(sql|pg))?$', n)),
                None
            )
            if not dump_name:
                raise ValueError(
                    'No se encontró el archivo dump dentro del zip. '
                    f'Archivos encontrados: {names}'
                )

            dump_bytes = zf.read(dump_name)
            return dump_bytes, manifest

    # ── Schema temporal ────────────────────────────────────────────────────

    def create_schema(self):
        """Crea el schema temporal si no existe."""
        conn = self._get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"'
            )
        _logger.info('BackupProcessor: schema %s creado', self.schema)

    def drop_schema(self):
        """Elimina el schema temporal y todo su contenido."""
        conn = self._get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'
            )
        _logger.info('BackupProcessor: schema %s eliminado', self.schema)

    def import_sql_dump(self, sql_bytes, log_callback=None):
        """
        Importa un dump SQL plano dentro del schema temporal.
        Estrategia:
        1. Establecer search_path al schema temporal
        2. Ejecutar el SQL en bloques por sentencia
        3. Ignorar errores no críticos (extensiones, roles, etc.)
        4. Loguear errores reales
        """
        conn = self._get_conn()
        conn.autocommit = False

        def log(msg):
            _logger.info(msg)
            if log_callback:
                log_callback(msg)

        try:
            sql_text = sql_bytes.decode('utf-8', errors='replace')

            with conn.cursor() as cur:
                # Establecer schema de trabajo
                cur.execute(f'SET search_path TO "{self.schema}", public')

                # Dividir en statements y ejecutar uno por uno
                # Usamos una heurística simple: split por ';' + newline
                # para evitar partir strings con punto y coma
                statements = self._split_sql(sql_text)
                total = len(statements)
                errors = 0

                for i, stmt in enumerate(statements):
                    stmt = stmt.strip()
                    if not stmt:
                        continue
                    # Saltar sentencias que no aplican al schema temporal
                    if self._should_skip(stmt):
                        continue
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        errors += 1
                        conn.rollback()
                        # Re-establecer contexto después del rollback
                        cur.execute(f'SET search_path TO "{self.schema}", public')
                        if errors <= 10:  # solo loguear los primeros 10 errores
                            log(f'[WARN stmt {i}/{total}] {str(e)[:200]}')

            conn.commit()
            log(f'Importación completada. {total} statements, {errors} errores omitidos.')

        except Exception as e:
            conn.rollback()
            raise RuntimeError(f'Error importando dump SQL: {e}') from e

    def import_pg_custom_dump(self, dump_bytes, log_callback=None):
        """
        Importa un dump en formato pg_custom (pg_restore).
        Como no podemos llamar pg_restore directamente desde Python de forma
        portable, convertimos a SQL usando pg_restore --schema-only y
        --data-only en dos pasos via subprocess.
        Requiere que pg_restore esté disponible en el PATH del servidor.
        """
        import subprocess
        import io

        def log(msg):
            _logger.info(msg)
            if log_callback:
                log_callback(msg)

        # Escribir el dump a un archivo temporal
        with tempfile.NamedTemporaryFile(suffix='.dump', delete=False) as tmp:
            tmp.write(dump_bytes)
            tmp_path = tmp.name

        try:
            # Extraer el SQL del dump usando pg_restore
            result = subprocess.run(
                ['pg_restore', '--no-owner', '--no-acl', '-f', '-', tmp_path],
                capture_output=True,
                timeout=300,
            )
            if result.returncode != 0 and not result.stdout:
                raise RuntimeError(
                    f'pg_restore falló: {result.stderr.decode()[:500]}'
                )
            sql_bytes = result.stdout
            log(f'pg_restore extrajo {len(sql_bytes)} bytes de SQL')
            self.import_sql_dump(sql_bytes, log_callback)
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def _split_sql(sql_text):
        """
        Divide un dump SQL en statements individuales.
        Heurística: split en ';' seguido de newline, respetando bloques $$ ... $$.
        """
        statements = []
        current = []
        in_dollar_quote = False
        dollar_tag = ''

        lines = sql_text.split('\n')
        for line in lines:
            # Detectar apertura/cierre de bloques $$ (funciones PL/pgSQL)
            if not in_dollar_quote:
                match = re.search(r'\$(\w*)\$', line)
                if match:
                    in_dollar_quote = True
                    dollar_tag = match.group(0)
            else:
                if dollar_tag in line:
                    in_dollar_quote = False

            current.append(line)

            if not in_dollar_quote and line.rstrip().endswith(';'):
                statements.append('\n'.join(current))
                current = []

        if current:
            statements.append('\n'.join(current))

        return statements

    @staticmethod
    def _should_skip(stmt):
        """
        Retorna True para statements que no aplican en un schema temporal:
        extensiones, roles, configuraciones de servidor, etc.
        """
        stmt_upper = stmt.upper().lstrip()
        SKIP_PREFIXES = (
            'CREATE EXTENSION',
            'COMMENT ON EXTENSION',
            'CREATE ROLE',
            'ALTER ROLE',
            'CREATE USER',
            'ALTER USER',
            'GRANT ',
            'REVOKE ',
            'SET DEFAULT_TABLESPACE',
            'SET CLIENT_ENCODING',
            'SET STANDARD_CONFORMING',
            'SET CHECK_FUNCTION_BODIES',
            'SET CLIENT_MIN_MESSAGES',
            'SET ROW_SECURITY',
            'SELECT PG_CATALOG',
            'ALTER DATABASE',
        )
        return any(stmt_upper.startswith(p) for p in SKIP_PREFIXES)

    # ── Queries de análisis ────────────────────────────────────────────────

    def query(self, sql, params=None):
        """Ejecuta una query en el schema temporal y retorna lista de dicts."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{self.schema}", public')
            cur.execute(sql, params or [])
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_installed_modules(self):
        return self.query("""
            SELECT name, shortdesc, author, latest_version AS installed_version, state
            FROM ir_module_module
            WHERE state = 'installed'
            ORDER BY name
        """)

    def get_custom_fields(self):
        return self.query("""
            SELECT
                f.name,
                f.field_description,
                m.model AS model_name,
                f.ttype,
                f.state
            FROM ir_model_fields f
            JOIN ir_model m ON m.id = f.model_id
            WHERE f.state = 'manual'
            ORDER BY m.model, f.name
        """)

    def get_custom_models(self):
        return self.query("""
            SELECT
                m.model,
                m.name,
                m.info,
                COUNT(f.id) AS field_count
            FROM ir_model m
            LEFT JOIN ir_model_fields f ON f.model_id = m.id AND f.state = 'base'
            WHERE m.state = 'manual'
            GROUP BY m.id, m.model, m.name, m.info
            ORDER BY m.model
        """)

    def get_record_count(self, table_name):
        """
        Cuenta registros en una tabla del schema temporal.
        Convierte 'res.partner' → 'res_partner' para el nombre de tabla SQL.
        """
        sql_table = table_name.replace('.', '_')
        try:
            result = self.query(f'SELECT COUNT(*) AS cnt FROM "{sql_table}"')
            return result[0]['cnt'] if result else 0
        except Exception:
            return -1

    def get_field_value_count(self, table_name, field_name):
        """
        Cuenta registros con valor no nulo en un campo custom.
        Solo disponible en Modo B.
        """
        sql_table = table_name.replace('.', '_')
        try:
            result = self.query(
                f'SELECT COUNT(*) AS cnt FROM "{sql_table}" '
                f'WHERE "{field_name}" IS NOT NULL '
                f'AND "{field_name}"::text NOT IN (\'\', \'0\', \'false\')'
            )
            return result[0]['cnt'] if result else 0
        except Exception:
            return -1

    def get_odoo_version(self):
        """Detecta la versión de Odoo desde ir_config_parameter."""
        try:
            result = self.query("""
                SELECT value FROM ir_config_parameter
                WHERE key = 'web.base.url.freeze'
                   OR key = 'database.uuid'
                LIMIT 1
            """)
            # Buscar la versión en la tabla de módulos base
            ver = self.query("""
                SELECT latest_version FROM ir_module_module
                WHERE name = 'base' AND state = 'installed'
                LIMIT 1
            """)
            return ver[0]['latest_version'] if ver else 'desconocida'
        except Exception:
            return 'desconocida'

    def table_exists(self, table_name):
        sql_table = table_name.replace('.', '_')
        result = self.query("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
            ) AS exists
        """, [self.schema, sql_table])
        return result[0]['exists'] if result else False

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
```

---

## ══════════════════════════════════════
## WIZARDS
## ══════════════════════════════════════

---

## `run.audit.wizard` (`wizards/run_audit_wizard.py`)

Orquesta el escaneo completo según el modo del proyecto. Contiene toda la lógica
de generación automática de findings y effort lines.

```python
from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools import config
import logging
import uuid

_logger = logging.getLogger(__name__)

# Horas base por categoría de módulo
EFFORT_MODULE = {
    'custom': (8.0, 20.0),    # (min, max) — el consultor elige en el rango
    'oca': (2.0, 4.0),
    'enterprise': (1.0, 2.0),
    'localization': (2.0, 6.0),
    'odoo_official': (0.0, 0.0),
    'unknown': (1.0, 3.0),
}
# Horas por campo custom
EFFORT_FIELD = {
    'studio': 1.0,
    'custom_dev': 2.0,
    'other_manual': 1.5,
}
# Horas por modelo custom completo
EFFORT_MODEL_BASE = 16.0
EFFORT_MODEL_PER_FIELD = 0.5  # adicional por cada campo propio
# Horas adicionales por volumen
EFFORT_VOLUME = {
    'low': 0.0,
    'medium': 4.0,
    'high': 10.0,
}
# Horas fijas de la propuesta
EFFORT_FIXED = [
    ('testing', 'Testing y validación post-migración', 8.0),
    ('training', 'Capacitación al equipo del cliente', 4.0),
    ('contingency', 'Contingencia (10%)', 0.0),  # se calcula como % del total
]


class RunAuditWizard(models.TransientModel):
    _name = 'run.audit.wizard'
    _description = 'Asistente de escaneo de auditoría'

    project_id = fields.Many2one('audit.project', required=True, readonly=True)
    audit_mode = fields.Selection(related='project_id.audit_mode', readonly=True)
    # Para Modo B: subida del archivo
    backup_file = fields.Binary(string='Archivo de backup')
    backup_filename = fields.Char(string='Nombre del archivo')
    # Opciones de escaneo
    scan_modules = fields.Boolean(default=True, string='Escanear módulos instalados')
    scan_fields = fields.Boolean(default=True, string='Escanear campos custom/Studio')
    scan_models = fields.Boolean(default=True, string='Escanear modelos custom')
    scan_volume = fields.Boolean(default=True, string='Escanear volumen de datos')
    generate_effort = fields.Boolean(
        default=True, string='Generar estimación de esfuerzo automáticamente'
    )
    # Log del proceso (readonly, se actualiza durante el escaneo)
    scan_log = fields.Text(readonly=True)
    scan_done = fields.Boolean(default=False)

    def action_scan(self):
        self.ensure_one()
        project = self.project_id
        log_lines = []

        def log(msg):
            log_lines.append(msg)
            _logger.info('[AuditScan] %s', msg)

        try:
            project.write({'state': 'scanning'})
            # Limpiar findings anteriores del proyecto
            project.module_finding_ids.unlink()
            project.field_finding_ids.unlink()
            project.model_finding_ids.unlink()
            project.volume_finding_ids.unlink()

            if project.audit_mode == 'xmlrpc':
                self._scan_xmlrpc(project, log)
            else:
                self._scan_backup(project, log)

            if self.generate_effort:
                self._generate_effort_lines(project, log)

            project.write({'state': 'done', 'scan_date': fields.Datetime.now()})
            log('✓ Escaneo completado.')

        except Exception as e:
            project.write({'state': 'error'})
            log(f'✗ Error durante el escaneo: {e}')
            import traceback
            log(traceback.format_exc())

        self.write({'scan_log': '\n'.join(log_lines), 'scan_done': True})
        # Reabrir el wizard con el log
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }

    # ── Modo A: XML-RPC ────────────────────────────────────────────────────

    def _scan_xmlrpc(self, project, log):
        from ..services.xmlrpc_client import OdooXmlRpcClient
        conn = project.connection_id
        if not conn:
            raise UserError('El proyecto no tiene credenciales XML-RPC configuradas.')

        log(f'Conectando a {conn.url} / {conn.database}...')
        client = OdooXmlRpcClient(conn.url, conn.database, conn.username, conn.password)

        version = client.get_server_version()
        project.write({
            'odoo_version_detected': version.get('server_version', ''),
        })
        log(f'Versión detectada: {version.get("server_version")}')

        if self.scan_modules:
            log('Escaneando módulos...')
            modules = client.get_installed_modules()
            self._create_module_findings(project, modules, log)

        if self.scan_fields:
            log('Escaneando campos custom...')
            fields_data = client.get_custom_fields()
            self._create_field_findings_xmlrpc(project, fields_data, client, log)

        if self.scan_models:
            log('Escaneando modelos custom...')
            models_data = client.get_custom_models()
            self._create_model_findings_xmlrpc(project, models_data, client, log)

        if self.scan_volume:
            log('Midiendo volumen de datos...')
            self._create_volume_findings_xmlrpc(project, client, log)

    # ── Modo B: Backup ─────────────────────────────────────────────────────

    def _scan_backup(self, project, log):
        from ..services.backup_processor import BackupProcessor, SCHEMA_PREFIX

        if not self.backup_file:
            raise UserError('Debes subir el archivo de backup antes de escanear.')

        import base64
        file_bytes = base64.b64decode(self.backup_file)
        filename = self.backup_filename or 'backup'

        log(f'Archivo recibido: {filename} ({len(file_bytes) / 1024 / 1024:.1f} MB)')

        # Detectar formato
        fmt = BackupProcessor.detect_format(filename, file_bytes)
        log(f'Formato detectado: {fmt}')

        # Crear registro audit.backup
        backup_rec = self.env['audit.backup'].create({
            'name': f'Backup — {project.client_name}',
            'backup_filename': filename,
            'backup_format': fmt,
            'state': 'processing',
        })
        project.write({'backup_id': backup_rec.id})

        # Generar nombre único de schema
        schema_name = f'{SCHEMA_PREFIX}{project.id}_{uuid.uuid4().hex[:8]}'
        backup_rec.write({'schema_name': schema_name})

        # Obtener DSN de la BD propia del Odoo del consultor
        dsn = self._get_own_dsn()
        processor = BackupProcessor(dsn, schema_name)

        try:
            processor.create_schema()
            log(f'Schema temporal creado: {schema_name}')

            # Extraer el dump según formato
            if fmt == 'zip_odoo':
                log('Extrayendo dump del zip...')
                dump_bytes, manifest = BackupProcessor.extract_dump_from_zip(file_bytes)
                log(f'Manifest: {manifest.get("odoo_version", "versión no encontrada")}')
                project.write({
                    'odoo_version_detected': manifest.get('odoo_version', ''),
                    'is_enterprise': 'enterprise' in str(manifest).lower(),
                })
                # Detectar si el dump es SQL o pg_custom
                inner_fmt = BackupProcessor.detect_format('dump', dump_bytes)
            else:
                dump_bytes = file_bytes
                inner_fmt = fmt

            # Importar según el tipo del dump
            if inner_fmt == 'pg_custom':
                log('Importando dump pg_custom (usando pg_restore)...')
                processor.import_pg_custom_dump(dump_bytes, log_callback=log)
            else:
                log('Importando dump SQL...')
                processor.import_sql_dump(dump_bytes, log_callback=log)

            # Detectar versión si no vino del manifest
            if not project.odoo_version_detected:
                ver = processor.get_odoo_version()
                project.write({'odoo_version_detected': ver})
                log(f'Versión Odoo detectada en dump: {ver}')

            backup_rec.write({'state': 'ready', 'processed_date': fields.Datetime.now()})

            # Ejecutar análisis usando el processor
            if self.scan_modules:
                log('Escaneando módulos...')
                modules = processor.get_installed_modules()
                self._create_module_findings(project, modules, log)

            if self.scan_fields:
                log('Escaneando campos custom...')
                fields_data = processor.get_custom_fields()
                self._create_field_findings_backup(project, fields_data, processor, log)

            if self.scan_models:
                log('Escaneando modelos custom...')
                models_data = processor.get_custom_models()
                self._create_model_findings_backup(project, models_data, processor, log)

            if self.scan_volume:
                log('Midiendo volumen de datos...')
                self._create_volume_findings_backup(project, processor, log)

        finally:
            # Siempre limpiar el schema temporal al terminar
            try:
                processor.drop_schema()
                backup_rec.write({'state': 'cleaned', 'schema_name': False})
                log(f'Schema temporal {schema_name} eliminado.')
            except Exception as e:
                log(f'[WARN] No se pudo eliminar el schema: {e}')
            processor.close()

    def _get_own_dsn(self):
        """
        Retorna el DSN de la base de datos propia del Odoo del consultor.
        Lee desde odoo.tools.config.
        """
        from odoo.tools import config
        db_host = config.get('db_host', 'localhost')
        db_port = config.get('db_port', 5432)
        db_user = config.get('db_user', 'odoo')
        db_password = config.get('db_password', '')
        db_name = self.env.cr.dbname  # nombre de la BD actual
        parts = [f'dbname={db_name}', f'user={db_user}', f'host={db_host}', f'port={db_port}']
        if db_password:
            parts.append(f'password={db_password}')
        return ' '.join(parts)

    # ── Creación de findings (compartido entre modos) ──────────────────────

    def _detect_module_category(self, mod):
        name = mod.get('name', '')
        author = (mod.get('author') or '').lower()
        ENTERPRISE = {
            'web_enterprise', 'account_reports', 'account_accountant',
            'sale_subscription', 'sale_renting', 'sign', 'documents',
            'quality_control', 'maintenance', 'helpdesk', 'studio',
            'social', 'marketing_automation', 'voip', 'whatsapp',
        }
        if name in ENTERPRISE:
            return 'enterprise'
        if name.startswith('l10n_'):
            return 'localization'
        if 'oca' in author or 'odoo community association' in author:
            return 'oca'
        if 'odoo s.a.' in author or 'odoo sa' in author:
            return 'odoo_official'
        OFFICIAL_PREFIXES = (
            'account', 'sale', 'purchase', 'stock', 'mrp', 'project',
            'hr', 'mail', 'web', 'base', 'bus', 'auth', 'calendar',
            'crm', 'lunch', 'fleet', 'point_of_sale', 'website',
            'payment', 'delivery', 'repair', 'survey',
        )
        if any(name.startswith(p) for p in OFFICIAL_PREFIXES):
            return 'odoo_official'
        return 'custom'

    def _create_module_findings(self, project, modules, log):
        for mod in modules:
            category = self._detect_module_category(mod)
            self.env['audit.module.finding'].create({
                'project_id': project.id,
                'name': mod['name'],
                'display_name_module': mod.get('shortdesc') or mod.get('display_name_module') or mod['name'],
                'author': mod.get('author') or '',
                'version': mod.get('installed_version') or '',
                'module_category': category,
            })
        log(f'  → {len(modules)} módulos registrados')

    def _detect_field_origin(self, field_name):
        if field_name.startswith('x_studio_'):
            return 'studio'
        if field_name.startswith('x_'):
            return 'custom_dev'
        return 'other_manual'

    def _create_field_findings_xmlrpc(self, project, fields_data, client, log):
        for f in fields_data:
            model_name = f.get('model_id') and f['model_id'][1] if isinstance(f.get('model_id'), list) else f.get('model_name', '')
            count = client.get_field_value_count(model_name, f['name']) if model_name else -1
            self.env['audit.field.finding'].create({
                'project_id': project.id,
                'name': f['name'],
                'field_description': f.get('field_description', ''),
                'model_name': model_name,
                'field_type': f.get('ttype', ''),
                'field_origin': self._detect_field_origin(f['name']),
                'has_data': count > 0,
                'record_count_with_value': max(count, 0),
            })
        log(f'  → {len(fields_data)} campos custom registrados')

    def _create_field_findings_backup(self, project, fields_data, processor, log):
        for f in fields_data:
            model_name = f.get('model_name', '')
            count = processor.get_field_value_count(model_name, f['name']) if model_name else -1
            self.env['audit.field.finding'].create({
                'project_id': project.id,
                'name': f['name'],
                'field_description': f.get('field_description', ''),
                'model_name': model_name,
                'field_type': f.get('ttype', ''),
                'field_origin': self._detect_field_origin(f['name']),
                'has_data': count > 0,
                'record_count_with_value': max(count, 0),
            })
        log(f'  → {len(fields_data)} campos custom registrados')

    def _create_model_findings_xmlrpc(self, project, models_data, client, log):
        for m in models_data:
            count = client.get_record_count(m['model'])
            self.env['audit.model.finding'].create({
                'project_id': project.id,
                'name': m['model'],
                'description': m.get('name') or m.get('info') or '',
                'field_count': len(m.get('field_id', [])),
                'record_count': max(count, 0),
            })
        log(f'  → {len(models_data)} modelos custom registrados')

    def _create_model_findings_backup(self, project, models_data, processor, log):
        for m in models_data:
            count = processor.get_record_count(m['model'])
            self.env['audit.model.finding'].create({
                'project_id': project.id,
                'name': m['model'],
                'description': m.get('name') or m.get('info') or '',
                'field_count': m.get('field_count', 0),
                'record_count': max(count, 0),
            })
        log(f'  → {len(models_data)} modelos custom registrados')

    def _volume_tier(self, count):
        if count < 0:
            return 'low'
        if count < 10000:
            return 'low'
        if count < 100000:
            return 'medium'
        return 'high'

    def _create_volume_findings_xmlrpc(self, project, client, log):
        from ..models.audit_volume_finding import VOLUME_MODELS
        for model_name, display in VOLUME_MODELS:
            count = client.get_record_count(model_name)
            if count < 0:
                continue
            tier = self._volume_tier(count)
            self.env['audit.volume.finding'].create({
                'project_id': project.id,
                'model_name': model_name,
                'display_name': display,
                'record_count': count,
                'volume_tier': tier,
                'effort_extra_hours': EFFORT_VOLUME[tier],
            })
        log('  → Volumen de datos registrado')

    def _create_volume_findings_backup(self, project, processor, log):
        from ..models.audit_volume_finding import VOLUME_MODELS
        for model_name, display in VOLUME_MODELS:
            if not processor.table_exists(model_name):
                continue
            count = processor.get_record_count(model_name)
            if count < 0:
                continue
            tier = self._volume_tier(count)
            self.env['audit.volume.finding'].create({
                'project_id': project.id,
                'model_name': model_name,
                'display_name': display,
                'record_count': count,
                'volume_tier': tier,
                'effort_extra_hours': EFFORT_VOLUME[tier],
            })
        log('  → Volumen de datos registrado')

    # ── Generación automática de effort lines ──────────────────────────────

    def _generate_effort_lines(self, project, log):
        # Limpiar effort lines anteriores de tipo 'auto'
        project.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()

        lines = []

        # 1. Por módulos relevantes
        for mod in project.module_finding_ids.filtered('is_relevant'):
            min_h, max_h = EFFORT_MODULE.get(mod.module_category, (1.0, 3.0))
            h = (min_h + max_h) / 2  # usar el promedio como punto de partida
            lines.append({
                'category': 'custom_module' if mod.module_category == 'custom' else 'oca_module',
                'description': f'Módulo: {mod.display_name_module or mod.name}',
                'estimated_hours': h,
                'reference': mod.name,
                'source': 'auto',
            })
            mod.write({'effort_hours': h})

        # 2. Por campos custom (agrupados por origen)
        studio_fields = project.field_finding_ids.filtered(
            lambda f: f.field_origin == 'studio'
        )
        custom_fields = project.field_finding_ids.filtered(
            lambda f: f.field_origin == 'custom_dev'
        )
        if studio_fields:
            total_h = len(studio_fields) * EFFORT_FIELD['studio']
            lines.append({
                'category': 'studio_fields',
                'description': f'Campos Studio (x_studio_*): {len(studio_fields)} campos',
                'estimated_hours': total_h,
                'reference': 'x_studio_*',
                'source': 'auto',
            })
        if custom_fields:
            total_h = len(custom_fields) * EFFORT_FIELD['custom_dev']
            lines.append({
                'category': 'studio_fields',
                'description': f'Campos custom (x_*): {len(custom_fields)} campos',
                'estimated_hours': total_h,
                'reference': 'x_*',
                'source': 'auto',
            })

        # 3. Por modelos custom completos
        for model in project.model_finding_ids:
            h = EFFORT_MODEL_BASE + (model.field_count * EFFORT_MODEL_PER_FIELD)
            lines.append({
                'category': 'custom_model',
                'description': f'Modelo custom: {model.name} ({model.field_count} campos, {model.record_count} registros)',
                'estimated_hours': h,
                'reference': model.name,
                'source': 'auto',
            })
            model.write({'effort_hours': h})

        # 4. Por volumen de datos
        volume_extra = sum(project.volume_finding_ids.mapped('effort_extra_hours'))
        if volume_extra > 0:
            lines.append({
                'category': 'data_volume',
                'description': f'Optimización ETL por volumen de datos',
                'estimated_hours': volume_extra,
                'reference': 'volumen',
                'source': 'auto',
            })

        # 5. Líneas fijas: testing, training
        for category, desc, hours in EFFORT_FIXED[:2]:
            lines.append({
                'category': category,
                'description': desc,
                'estimated_hours': hours,
                'source': 'auto',
            })

        # 6. Contingencia: 10% del subtotal
        subtotal = sum(l['estimated_hours'] for l in lines)
        contingency = round(subtotal * 0.10, 1)
        lines.append({
            'category': 'contingency',
            'description': f'Contingencia 10% ({subtotal:.1f}h base)',
            'estimated_hours': contingency,
            'source': 'auto',
        })

        # Crear todas las líneas
        seq = 10
        for line_vals in lines:
            self.env['audit.effort.line'].create({
                'project_id': project.id,
                'sequence': seq,
                **line_vals,
            })
            seq += 10

        log(f'  → {len(lines)} líneas de esfuerzo generadas. Total: {subtotal + contingency:.1f}h')
```

---

## `generate.report.wizard` (`wizards/generate_report_wizard.py`)

```python
from odoo import models, fields, api


class GenerateReportWizard(models.TransientModel):
    _name = 'generate.report.wizard'
    _description = 'Generar informe de auditoría'

    project_id = fields.Many2one('audit.project', required=True, readonly=True)
    report_type = fields.Selection([
        ('executive', 'Resumen ejecutivo (para el cliente)'),
        ('technical', 'Informe técnico completo'),
        ('budget', 'Solo presupuesto'),
    ], default='executive', string='Tipo de informe')
    include_modules = fields.Boolean(default=True, string='Incluir inventario de módulos')
    include_fields = fields.Boolean(default=True, string='Incluir campos custom')
    include_models = fields.Boolean(default=False, string='Incluir modelos custom')
    include_volume = fields.Boolean(default=True, string='Incluir volumen de datos')
    include_effort = fields.Boolean(default=True, string='Incluir estimación de horas')

    def action_generate_pdf(self):
        self.ensure_one()
        return self.env.ref('migration_auditor.action_audit_report').report_action(
            self.project_id,
            data={
                'report_type': self.report_type,
                'include_modules': self.include_modules,
                'include_fields': self.include_fields,
                'include_models': self.include_models,
                'include_volume': self.include_volume,
                'include_effort': self.include_effort,
            }
        )
```

---

## Reporte QWeb (`report/audit_report_template.xml`)

```xml
<odoo>
    <template id="audit_report_document">
        <t t-call="web.html_container">
            <t t-foreach="docs" t-as="project">
                <t t-call="web.external_layout">
                    <div class="page">

                        <!-- Encabezado -->
                        <div class="row mb-4">
                            <div class="col-12">
                                <h2>Informe de Auditoría — Migración Odoo</h2>
                                <h4 t-esc="project.client_name"/>
                                <p>
                                    Versión origen detectada:
                                    <strong t-esc="project.odoo_version_detected or 'No detectada'"/>
                                    → Versión destino:
                                    <strong t-esc="project.target_version"/>
                                </p>
                                <p>
                                    Fecha del análisis:
                                    <span t-esc="project.scan_date" t-options='{"widget": "date"}'/>
                                </p>
                            </div>
                        </div>

                        <!-- Resumen ejecutivo -->
                        <t t-if="project.executive_summary">
                            <h3>Resumen ejecutivo</h3>
                            <p t-esc="project.executive_summary"/>
                            <div class="page_break"/>
                        </t>

                        <!-- Módulos instalados -->
                        <t t-if="doc_data.get('include_modules')">
                            <h3>Módulos instalados relevantes para la migración</h3>
                            <table class="table table-sm table-bordered">
                                <thead class="thead-light">
                                    <tr>
                                        <th>Módulo</th>
                                        <th>Categoría</th>
                                        <th>Versión</th>
                                        <th>Autor</th>
                                        <th>Horas estimadas</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="project.module_finding_ids.filtered(lambda m: m.is_relevant)" t-as="mod">
                                        <tr>
                                            <td><t t-esc="mod.display_name_module"/></td>
                                            <td><t t-esc="mod.module_category"/></td>
                                            <td><t t-esc="mod.version"/></td>
                                            <td><t t-esc="mod.author"/></td>
                                            <td><t t-esc="mod.effort_hours"/></td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </t>

                        <!-- Campos custom -->
                        <t t-if="doc_data.get('include_fields') and project.field_finding_ids">
                            <h3>Campos personalizados detectados</h3>
                            <table class="table table-sm table-bordered">
                                <thead class="thead-light">
                                    <tr>
                                        <th>Campo</th>
                                        <th>Modelo</th>
                                        <th>Tipo</th>
                                        <th>Origen</th>
                                        <th>Con datos</th>
                                        <th>Decisión</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="project.field_finding_ids" t-as="f">
                                        <tr>
                                            <td><t t-esc="f.name"/><br/><small t-esc="f.field_description"/></td>
                                            <td><t t-esc="f.model_name"/></td>
                                            <td><t t-esc="f.field_type"/></td>
                                            <td><t t-esc="f.field_origin"/></td>
                                            <td><t t-esc="'Sí' if f.has_data else 'No'"/></td>
                                            <td><t t-esc="f.migration_decision or 'Pendiente'"/></td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </t>

                        <!-- Volumen de datos -->
                        <t t-if="doc_data.get('include_volume') and project.volume_finding_ids">
                            <h3>Volumen de datos</h3>
                            <table class="table table-sm table-bordered">
                                <thead class="thead-light">
                                    <tr>
                                        <th>Modelo</th>
                                        <th>Registros</th>
                                        <th>Volumen</th>
                                        <th>Horas adicionales</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="project.volume_finding_ids" t-as="v">
                                        <tr>
                                            <td><t t-esc="v.display_name"/></td>
                                            <td><t t-esc="v.record_count"/></td>
                                            <td><t t-esc="v.volume_tier"/></td>
                                            <td><t t-esc="v.effort_extra_hours"/></td>
                                        </tr>
                                    </t>
                                </tbody>
                            </table>
                        </t>

                        <!-- Presupuesto -->
                        <t t-if="doc_data.get('include_effort') and project.effort_line_ids">
                            <div class="page_break"/>
                            <h3>Estimación de esfuerzo y presupuesto</h3>
                            <table class="table table-sm table-bordered">
                                <thead class="thead-light">
                                    <tr>
                                        <th>Categoría</th>
                                        <th>Descripción</th>
                                        <th class="text-right">Horas</th>
                                        <th class="text-right">Subtotal</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <t t-foreach="project.effort_line_ids" t-as="line">
                                        <tr>
                                            <td><t t-esc="line.category"/></td>
                                            <td><t t-esc="line.description"/></td>
                                            <td class="text-right"><t t-esc="line.estimated_hours"/></td>
                                            <td class="text-right">
                                                <t t-esc="line.subtotal"
                                                   t-options='{"widget": "monetary", "display_currency": project.currency_id}'/>
                                            </td>
                                        </tr>
                                    </t>
                                </tbody>
                                <tfoot>
                                    <tr class="font-weight-bold">
                                        <td colspan="2">TOTAL</td>
                                        <td class="text-right"><t t-esc="project.total_hours"/>h</td>
                                        <td class="text-right">
                                            <t t-esc="project.total_cost"
                                               t-options='{"widget": "monetary", "display_currency": project.currency_id}'/>
                                        </td>
                                    </tr>
                                </tfoot>
                            </table>
                            <p class="text-muted" style="font-size:11px;">
                                * Las horas son estimaciones basadas en el análisis técnico automatizado.
                                El consultor puede ajustarlas según criterio profesional.
                            </p>
                        </t>

                        <!-- Notas del consultor -->
                        <t t-if="project.consultant_notes">
                            <h3>Notas técnicas del consultor</h3>
                            <p t-esc="project.consultant_notes"/>
                        </t>

                    </div>
                </t>
            </t>
        </t>
    </template>

    <record id="action_audit_report" model="ir.actions.report">
        <field name="name">Informe de auditoría de migración</field>
        <field name="model">audit.project</field>
        <field name="report_type">qweb-pdf</field>
        <field name="report_name">migration_auditor.audit_report_document</field>
        <field name="report_file">migration_auditor.audit_report_document</field>
        <field name="binding_model_id" ref="model_audit_project"/>
        <field name="binding_type">report</field>
    </record>
</odoo>
```

---

## Seguridad

### `security/auditor_security.xml`

```xml
<odoo>
    <data>
        <record id="module_category_auditor" model="ir.module.category">
            <field name="name">Migration Auditor</field>
            <field name="sequence">81</field>
        </record>
        <record id="group_auditor_user" model="res.groups">
            <field name="name">Auditor</field>
            <field name="category_id" ref="module_category_auditor"/>
        </record>
    </data>
</odoo>
```

### `ir.model.access.csv`

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_audit_project,audit.project,model_audit_project,group_auditor_user,1,1,1,1
access_audit_connection,audit.connection,model_audit_connection,group_auditor_user,1,1,1,1
access_audit_backup,audit.backup,model_audit_backup,group_auditor_user,1,1,1,1
access_audit_module_finding,audit.module.finding,model_audit_module_finding,group_auditor_user,1,1,1,1
access_audit_field_finding,audit.field.finding,model_audit_field_finding,group_auditor_user,1,1,1,1
access_audit_model_finding,audit.model.finding,model_audit_model_finding,group_auditor_user,1,1,1,1
access_audit_volume_finding,audit.volume.finding,model_audit_volume_finding,group_auditor_user,1,1,1,1
access_audit_effort_line,audit.effort.line,model_audit_effort_line,group_auditor_user,1,1,1,1
access_run_audit_wizard,run.audit.wizard,model_run_audit_wizard,group_auditor_user,1,1,1,1
access_generate_report_wizard,generate.report.wizard,model_generate_report_wizard,group_auditor_user,1,1,1,1
```

---

## Menús (`views/menus.xml`)

```xml
<odoo>
    <data>
        <menuitem id="menu_auditor_root" name="Migration Auditor" sequence="81"/>

        <menuitem id="menu_audit_projects" name="Proyectos de auditoría"
                  parent="menu_auditor_root"
                  action="action_audit_project" sequence="10"/>

        <menuitem id="menu_audit_connections" name="Conexiones XML-RPC"
                  parent="menu_auditor_root"
                  action="action_audit_connection" sequence="20"/>
    </data>
</odoo>
```

---

## Consideraciones técnicas críticas

### 1. Schemas temporales — nunca bases de datos separadas

El `BackupProcessor` trabaja con schemas dentro de la misma BD del Odoo del consultor.
Ventajas: no requiere permisos de `CREATE DATABASE`, no necesita conexión adicional,
limpieza garantizada con `DROP SCHEMA CASCADE`. El schema temporal se elimina siempre
en el bloque `finally`, incluso si el análisis falla a mitad de camino.

### 2. `pg_restore` debe estar disponible en el servidor

Para dumps en formato `pg_custom` (el más común de backups Odoo 16+) se requiere que
el binario `pg_restore` esté en el PATH del proceso Odoo del servidor del consultor.
En instalaciones estándar con PostgreSQL esto está disponible. Si no, agregar manejo
de error claro: `"El formato pg_custom requiere pg_restore instalado en el servidor."`

### 3. Seguridad de credenciales XML-RPC

El campo `password` en `audit.connection` debe usar `password=True` en la definición
del campo para que Odoo lo enmascare en la UI. En la BD se almacena en texto plano
(comportamiento estándar de Odoo) — es aceptable para uso interno del consultor.

### 4. Tamaño del campo `backup_file`

Los backups de Odoo pueden ser grandes (varios GB). El campo `Binary` en Odoo usa
`ir.attachment` internamente con `attachment=True`. Asegurarse de configurar en el
campo: `attachment=True` para que no se guarde en memoria sino en el filestore.

```python
backup_file = fields.Binary(string='Archivo de backup', attachment=True)
```

### 5. Importación SQL parcialmente tolerante a errores

El método `import_sql_dump` ejecuta statement por statement y hace rollback individual
por statement fallido, luego continúa. Esto es intencional: los dumps de Odoo incluyen
sentencias de extensiones y roles que no aplican a un schema temporal. Los primeros 10
errores se loguean; el resto se silencian para no saturar el log.

### 6. Timeout en XML-RPC

Agregar timeout a las conexiones XML-RPC para evitar que el wizard cuelgue si el
servidor del cliente no responde:

```python
import xmlrpc.client
import socket
socket.setdefaulttimeout(30)  # 30 segundos máximo por llamada
```

Llamar esto al inicio de `OdooXmlRpcClient.__init__`.

### 7. `psycopg2` como dependencia externa

Odoo ya tiene `psycopg2` como dependencia propia — no es necesario instalarlo
separadamente. Está disponible en el entorno Python de cualquier instancia Odoo 17.

---

## Flujo de trabajo completo

```
Cliente contacta al consultor
          ↓
Migration Auditor > Nuevo proyecto
  - Nombre del cliente
  - Versión origen / destino
  - Modo: XML-RPC o Backup
          ↓
┌─────────────────────────────────────────┐
│  MODO XML-RPC                           │
│  Crear audit.connection con URL +       │
│  credenciales → "Probar conexión"       │
└─────────────────────────────────────────┘
          ↓                ↓
┌─────────────────────────────────────────┐
│  MODO BACKUP                            │
│  Cliente envía .zip o .sql/.dump        │
│  El consultor lo sube en el wizard      │
└─────────────────────────────────────────┘
          ↓
"Ejecutar diagnóstico" → wizard
  - Seleccionar qué escanear
  - Para Backup: subir el archivo aquí
  - El sistema detecta formato automáticamente
  - Escaneo en background con log en tiempo real
          ↓
Proyecto en estado "done"
  - Inventario de módulos con categorías
  - Campos custom/Studio con conteo de datos
  - Modelos custom con volumen
  - Líneas de esfuerzo autogeneradas
          ↓
Revisar y ajustar manualmente:
  - Horas de cada módulo (rango auto, ajustar a criterio)
  - Decisión de migración por campo (migrate/drop/recreate)
  - Resumen ejecutivo editable
  - Tarifa hora del consultor
          ↓
"Generar informe" → wizard
  - Tipo: ejecutivo / técnico / solo presupuesto
  - Seleccionar secciones a incluir
  - Generar PDF
          ↓
Enviar propuesta al cliente
```
