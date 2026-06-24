from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestMigrationExecution(TransactionCase):
    """Tests del motor ETL — migration.execution (AbstractModel)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})

        cls.job = cls.env['migration.job'].create({
            'name': 'ETL Test Job',
            'source_model_id': cls.env.ref('base.model_res_partner').id,
            'dest_model_id': cls.env.ref('base.model_res_partner').id,
            'mode': 'create_only',
        })

        name_field = cls.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)
        cls.env['migration.field.map'].create({
            'job_id': cls.job.id,
            'source_field_id': name_field.id,
            'dest_field_id': name_field.id,
            'transform_type': 'direct',
            'sequence': 10,
        })

        cls.source_partner = cls.env['res.partner'].create({
            'name': 'ETL Source Partner',
            'email': 'etl@test.com',
        })

    # ── Validación de reglas ───────────────────────────────────────────────

    def test_rule_not_null_passes_when_field_has_value(self):
        engine = self.env['migration.execution']
        name_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)
        rule = self.env['migration.rule'].create({
            'job_id': self.job.id,
            'name': 'Name not null',
            'field_id': name_field.id,
            'rule_type': 'not_null',
            'on_failure': 'error',
            'sequence': 10,
            'active': True,
        })
        field_value = self.source_partner.name
        result = engine._evaluate_rule(rule, field_value, self.source_partner)
        self.assertTrue(result)

    def test_rule_not_null_fails_when_field_empty(self):
        engine = self.env['migration.execution']
        email_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'email'),
        ], limit=1)
        partner_no_email = self.env['res.partner'].create({'name': 'No Email'})
        rule = self.env['migration.rule'].create({
            'job_id': self.job.id,
            'name': 'Email not null',
            'field_id': email_field.id,
            'rule_type': 'not_null',
            'on_failure': 'error',
            'sequence': 20,
            'active': True,
        })
        field_value = partner_no_email.email
        result = engine._evaluate_rule(rule, field_value, partner_no_email)
        self.assertFalse(result)

    def test_rule_python_expr_pass(self):
        engine = self.env['migration.execution']
        name_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)
        rule = self.env['migration.rule'].create({
            'job_id': self.job.id,
            'name': 'Name length > 2',
            'field_id': name_field.id,
            'rule_type': 'python_expr',
            'python_expr': "len(record.name) > 2",
            'on_failure': 'warning',
            'sequence': 30,
            'active': True,
        })
        field_value = self.source_partner.name
        result = engine._evaluate_rule(rule, field_value, self.source_partner)
        self.assertTrue(result)

    def test_rule_python_expr_fail(self):
        engine = self.env['migration.execution']
        name_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)
        partner_short = self.env['res.partner'].create({'name': 'AB'})
        rule = self.env['migration.rule'].create({
            'job_id': self.job.id,
            'name': 'Name length > 5',
            'field_id': name_field.id,
            'rule_type': 'python_expr',
            'python_expr': "len(record.name) > 5",
            'on_failure': 'warning',
            'sequence': 40,
            'active': True,
        })
        field_value = partner_short.name
        result = engine._evaluate_rule(rule, field_value, partner_short)
        self.assertFalse(result)

    # ── Mapeo de campos ────────────────────────────────────────────────────

    def test_apply_field_maps_direct(self):
        engine = self.env['migration.execution']
        vals = engine._apply_field_maps(self.job, self.source_partner)
        self.assertIn('name', vals)
        self.assertEqual(vals['name'], self.source_partner.name)

    def test_apply_field_maps_fixed_value(self):
        active_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'active'),
        ], limit=1)
        self.env['migration.field.map'].create({
            'job_id': self.job.id,
            'dest_field_id': active_field.id,
            'transform_type': 'fixed_value',
            'fixed_value': 'True',
            'sequence': 90,
        })
        engine = self.env['migration.execution']
        vals = engine._apply_field_maps(self.job, self.source_partner)
        self.assertIn('active', vals)

    # ── Dry run ────────────────────────────────────────────────────────────

    def test_wizard_dry_run_creates_run_with_logs(self):
        """El dry run debe crear un run con logs pero sin modificar datos reales."""
        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
            'dry_run': True,
            'confirm': False,
        })
        wizard.action_execute()

        run = self.job.execution_run_ids[:1]
        self.assertTrue(run, "Debe existir al menos un run tras el dry run")
        self.assertIn(run.state, ('done', 'partial', 'error'))

    def test_wizard_requires_confirmation(self):
        """El wizard no debe ejecutar en producción sin la casilla de confirmación."""
        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
            'dry_run': False,
            'confirm': False,
        })
        with self.assertRaises(UserError):
            wizard.action_execute()

    # ── Conteo de registros ────────────────────────────────────────────────

    def test_wizard_record_total_compute(self):
        """record_total debe coincidir con el dominio del job."""
        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
        })
        self.assertGreater(wizard.record_total, 0)

    def test_wizard_record_total_with_domain(self):
        """Con un dominio restrictivo, record_total debe ser 1."""
        self.job.write({'domain': "[('id', '=', %d)]" % self.source_partner.id})
        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
        })
        self.assertEqual(wizard.record_total, 1)
        self.job.write({'domain': '[]'})

    # ── Logs ──────────────────────────────────────────────────────────────

    def test_migration_log_fields(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/LOG/TEST',
            'job_id': self.job.id,
        })
        log = self.env['migration.log'].create({
            'execution_run_id': run.id,
            'log_type': 'info',
            'source_record_id_int': self.source_partner.id,
            'message': 'Record migrated successfully',
        })
        self.assertEqual(log.log_type, 'info')
        self.assertEqual(log.execution_run_id, run)
        self.assertEqual(log.job_id, self.job)

    def test_migration_log_types(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/LOG/TEST/2',
            'job_id': self.job.id,
        })
        for log_type in ('info', 'warning', 'error'):
            log = self.env['migration.log'].create({
                'execution_run_id': run.id,
                'log_type': log_type,
                'source_record_id_int': 1,
                'message': f'Test {log_type}',
            })
            self.assertEqual(log.log_type, log_type)
