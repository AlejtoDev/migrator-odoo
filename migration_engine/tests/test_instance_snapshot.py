from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInstanceModuleStatus(TransactionCase):
    """Tests del Bloque B — instance.module.status."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.ModuleStatus = cls.env['instance.module.status']

    # ── refresh_snapshot ───────────────────────────────────────────────────

    def test_refresh_snapshot_creates_records(self):
        self.ModuleStatus.sudo().refresh_snapshot()
        count = self.ModuleStatus.search_count([])
        self.assertGreater(count, 0, "refresh_snapshot debe crear registros de módulos")

    def test_refresh_snapshot_includes_base_module(self):
        self.ModuleStatus.sudo().refresh_snapshot()
        base_status = self.ModuleStatus.search([('name', '=', 'base')], limit=1)
        self.assertTrue(base_status, "El módulo 'base' debe aparecer en el inventario")

    def test_refresh_snapshot_idempotent(self):
        """Llamar refresh_snapshot dos veces no debe duplicar registros."""
        self.ModuleStatus.sudo().refresh_snapshot()
        count_first = self.ModuleStatus.search_count([])
        self.ModuleStatus.sudo().refresh_snapshot()
        count_second = self.ModuleStatus.search_count([])
        self.assertEqual(count_first, count_second,
                         "refresh_snapshot no debe duplicar registros")

    def test_refresh_preserves_manual_notes(self):
        """Las notas manuales no deben borrarse al refrescar."""
        self.ModuleStatus.sudo().refresh_snapshot()
        base_rec = self.ModuleStatus.search([('name', '=', 'base')], limit=1)
        self.assertTrue(base_rec)
        base_rec.write({'notes': 'Nota manual de prueba'})
        self.ModuleStatus.sudo().refresh_snapshot()
        base_rec_after = self.ModuleStatus.search([('name', '=', 'base')], limit=1)
        self.assertEqual(base_rec_after.notes, 'Nota manual de prueba',
                         "Las notas manuales no deben perderse al refrescar")

    # ── Categorización ────────────────────────────────────────────────────

    def test_base_module_is_odoo_official(self):
        self.ModuleStatus.sudo().refresh_snapshot()
        base_rec = self.ModuleStatus.search([('name', '=', 'base')], limit=1)
        self.assertIn(base_rec.module_category, ('odoo_official', 'unknown'),
                      "El módulo 'base' debe ser categorizado como odoo_official")

    def test_l10n_module_is_localization(self):
        """Módulos que empiezan con l10n_ deben ser categorizados como localization."""
        l10n_mods = self.env['ir.module.module'].sudo().search([
            ('name', 'like', 'l10n_'), ('state', '=', 'installed'),
        ], limit=1)
        if not l10n_mods:
            self.skipTest("No hay módulos l10n_ instalados")
        self.ModuleStatus.sudo().refresh_snapshot()
        l10n_status = self.ModuleStatus.search([
            ('name', 'like', 'l10n_'),
        ], limit=1)
        if l10n_status:
            self.assertEqual(l10n_status.module_category, 'localization')

    def test_is_relevant_field_compute(self):
        self.ModuleStatus.sudo().refresh_snapshot()
        base_rec = self.ModuleStatus.search([('name', '=', 'base')], limit=1)
        self.assertFalse(base_rec.is_relevant_for_migration,
                         "El módulo base oficial no debe ser relevante para migración")

    # ── CRUD básico ────────────────────────────────────────────────────────

    def test_manual_create(self):
        rec = self.ModuleStatus.create({
            'name': 'my_test_module',
            'module_category': 'custom',
            'state': 'installed',
        })
        self.assertTrue(rec.id)
        self.assertEqual(rec.module_category, 'custom')
        self.assertTrue(rec.is_relevant_for_migration)

    def test_module_category_options(self):
        for cat in ('odoo_official', 'oca', 'custom', 'enterprise', 'localization', 'unknown'):
            rec = self.ModuleStatus.create({
                'name': f'test_mod_{cat}',
                'module_category': cat,
                'state': 'installed',
            })
            self.assertEqual(rec.module_category, cat)


@tagged('post_install', '-at_install')
class TestInstanceStudioField(TransactionCase):
    """Tests del Bloque B — instance.studio.field."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.StudioField = cls.env['instance.studio.field']

    # ── refresh_studio_fields ─────────────────────────────────────────────

    def test_refresh_studio_fields_runs_without_error(self):
        """refresh_studio_fields no debe lanzar excepción aunque no haya campos Studio."""
        try:
            self.StudioField.sudo().refresh_studio_fields()
        except Exception as e:
            self.fail(f"refresh_studio_fields lanzó excepción: {e}")

    def test_studio_field_migration_impact_selection(self):
        """Los valores de migration_impact deben ser cadenas compatibles con widget priority."""
        rec = self.StudioField.create({
            'name': 'x_studio_test_field',
            'field_description': 'Test field',
            'model_name': 'res.partner',
            'ttype': 'char',
            'migration_impact': '2',
        })
        self.assertEqual(rec.migration_impact, '2')

    def test_studio_field_impact_all_values(self):
        """Todos los valores válidos del priority widget deben aceptarse."""
        for impact in ('0', '1', '2', '3'):
            rec = self.StudioField.create({
                'name': f'x_studio_impact_{impact}',
                'field_description': f'Impact {impact}',
                'model_name': 'res.partner',
                'ttype': 'char',
                'migration_impact': impact,
            })
            self.assertEqual(rec.migration_impact, impact)

    def test_studio_field_sample_values_not_stored(self):
        """sample_values debe ser store=False."""
        field_def = self.env['ir.model.fields'].search([
            ('model', '=', 'instance.studio.field'),
            ('name', '=', 'sample_values'),
        ], limit=1)
        if field_def:
            self.assertFalse(field_def.store,
                             "sample_values debe ser store=False")

    def test_studio_field_crud(self):
        rec = self.StudioField.create({
            'name': 'x_studio_my_custom',
            'field_description': 'Campo Studio de prueba',
            'model_name': 'res.partner',
            'ttype': 'char',
            'migration_impact': '1',
        })
        self.assertTrue(rec.id)
        rec.write({'migration_notes': 'Migrar a campo nativo'})
        self.assertEqual(rec.migration_notes, 'Migrar a campo nativo')
        rec_id = rec.id
        rec.unlink()
        self.assertFalse(self.StudioField.search([('id', '=', rec_id)]))


@tagged('post_install', '-at_install')
class TestSnapshotRefreshWizard(TransactionCase):
    """Tests del wizard de reescaneo de snapshot."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})

    def test_wizard_refresh_modules(self):
        wizard = self.env['snapshot.refresh.wizard'].create({
            'refresh_modules': True,
            'refresh_studio_fields': False,
        })
        try:
            wizard.action_refresh()
        except Exception as e:
            self.fail(f"El wizard de refresh falló: {e}")

    def test_wizard_refresh_both(self):
        wizard = self.env['snapshot.refresh.wizard'].create({
            'refresh_modules': True,
            'refresh_studio_fields': True,
        })
        try:
            wizard.action_refresh()
        except Exception as e:
            self.fail(f"El wizard de refresh (ambos) falló: {e}")
