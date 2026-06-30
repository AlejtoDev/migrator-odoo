import xmlrpc.client
import logging

_logger = logging.getLogger(__name__)

_TIMEOUT = 30


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout=_TIMEOUT):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout=_TIMEOUT):
        super().__init__()
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


def _make_transport(url, timeout=_TIMEOUT):
    cls = _TimeoutSafeTransport if url.startswith('https') else _TimeoutTransport
    return cls(timeout=timeout)


class OdooXmlRpcClient:
    """Wrapper sobre el XML-RPC de Odoo para auditoría remota."""

    def __init__(self, url, database, username, password):
        self.url = url.rstrip('/')
        self.database = database
        self.username = username
        self.password = password
        self._uid = None
        self._authenticate()

    def _proxy(self, path):
        return xmlrpc.client.ServerProxy(
            f'{self.url}{path}',
            transport=_make_transport(self.url),
        )

    def _authenticate(self):
        common = self._proxy('/xmlrpc/2/common')
        self._uid = common.authenticate(
            self.database, self.username, self.password, {}
        )
        if not self._uid:
            raise ConnectionError(
                f'Autenticación fallida para {self.username}@{self.database}'
            )

    def get_server_version(self):
        return self._proxy('/xmlrpc/2/common').version()

    def execute(self, model, method, domain=None, fields=None, **kwargs):
        models_proxy = self._proxy('/xmlrpc/2/object')
        args = [domain or []]
        if fields:
            kwargs['fields'] = fields
        return models_proxy.execute_kw(
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
        return self.search_read(
            'ir.model.fields',
            domain=[('state', '=', 'manual')],
            fields=['name', 'field_description', 'model_id', 'ttype', 'state'],
        )

    def get_custom_models(self, custom_module_names=None):
        # Modelos creados desde UI/Studio (state='manual')
        manual = self.search_read(
            'ir.model',
            domain=[('state', '=', 'manual')],
            fields=['name', 'model', 'field_id', 'info'],
        )
        result = {m['id']: m for m in manual}

        # Modelos definidos en módulos custom Python (state='base')
        if custom_module_names:
            refs = self.search_read(
                'ir.model.data',
                domain=[
                    ('model', '=', 'ir.model'),
                    ('module', 'in', list(custom_module_names)),
                ],
                fields=['res_id'],
            )
            extra_ids = [r['res_id'] for r in refs if r['res_id'] not in result]
            if extra_ids:
                py_models = self.search_read(
                    'ir.model',
                    domain=[('id', 'in', extra_ids)],
                    fields=['name', 'model', 'field_id', 'info'],
                )
                for m in py_models:
                    result[m['id']] = m

        return list(result.values())

    def get_own_field_counts_by_model(self, custom_module_names):
        """Devuelve {model_id: n} con solo los campos definidos en los módulos custom (no heredados)."""
        if not custom_module_names:
            return {}
        refs = self.search_read(
            'ir.model.data',
            domain=[('model', '=', 'ir.model.fields'), ('module', 'in', list(custom_module_names))],
            fields=['res_id'],
            limit=0,
        )
        if not refs:
            return {}
        field_ids = [r['res_id'] for r in refs]
        fields_info = self.search_read(
            'ir.model.fields',
            domain=[('id', 'in', field_ids)],
            fields=['model_id'],
            limit=0,
        )
        counts = {}
        for fd in fields_info:
            mid = fd['model_id'][0] if isinstance(fd['model_id'], list) else fd['model_id']
            counts[mid] = counts.get(mid, 0) + 1
        return counts

    def get_record_count(self, model_name):
        try:
            return self.search_count(model_name)
        except Exception:
            return -1

    def get_field_value_count(self, model_name, field_name):
        try:
            return self.search_count(
                model_name,
                domain=[(field_name, 'not in', [False, '', 0])]
            )
        except Exception:
            return -1
