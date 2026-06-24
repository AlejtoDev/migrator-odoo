from odoo import models, fields, api


class AuditBackup(models.Model):
    _name = 'audit.backup'
    _description = 'Backup de Odoo del cliente para análisis'
    _order = 'id desc'

    name = fields.Char(string='Descripción', required=True)
    backup_file = fields.Binary(string='Archivo de backup', attachment=True)
    backup_filename = fields.Char(string='Nombre del archivo')
    backup_format = fields.Selection([
        ('zip_odoo', 'ZIP nativo de Odoo'),
        ('sql_plain', 'SQL plano (.sql / .dump)'),
        ('pg_custom', 'PostgreSQL custom format'),
    ], string='Formato detectado', readonly=True)
    file_size_mb = fields.Float(string='Tamaño (MB)', compute='_compute_size')
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('processing', 'Procesando'),
        ('ready', 'Listo'),
        ('error', 'Error'),
        ('cleaned', 'Schema eliminado'),
    ], string='Estado', default='pending')
    schema_name = fields.Char(string='Schema temporal', readonly=True)
    processing_log = fields.Text(string='Log de procesamiento', readonly=True)
    odoo_version_detected = fields.Char(string='Versión Odoo detectada', readonly=True)
    processed_date = fields.Datetime(string='Procesado el', readonly=True)

    @api.depends('backup_file')
    def _compute_size(self):
        for rec in self:
            if rec.backup_file:
                import base64
                try:
                    data = base64.b64decode(rec.backup_file)
                    rec.file_size_mb = len(data) / (1024 * 1024)
                except Exception:
                    rec.file_size_mb = 0.0
            else:
                rec.file_size_mb = 0.0

    def action_clean_schema(self):
        self.ensure_one()
        if not self.schema_name:
            return
        from ..services.backup_processor import BackupProcessor
        from odoo.tools import config
        db_host = config.get('db_host', 'localhost')
        db_port = config.get('db_port', 5432)
        db_user = config.get('db_user', 'odoo')
        db_password = config.get('db_password', '')
        db_name = self.env.cr.dbname
        parts = [f'dbname={db_name}', f'user={db_user}', f'host={db_host}', f'port={db_port}']
        if db_password:
            parts.append(f'password={db_password}')
        dsn = ' '.join(parts)
        processor = BackupProcessor(dsn, self.schema_name)
        try:
            processor.drop_schema()
            self.write({'state': 'cleaned', 'schema_name': False})
        finally:
            processor.close()
