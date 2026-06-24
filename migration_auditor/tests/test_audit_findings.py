from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditModuleFinding(TransactionCase):
    """Tests del modelo audit.module.finding."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.project = cls.env['audit.project'].create({
            'name': 'AUDIT/TEST/FIND',
            'client_name': 'FindTest Client',
            'audit_mode': 'xmlrpc',
        })

    def _create_module(self, name, category):
        return self.env['audit.module.finding'].create({
            'project_id': self.project.id,
            'name': name,
            'display_name_module': f'Display {name}',
            'module_category': category,
        })

    # ── is_relevant compute ───────────────────────────────────────────────

    def test_custom_module_is_relevant(self):
        mod = self._create_module('my_custom_app', 'custom')
        self.assertTrue(mod.is_relevant)

    def test_oca_module_is_relevant(self):
        mod = self._create_module('purchase_discount', 'oca')
        self.assertTrue(mod.is_relevant)

    def test_odoo_official_not_relevant(self):
        mod = self._create_module('sale', 'odoo_official')
        self.assertFalse(mod.is_relevant)

    def test_enterprise_not_relevant(self):
        mod = self._create_module('web_enterprise', 'enterprise')
        self.assertFalse(mod.is_relevant)

    def test_localization_not_relevant(self):
        mod = self._create_module('l10n_cl', 'localization')
        self.assertFalse(mod.is_relevant)

    # ── compatibility_risk ────────────────────────────────────────────────

    def test_default_compatibility_risk(self):
        mod = self._create_module('test_mod', 'custom')
        self.assertEqual(mod.compatibility_risk, 'low')

    def test_set_compatibility_risk_high(self):
        mod = self._create_module('risky_mod', 'custom')
        mod.write({'compatibility_risk': 'high'})
        self.assertEqual(mod.compatibility_risk, 'high')

    # ── cascade delete ────────────────────────────────────────────────────

    def test_findings_deleted_with_project(self):
        project = self.env['audit.project'].create({
            'name': 'AUDIT/DEL/TEST',
            'client_name': 'Del Client',
            'audit_mode': 'xmlrpc',
        })
        mod = self.env['audit.module.finding'].create({
            'project_id': project.id,
            'name': 'to_delete_mod',
            'module_category': 'custom',
        })
        mod_id = mod.id
        project.unlink()
        self.assertFalse(
            self.env['audit.module.finding'].search([('id', '=', mod_id)])
        )


@tagged('post_install', '-at_install')
class TestAuditFieldFinding(TransactionCase):
    """Tests del modelo audit.field.finding."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.project = cls.env['audit.project'].create({
            'name': 'AUDIT/FIELD/TEST',
            'client_name': 'Field Client',
            'audit_mode': 'backup',
        })

    def _create_field(self, name, origin='studio', has_data=False, count=0):
        return self.env['audit.field.finding'].create({
            'project_id': self.project.id,
            'name': name,
            'model_name': 'res.partner',
            'field_type': 'char',
            'field_origin': origin,
            'has_data': has_data,
            'record_count_with_value': count,
        })

    def test_studio_field_origin(self):
        fld = self._create_field('x_studio_nombre_legal', 'studio', True, 150)
        self.assertEqual(fld.field_origin, 'studio')
        self.assertTrue(fld.has_data)
        self.assertEqual(fld.record_count_with_value, 150)

    def test_custom_dev_field_origin(self):
        fld = self._create_field('x_custom_field', 'custom_dev')
        self.assertEqual(fld.field_origin, 'custom_dev')

    def test_migration_decision_default(self):
        fld = self._create_field('x_studio_test')
        self.assertEqual(fld.migration_decision, 'pending')

    def test_migration_decision_all_values(self):
        for decision in ('migrate', 'recreate_studio', 'drop', 'pending'):
            fld = self._create_field(f'x_field_{decision}')
            fld.write({'migration_decision': decision})
            self.assertEqual(fld.migration_decision, decision)

    def test_field_without_data(self):
        fld = self._create_field('x_studio_empty', 'studio', False, 0)
        self.assertFalse(fld.has_data)
        self.assertEqual(fld.record_count_with_value, 0)


@tagged('post_install', '-at_install')
class TestAuditModelFinding(TransactionCase):
    """Tests del modelo audit.model.finding."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.project = cls.env['audit.project'].create({
            'name': 'AUDIT/MODEL/TEST',
            'client_name': 'Model Client',
            'audit_mode': 'xmlrpc',
        })

    def test_create_model_finding(self):
        mdl = self.env['audit.model.finding'].create({
            'project_id': self.project.id,
            'name': 'x_custom_contrato',
            'description': 'Modelo de contratos personalizados',
            'field_count': 12,
            'record_count': 450,
        })
        self.assertTrue(mdl.id)
        self.assertEqual(mdl.migration_decision, 'pending')

    def test_migration_decision_all_values(self):
        for decision in ('migrate_full', 'migrate_data_only', 'drop', 'pending'):
            mdl = self.env['audit.model.finding'].create({
                'project_id': self.project.id,
                'name': f'x_model_{decision}',
                'migration_decision': decision,
            })
            self.assertEqual(mdl.migration_decision, decision)


@tagged('post_install', '-at_install')
class TestAuditVolumeFinding(TransactionCase):
    """Tests del modelo audit.volume.finding y su compute de volume_tier."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.project = cls.env['audit.project'].create({
            'name': 'AUDIT/VOL/TEST',
            'client_name': 'Volume Client',
            'audit_mode': 'xmlrpc',
        })

    def _create_volume(self, model_name, count):
        return self.env['audit.volume.finding'].create({
            'project_id': self.project.id,
            'model_name': model_name,
            'display_name': model_name,
            'record_count': count,
        })

    def test_volume_tier_low(self):
        vol = self._create_volume('res.partner', 500)
        self.assertEqual(vol.volume_tier, 'low')

    def test_volume_tier_low_boundary(self):
        vol = self._create_volume('res.partner', 9999)
        self.assertEqual(vol.volume_tier, 'low')

    def test_volume_tier_medium(self):
        vol = self._create_volume('account.move', 10000)
        self.assertEqual(vol.volume_tier, 'medium')

    def test_volume_tier_medium_upper(self):
        vol = self._create_volume('account.move', 99999)
        self.assertEqual(vol.volume_tier, 'medium')

    def test_volume_tier_high(self):
        vol = self._create_volume('account.move.line', 100000)
        self.assertEqual(vol.volume_tier, 'high')

    def test_volume_tier_high_large(self):
        vol = self._create_volume('stock.move', 5000000)
        self.assertEqual(vol.volume_tier, 'high')

    def test_volume_tier_zero_records(self):
        vol = self._create_volume('project.task', 0)
        self.assertEqual(vol.volume_tier, 'low')
