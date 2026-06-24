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
        result = engine._evaluate_rule(rule, self.source_partner)
        self.assertEqual(result, 'pass')

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
        result = engine._evaluate_rule(rule, partner_no_email)
        self.assertIn(result, ('fail', 'warning'))

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
        result = engine._evaluate_rule(rule, self.source_partner)
        self.assertEqual(result, 'pass')

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
        result = engine._evaluate_rule(rule, partner_short)
        self.assertIn(result, ('fail', 'warning'))

    # ── Mapeo de campos ────────────────────────────────────────────────────

    def test_apply_field_maps_direct(self):
        engine = self.env['migration.execution']
        vals = engine._apply_field_maps(self.job, self.source_partner)
        self.assertIn('name', vals)
        self.assertEqual(vals['name'], self.source_partner.name)

    def test_apply_field_maps_fixed_value(self):
        email_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'active'),
        ], limit=1)
        self.env['migration.field.map'].create({
            'job_id': self.job.id,
            'dest_field_id': email_field.id,
            'transform_type': 'fixed_value',
            'fixed_value': 'True',
            'sequence': 90,
        })
        engine = self.env['migration.execution']
        vals = engine._apply_field_maps(self.job, self.source_partner)
        self.assertIn('active', vals)

    # ── Dry run ────────────────────────────────────────────────────────────

    def test_wizard_dry_run_creates_run_with_logs(self):
        """El dry run debe crear un run con logs pero no crear registros reales."""
        partners_before = self.env['res.partner'].search_count([
            ('name', '=', 'ETL Source Partner COPY'),
        ])

        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
            'dry_run': True,
            'confirmed': True,
        })
        wizard.action_run()

        run = self.job.execution_run_ids[:1]
        self.assertTrue(run, "Debe existir al menos un run tras el dry run")
        self.assertIn(run.state, ('done', 'done_with_errors'))

        partners_after = self.env['res.partner'].search_count([
            ('name', '=', 'ETL Source Partner COPY'),
        ])
        self.assertEqual(partners_before, partners_after,
                         "El dry run no debe crear registros reales")

    def test_wizard_requires_confirmation(self):
        """El wizard no debe ejecutar sin la casilla de confirmación marcada."""
        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
            'dry_run': False,
            'confirmed': False,
        })
        with self.assertRaises(UserError):
            wizard.action_run()

    # ── Conteo de registros ────────────────────────────────────────────────

    def test_wizard_record_total_compute(self):
        """record_total debe coincidir con el dominio del job."""
        wizard = self.env['run.migration.wizard'].with_context(
            default_job_id=self.job.id,
        ).create({'job_id': self.job.id})
        self.assertGreater(wizard.record_total, 0)

    def test_wizard_record_total_with_domain(self):
        """Con un dominio restrictivo, record_total debe ser menor."""
        self.job.write({'source_domain': "[('id', '=', %d)]" % self.source_partner.id})
        wizard = self.env['run.migration.wizard'].create({
            'job_id': self.job.id,
        })
        self.assertEqual(wizard.record_total, 1)
        self.job.write({'source_domain': False})

    # ── Logs ──────────────────────────────────────────────────────────────

    def test_migration_log_fields(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/LOG/TEST',
        })
        log = self.env['migration.log'].create({
            'run_id': run.id,
            'job_id': self.job.id,
            'result': 'success',
            'source_record_id': self.source_partner.id,
            'message': 'Record migrated successfully',
        })
        self.assertEqual(log.result, 'success')
        self.assertEqual(log.run_id, run)
        self.assertEqual(log.job_id, self.job)

    def test_migration_log_results(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/LOG/TEST/2',
        })
        for result in ('success', 'warning', 'error', 'skipped'):
            log = self.env['migration.log'].create({
                'run_id': run.id,
                'job_id': self.job.id,
                'result': result,
                'source_record_id': 1,
                'message': f'Test {result}',
            })
            self.assertEqual(log.result, result)
