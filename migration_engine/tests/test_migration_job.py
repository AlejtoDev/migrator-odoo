from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError


@tagged('post_install', '-at_install')
class TestMigrationJob(TransactionCase):
    """Tests del modelo migration.job — configuración del trabajo ETL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.ResPartner = cls.env['res.partner']
        cls.Job = cls.env['migration.job']

    def _create_job(self, mode='create_only', **kwargs):
        vals = {
            'name': 'Test Job',
            'source_model_id': self.env.ref('base.model_res_partner').id,
            'dest_model_id': self.env.ref('base.model_res_partner').id,
            'mode': mode,
        }
        vals.update(kwargs)
        return self.Job.create(vals)

    # ── CREATE ────────────────────────────────────────────────────────────

    def test_create_job_minimal(self):
        job = self._create_job()
        self.assertTrue(job.id)
        self.assertEqual(job.mode, 'create_only')
        self.assertEqual(job.state, 'draft')

    def test_create_job_all_modes(self):
        for mode in ('create_only', 'update_only', 'create_or_update'):
            job = self._create_job(mode=mode, name=f'Job {mode}')
            self.assertEqual(job.mode, mode)

    def test_job_requires_source_model(self):
        with self.assertRaises(Exception):
            self.Job.create({
                'name': 'No Source',
                'dest_model_id': self.env.ref('base.model_res_partner').id,
                'mode': 'create_only',
            })

    def test_job_requires_dest_model(self):
        with self.assertRaises(Exception):
            self.Job.create({
                'name': 'No Dest',
                'source_model_id': self.env.ref('base.model_res_partner').id,
                'mode': 'create_only',
            })

    # ── FIELD MAPS ────────────────────────────────────────────────────────

    def test_add_field_map_direct(self):
        job = self._create_job()
        source_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'),
            ('name', '=', 'name'),
        ], limit=1)
        dest_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'),
            ('name', '=', 'name'),
        ], limit=1)
        fmap = self.env['migration.field.map'].create({
            'job_id': job.id,
            'source_field_id': source_field.id,
            'dest_field_id': dest_field.id,
            'transform_type': 'direct',
            'sequence': 10,
        })
        self.assertEqual(fmap.job_id, job)
        self.assertEqual(fmap.transform_type, 'direct')

    def test_add_field_map_fixed_value(self):
        job = self._create_job()
        dest_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'),
            ('name', '=', 'active'),
        ], limit=1)
        fmap = self.env['migration.field.map'].create({
            'job_id': job.id,
            'dest_field_id': dest_field.id,
            'transform_type': 'fixed_value',
            'fixed_value': 'True',
            'sequence': 20,
        })
        self.assertEqual(fmap.transform_type, 'fixed_value')
        self.assertEqual(fmap.fixed_value, 'True')

    def test_field_map_sequence_order(self):
        job = self._create_job()
        name_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)
        email_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'email'),
        ], limit=1)
        fm1 = self.env['migration.field.map'].create({
            'job_id': job.id,
            'source_field_id': name_field.id,
            'dest_field_id': name_field.id,
            'transform_type': 'direct',
            'sequence': 20,
        })
        fm2 = self.env['migration.field.map'].create({
            'job_id': job.id,
            'source_field_id': email_field.id,
            'dest_field_id': email_field.id,
            'transform_type': 'direct',
            'sequence': 10,
        })
        maps = job.field_map_ids.sorted('sequence')
        self.assertEqual(maps[0], fm2)
        self.assertEqual(maps[1], fm1)

    # ── RULES ─────────────────────────────────────────────────────────────

    def test_add_validation_rule(self):
        job = self._create_job()
        name_field = self.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)
        rule = self.env['migration.rule'].create({
            'job_id': job.id,
            'name': 'Name not null',
            'field_id': name_field.id,
            'rule_type': 'not_null',
            'on_failure': 'error',
            'sequence': 10,
        })
        self.assertEqual(rule.job_id, job)
        self.assertEqual(rule.rule_type, 'not_null')
        self.assertEqual(rule.on_failure, 'error')

    def test_rule_on_failure_options(self):
        job = self._create_job()
        for on_failure in ('warning', 'error'):
            rule = self.env['migration.rule'].create({
                'job_id': job.id,
                'name': f'Rule {on_failure}',
                'rule_type': 'not_null',
                'on_failure': on_failure,
                'sequence': 10,
            })
            self.assertEqual(rule.on_failure, on_failure)

    # ── EXECUTION RUN ─────────────────────────────────────────────────────

    def test_execution_run_state_default(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/TEST/0001',
        })
        self.assertEqual(run.state, 'running')
        self.assertTrue(run.name.startswith('RUN'))

    def test_execution_run_counts_compute(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/TEST/0002',
        })
        job = self._create_job()
        self.env['migration.log'].create([
            {'run_id': run.id, 'job_id': job.id, 'result': 'success',
             'source_record_id': 1, 'message': 'OK'},
            {'run_id': run.id, 'job_id': job.id, 'result': 'warning',
             'source_record_id': 2, 'message': 'Warning'},
            {'run_id': run.id, 'job_id': job.id, 'result': 'error',
             'source_record_id': 3, 'message': 'Error'},
        ])
        self.assertEqual(run.success_count, 1)
        self.assertEqual(run.warning_count, 1)
        self.assertEqual(run.error_count, 1)

    def test_execution_run_state_transition(self):
        run = self.env['migration.execution.run'].create({
            'name': 'RUN/TEST/0003',
        })
        run.write({'state': 'done'})
        self.assertEqual(run.state, 'done')


@tagged('post_install', '-at_install')
class TestMigrationFieldMap(TransactionCase):
    """Tests de constrains y tipos de transformación en migration.field.map."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.job = cls.env['migration.job'].create({
            'name': 'FieldMap Test Job',
            'source_model_id': cls.env.ref('base.model_res_partner').id,
            'dest_model_id': cls.env.ref('base.model_res_partner').id,
            'mode': 'create_only',
        })
        cls.name_field = cls.env['ir.model.fields'].search([
            ('model', '=', 'res.partner'), ('name', '=', 'name'),
        ], limit=1)

    def test_transform_type_python_expr(self):
        fmap = self.env['migration.field.map'].create({
            'job_id': self.job.id,
            'source_field_id': self.name_field.id,
            'dest_field_id': self.name_field.id,
            'transform_type': 'python_expr',
            'python_expr': "record.name.upper()",
            'sequence': 10,
        })
        self.assertEqual(fmap.transform_type, 'python_expr')
        self.assertEqual(fmap.python_expr, "record.name.upper()")

    def test_transform_type_lookup(self):
        fmap = self.env['migration.field.map'].create({
            'job_id': self.job.id,
            'source_field_id': self.name_field.id,
            'dest_field_id': self.name_field.id,
            'transform_type': 'lookup',
            'lookup_model_id': self.env.ref('base.model_res_partner').id,
            'sequence': 30,
        })
        self.assertEqual(fmap.transform_type, 'lookup')
