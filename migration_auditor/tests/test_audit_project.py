from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestAuditProject(TransactionCase):
    """Tests del modelo audit.project — ciclo de vida y configuración."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.Project = cls.env['audit.project']

    def _create_project(self, audit_mode='xmlrpc', **kwargs):
        vals = {
            'name': 'AUDIT/TEST/0001',
            'client_name': 'Cliente de Prueba S.A.',
            'audit_mode': audit_mode,
        }
        vals.update(kwargs)
        return self.Project.create(vals)

    # ── CREATE ────────────────────────────────────────────────────────────

    def test_create_project_minimal(self):
        project = self._create_project()
        self.assertTrue(project.id)
        self.assertEqual(project.state, 'draft')
        self.assertEqual(project.audit_mode, 'xmlrpc')

    def test_create_project_backup_mode(self):
        project = self._create_project(audit_mode='backup')
        self.assertEqual(project.audit_mode, 'backup')

    def test_project_requires_client_name(self):
        with self.assertRaises(Exception):
            self.Project.create({
                'name': 'No Client',
                'audit_mode': 'xmlrpc',
            })

    # ── STATE MACHINE ─────────────────────────────────────────────────────

    def test_action_reset_draft_clears_findings(self):
        project = self._create_project()
        self.env['audit.module.finding'].create({
            'project_id': project.id,
            'name': 'test_module',
            'module_category': 'custom',
        })
        project.write({'state': 'done'})
        self.assertEqual(len(project.module_finding_ids), 1)
        project.action_reset_draft()
        self.assertEqual(project.state, 'draft')
        self.assertEqual(len(project.module_finding_ids), 0)

    def test_action_reset_draft_removes_auto_effort_only(self):
        """action_reset_draft solo elimina effort lines automáticas, no las manuales."""
        project = self._create_project()
        auto_line = self.env['audit.effort.line'].create({
            'project_id': project.id,
            'category': 'custom_module',
            'description': 'Auto generada',
            'estimated_hours': 8.0,
            'source': 'auto',
        })
        manual_line = self.env['audit.effort.line'].create({
            'project_id': project.id,
            'category': 'other',
            'description': 'Manual',
            'estimated_hours': 2.0,
            'source': 'manual',
        })
        project.write({'state': 'done'})
        project.action_reset_draft()
        remaining = project.effort_line_ids
        self.assertNotIn(auto_line, remaining)
        self.assertIn(manual_line, remaining)

    # ── SMART BUTTONS ─────────────────────────────────────────────────────

    def test_module_count_compute(self):
        project = self._create_project()
        self.assertEqual(project.module_count, 0)
        self.env['audit.module.finding'].create([
            {'project_id': project.id, 'name': f'mod_{i}', 'module_category': 'custom'}
            for i in range(3)
        ])
        self.assertEqual(project.module_count, 3)

    def test_field_count_compute(self):
        project = self._create_project()
        self.assertEqual(project.field_count, 0)
        self.env['audit.field.finding'].create({
            'project_id': project.id,
            'name': 'x_studio_test',
            'model_name': 'res.partner',
            'field_origin': 'studio',
        })
        self.assertEqual(project.field_count, 1)

    def test_model_count_compute(self):
        project = self._create_project()
        self.assertEqual(project.model_count, 0)
        self.env['audit.model.finding'].create({
            'project_id': project.id,
            'name': 'x_custom_model',
        })
        self.assertEqual(project.model_count, 1)

    # ── PRESUPUESTO ───────────────────────────────────────────────────────

    def test_total_hours_compute(self):
        project = self._create_project(hourly_rate=50.0)
        self.env['audit.effort.line'].create([
            {'project_id': project.id, 'category': 'custom_module',
             'description': 'M1', 'estimated_hours': 10.0, 'source': 'auto'},
            {'project_id': project.id, 'category': 'testing',
             'description': 'T1', 'estimated_hours': 5.0, 'source': 'auto'},
        ])
        self.assertAlmostEqual(project.total_hours, 15.0, places=2)

    def test_total_cost_compute(self):
        project = self._create_project(hourly_rate=100.0)
        self.env['audit.effort.line'].create({
            'project_id': project.id,
            'category': 'custom_module',
            'description': 'Module work',
            'estimated_hours': 20.0,
            'source': 'auto',
        })
        self.assertAlmostEqual(project.total_cost, 2000.0, places=2)

    def test_total_cost_zero_when_no_lines(self):
        project = self._create_project(hourly_rate=100.0)
        self.assertAlmostEqual(project.total_cost, 0.0, places=2)

    # ── ACTIONS ───────────────────────────────────────────────────────────

    def test_action_run_audit_returns_wizard(self):
        project = self._create_project()
        action = project.action_run_audit()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'run.audit.wizard')
        self.assertEqual(action['target'], 'new')

    def test_action_generate_report_returns_wizard(self):
        project = self._create_project()
        project.write({'state': 'done'})
        action = project.action_generate_report()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'generate.report.wizard')

    def test_action_view_modules(self):
        project = self._create_project()
        action = project.action_view_modules()
        self.assertEqual(action['res_model'], 'audit.module.finding')
        self.assertIn(('project_id', '=', project.id), action['domain'])

    def test_action_view_fields(self):
        project = self._create_project()
        action = project.action_view_fields()
        self.assertEqual(action['res_model'], 'audit.field.finding')

    def test_action_view_models(self):
        project = self._create_project()
        action = project.action_view_models()
        self.assertEqual(action['res_model'], 'audit.model.finding')


@tagged('post_install', '-at_install')
class TestAuditConnection(TransactionCase):
    """Tests del modelo audit.connection — credenciales XML-RPC."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})

    def test_create_connection(self):
        conn = self.env['audit.connection'].create({
            'name': 'Test Connection',
            'url': 'https://test.odoo.com',
            'database': 'test_db',
            'username': 'admin',
            'password': 'admin',
        })
        self.assertTrue(conn.id)
        self.assertIsNone(conn.last_test_result or None)

    def test_connection_last_test_result_selection(self):
        conn = self.env['audit.connection'].create({
            'name': 'Conn Result Test',
            'url': 'https://test.odoo.com',
            'database': 'test_db',
            'username': 'admin',
            'password': 'test',
        })
        conn.write({'last_test_result': 'ok', 'last_test_detail': 'Odoo 17.0'})
        self.assertEqual(conn.last_test_result, 'ok')
        conn.write({'last_test_result': 'error', 'last_test_detail': 'Connection refused'})
        self.assertEqual(conn.last_test_result, 'error')

    def test_action_test_connection_unreachable_raises(self):
        """Intentar conectar a un URL no existente debe lanzar UserError."""
        conn = self.env['audit.connection'].create({
            'name': 'Unreachable',
            'url': 'http://localhost:9999',
            'database': 'nonexistent',
            'username': 'admin',
            'password': 'wrong',
        })
        with self.assertRaises(UserError):
            conn.action_test_connection()

    def test_action_test_connection_sets_error_state(self):
        """Tras un fallo, last_test_result debe quedar en 'error'."""
        conn = self.env['audit.connection'].create({
            'name': 'Failing Conn',
            'url': 'http://localhost:9999',
            'database': 'none',
            'username': 'admin',
            'password': 'bad',
        })
        try:
            conn.action_test_connection()
        except UserError:
            pass
        self.assertEqual(conn.last_test_result, 'error')
        self.assertTrue(conn.last_test_date)
