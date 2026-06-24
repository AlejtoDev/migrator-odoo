import socket
from odoo import models, fields
from odoo.exceptions import UserError


class AuditConnection(models.Model):
    _name = 'audit.connection'
    _description = 'Credenciales de conexión XML-RPC al Odoo del cliente'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True)
    url = fields.Char(string='URL del Odoo', required=True,
                      help='Ej: https://cliente.odoo.com')
    database = fields.Char(string='Base de datos', required=True)
    username = fields.Char(string='Usuario', required=True)
    password = fields.Char(string='Contraseña', password=True)
    last_test_date = fields.Datetime(string='Última prueba')
    last_test_result = fields.Selection([
        ('ok', 'OK'),
        ('error', 'Error'),
    ], string='Resultado', readonly=True)
    last_test_detail = fields.Char(string='Detalle del test', readonly=True)
    odoo_version = fields.Char(string='Versión detectada', readonly=True)
    notes = fields.Text(string='Notas')

    def action_test_connection(self):
        self.ensure_one()
        from ..services.xmlrpc_client import OdooXmlRpcClient
        try:
            client = OdooXmlRpcClient(self.url, self.database, self.username, self.password)
            version = client.get_server_version()
            ver = version.get('server_version', 'desconocida')
            self.write({
                'last_test_date': fields.Datetime.now(),
                'odoo_version': ver,
                'last_test_result': 'ok',
                'last_test_detail': f'Odoo {ver}',
            })
            return self._notify_success(f"Conexión exitosa — Odoo {ver}")
        except Exception as e:
            self.write({
                'last_test_date': fields.Datetime.now(),
                'last_test_result': 'error',
                'last_test_detail': str(e)[:200],
            })
            raise UserError(f'No se pudo conectar: {e}')

    def _notify_success(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Conexión exitosa',
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }
