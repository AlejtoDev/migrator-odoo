import os
import re
import json
import zipfile
import tempfile
import logging
import psycopg2
from psycopg2 import sql as pgsql

_logger = logging.getLogger(__name__)

SCHEMA_PREFIX = 'audit_tmp_'


class BackupProcessor:
    """
    Procesa backups de Odoo (zip nativo o dump SQL/pg_custom).
    Trabaja con schemas dentro de la misma base de datos del Odoo del consultor.
    NUNCA crea bases de datos separadas.
    """

    def __init__(self, db_connection_string, schema_name):
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
        name_lower = filename.lower()
        magic = file_bytes[:8] if len(file_bytes) >= 8 else file_bytes

        if name_lower.endswith('.zip') or magic[:2] == b'PK':
            return 'zip_odoo'

        if magic[:5] == b'PGDMP':
            return 'pg_custom'

        try:
            head = file_bytes[:200].decode('utf-8', errors='ignore').strip()
            if head.startswith('--') or head.upper().startswith(('SET ', 'CREATE ', 'BEGIN')):
                return 'sql_plain'
        except Exception:
            pass

        if name_lower.endswith('.sql'):
            return 'sql_plain'

        return 'sql_plain'

    # ── Extracción del dump ────────────────────────────────────────────────

    @staticmethod
    def extract_dump_from_zip(zip_bytes):
        import io
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            manifest = {}
            if 'manifest.json' in names:
                manifest = json.loads(zf.read('manifest.json'))

            dump_name = next(
                (n for n in names if re.match(r'dump(\.(sql|pg))?$', n)),
                None
            )
            if not dump_name:
                raise ValueError(
                    f'No se encontró el archivo dump dentro del zip. '
                    f'Archivos encontrados: {names}'
                )
            return zf.read(dump_name), manifest

    # ── Schema temporal ────────────────────────────────────────────────────

    def create_schema(self):
        conn = self._get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                pgsql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(
                    pgsql.Identifier(self.schema)
                )
            )
        _logger.info('BackupProcessor: schema %s creado', self.schema)

    def drop_schema(self):
        conn = self._get_conn()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                pgsql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(
                    pgsql.Identifier(self.schema)
                )
            )
        _logger.info('BackupProcessor: schema %s eliminado', self.schema)

    def import_sql_dump(self, sql_bytes, log_callback=None):
        conn = self._get_conn()
        conn.autocommit = False

        def log(msg):
            _logger.info(msg)
            if log_callback:
                log_callback(msg)

        try:
            sql_text = sql_bytes.decode('utf-8', errors='replace')
            with conn.cursor() as cur:
                cur.execute(
                    pgsql.SQL('SET search_path TO {}, public').format(
                        pgsql.Identifier(self.schema)
                    )
                )
                statements = self._split_sql(sql_text)
                total = len(statements)
                errors = 0

                for i, stmt in enumerate(statements):
                    stmt = stmt.strip()
                    if not stmt or self._should_skip(stmt):
                        continue
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        errors += 1
                        conn.rollback()
                        cur.execute(
                            pgsql.SQL('SET search_path TO {}, public').format(
                                pgsql.Identifier(self.schema)
                            )
                        )
                        if errors <= 10:
                            log(f'[WARN stmt {i}/{total}] {str(e)[:200]}')

            conn.commit()
            log(f'Importación completada. {total} statements, {errors} errores omitidos.')

        except Exception as e:
            conn.rollback()
            raise RuntimeError(f'Error importando dump SQL: {e}') from e

    def import_pg_custom_dump(self, dump_bytes, log_callback=None):
        import subprocess

        def log(msg):
            _logger.info(msg)
            if log_callback:
                log_callback(msg)

        with tempfile.NamedTemporaryFile(suffix='.dump', delete=False) as tmp:
            tmp.write(dump_bytes)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ['pg_restore', '--no-owner', '--no-acl', '-f', '-', tmp_path],
                capture_output=True,
                timeout=300,
            )
            if result.returncode != 0 and not result.stdout:
                raise RuntimeError(f'pg_restore falló: {result.stderr.decode()[:500]}')
            log(f'pg_restore extrajo {len(result.stdout)} bytes de SQL')
            self.import_sql_dump(result.stdout, log_callback)
        finally:
            os.unlink(tmp_path)

    @staticmethod
    def _split_sql(sql_text):
        statements = []
        current = []
        in_dollar_quote = False
        dollar_tag = ''

        for line in sql_text.split('\n'):
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
        stmt_upper = stmt.upper().lstrip()
        SKIP_PREFIXES = (
            'CREATE EXTENSION', 'COMMENT ON EXTENSION',
            'CREATE ROLE', 'ALTER ROLE', 'CREATE USER', 'ALTER USER',
            'GRANT ', 'REVOKE ',
            'SET DEFAULT_TABLESPACE', 'SET CLIENT_ENCODING',
            'SET STANDARD_CONFORMING', 'SET CHECK_FUNCTION_BODIES',
            'SET CLIENT_MIN_MESSAGES', 'SET ROW_SECURITY',
            'SELECT PG_CATALOG', 'ALTER DATABASE',
        )
        return any(stmt_upper.startswith(p) for p in SKIP_PREFIXES)

    # ── Queries de análisis ────────────────────────────────────────────────

    def query(self, sql, params=None):
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                pgsql.SQL('SET search_path TO {}, public').format(
                    pgsql.Identifier(self.schema)
                )
            )
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
            SELECT f.name, f.field_description, m.model AS model_name, f.ttype, f.state
            FROM ir_model_fields f
            JOIN ir_model m ON m.id = f.model_id
            WHERE f.state = 'manual'
            ORDER BY m.model, f.name
        """)

    def get_custom_models(self):
        return self.query("""
            SELECT m.model, m.name, m.info, COUNT(f.id) AS field_count
            FROM ir_model m
            LEFT JOIN ir_model_fields f ON f.model_id = m.id AND f.state = 'base'
            WHERE m.state = 'manual'
            GROUP BY m.id, m.model, m.name, m.info
            ORDER BY m.model
        """)

    def get_record_count(self, table_name):
        sql_table = table_name.replace('.', '_')
        try:
            result = self._query_composed(
                pgsql.SQL('SELECT COUNT(*) AS cnt FROM {}').format(
                    pgsql.Identifier(sql_table)
                )
            )
            return result[0]['cnt'] if result else 0
        except Exception:
            return -1

    def get_field_value_count(self, table_name, field_name):
        sql_table = table_name.replace('.', '_')
        try:
            result = self._query_composed(
                pgsql.SQL(
                    "SELECT COUNT(*) AS cnt FROM {} "
                    "WHERE {} IS NOT NULL "
                    "AND {}::text NOT IN ('', '0', 'false')"
                ).format(
                    pgsql.Identifier(sql_table),
                    pgsql.Identifier(field_name),
                    pgsql.Identifier(field_name),
                )
            )
            return result[0]['cnt'] if result else 0
        except Exception:
            return -1

    def _query_composed(self, composed):
        """Ejecuta una `psycopg2.sql.Composed` con el search_path del schema."""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                pgsql.SQL('SET search_path TO {}, public').format(
                    pgsql.Identifier(self.schema)
                )
            )
            cur.execute(composed)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_odoo_version(self):
        try:
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
