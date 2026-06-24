from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditEffortLine(TransactionCase):
    """Tests del modelo audit.effort.line — líneas de estimación de horas."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.project = cls.env['audit.project'].create({
            'name': 'AUDIT/EFFORT/TEST',
            'client_name': 'Effort Client',
            'audit_mode': 'xmlrpc',
            'hourly_rate': 80.0,
        })

    def _create_line(self, category='other', hours=8.0, source='manual'):
        return self.env['audit.effort.line'].create({
            'project_id': self.project.id,
            'category': category,
            'description': f'Línea {category}',
            'estimated_hours': hours,
            'source': source,
        })

    # ── subtotal compute ───────────────────────────────────────────────────

    def test_subtotal_compute(self):
        line = self._create_line(hours=10.0)
        self.assertAlmostEqual(line.subtotal, 800.0, places=2)

    def test_subtotal_zero_hours(self):
        line = self._create_line(hours=0.0)
        self.assertAlmostEqual(line.subtotal, 0.0, places=2)

    def test_subtotal_recomputes_on_hours_change(self):
        line = self._create_line(hours=5.0)
        self.assertAlmostEqual(line.subtotal, 400.0, places=2)
        line.write({'estimated_hours': 20.0})
        self.assertAlmostEqual(line.subtotal, 1600.0, places=2)

    def test_subtotal_recomputes_on_rate_change(self):
        line = self._create_line(hours=10.0)
        self.assertAlmostEqual(line.subtotal, 800.0, places=2)
        self.project.write({'hourly_rate': 150.0})
        line.invalidate_recordset(['subtotal', 'unit_price'])
        self.assertAlmostEqual(line.subtotal, 1500.0, places=2)
        self.project.write({'hourly_rate': 80.0})

    # ── source field ───────────────────────────────────────────────────────

    def test_source_auto(self):
        line = self._create_line(source='auto')
        self.assertEqual(line.source, 'auto')

    def test_source_manual(self):
        line = self._create_line(source='manual')
        self.assertEqual(line.source, 'manual')

    # ── categorías ────────────────────────────────────────────────────────

    def test_all_categories_valid(self):
        categories = [
            'analysis', 'custom_module', 'oca_module', 'studio_fields',
            'custom_model', 'data_volume', 'testing', 'training',
            'contingency', 'other',
        ]
        for cat in categories:
            line = self._create_line(category=cat, hours=1.0)
            self.assertEqual(line.category, cat)

    # ── sequence order ────────────────────────────────────────────────────

    def test_effort_lines_ordered_by_sequence(self):
        project = self.env['audit.project'].create({
            'name': 'AUDIT/SEQ/TEST',
            'client_name': 'Seq Client',
            'audit_mode': 'xmlrpc',
        })
        l1 = self.env['audit.effort.line'].create({
            'project_id': project.id, 'category': 'testing',
            'description': 'Last', 'estimated_hours': 1.0,
            'sequence': 30, 'source': 'manual',
        })
        l2 = self.env['audit.effort.line'].create({
            'project_id': project.id, 'category': 'analysis',
            'description': 'First', 'estimated_hours': 1.0,
            'sequence': 10, 'source': 'manual',
        })
        l3 = self.env['audit.effort.line'].create({
            'project_id': project.id, 'category': 'custom_module',
            'description': 'Middle', 'estimated_hours': 1.0,
            'sequence': 20, 'source': 'manual',
        })
        sorted_lines = project.effort_line_ids.sorted('sequence')
        self.assertEqual(sorted_lines[0], l2)
        self.assertEqual(sorted_lines[1], l3)
        self.assertEqual(sorted_lines[2], l1)

    # ── project totals ────────────────────────────────────────────────────

    def test_project_total_hours_sums_lines(self):
        project = self.env['audit.project'].create({
            'name': 'AUDIT/TOTAL/TEST',
            'client_name': 'Total Client',
            'audit_mode': 'xmlrpc',
            'hourly_rate': 50.0,
        })
        hours = [8.0, 16.0, 4.0, 2.5]
        for i, h in enumerate(hours):
            self.env['audit.effort.line'].create({
                'project_id': project.id,
                'category': 'other',
                'description': f'Line {i}',
                'estimated_hours': h,
                'source': 'manual',
            })
        self.assertAlmostEqual(project.total_hours, sum(hours), places=2)
        self.assertAlmostEqual(project.total_cost, sum(hours) * 50.0, places=2)


@tagged('post_install', '-at_install')
class TestRunAuditWizardEffort(TransactionCase):
    """Tests de _generate_effort_lines en run.audit.wizard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context={**cls.env.context, 'tracking_disable': True})
        cls.project = cls.env['audit.project'].create({
            'name': 'AUDIT/WIZEFF/TEST',
            'client_name': 'Wizard Effort Client',
            'audit_mode': 'xmlrpc',
            'hourly_rate': 100.0,
        })

    def _populate_project_findings(self):
        """Crea findings típicos para simular resultados de un escaneo."""
        self.env['audit.module.finding'].create([
            {'project_id': self.project.id, 'name': 'my_custom_module',
             'module_category': 'custom', 'display_name_module': 'Mi Módulo Custom'},
            {'project_id': self.project.id, 'name': 'purchase_discount',
             'module_category': 'oca', 'display_name_module': 'Purchase Discount'},
            {'project_id': self.project.id, 'name': 'sale',
             'module_category': 'odoo_official', 'display_name_module': 'Sales'},
        ])
        self.env['audit.field.finding'].create([
            {'project_id': self.project.id, 'name': 'x_studio_codigo',
             'model_name': 'res.partner', 'field_origin': 'studio',
             'has_data': True, 'record_count_with_value': 200},
            {'project_id': self.project.id, 'name': 'x_custom_field',
             'model_name': 'res.partner', 'field_origin': 'custom_dev',
             'has_data': True, 'record_count_with_value': 100},
        ])
        self.env['audit.model.finding'].create({
            'project_id': self.project.id,
            'name': 'x_contrato',
            'description': 'Contratos',
            'field_count': 8,
            'record_count': 300,
        })
        self.env['audit.volume.finding'].create({
            'project_id': self.project.id,
            'model_name': 'account.move.line',
            'display_name': 'Líneas contables',
            'record_count': 250000,
            'effort_extra_hours': 10.0,
        })

    def test_generate_effort_lines_creates_lines(self):
        self._populate_project_findings()
        wizard = self.env['run.audit.wizard'].create({
            'project_id': self.project.id,
            'generate_effort': True,
        })
        wizard._generate_effort_lines(self.project, log=lambda m: None)
        self.assertGreater(len(self.project.effort_line_ids), 0,
                           "Deben crearse líneas de esfuerzo automáticas")

    def test_generate_effort_includes_contingency(self):
        self._populate_project_findings()
        wizard = self.env['run.audit.wizard'].create({
            'project_id': self.project.id,
            'generate_effort': True,
        })
        self.project.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()
        wizard._generate_effort_lines(self.project, log=lambda m: None)
        contingency_lines = self.project.effort_line_ids.filtered(
            lambda l: l.category == 'contingency'
        )
        self.assertTrue(contingency_lines,
                        "Debe existir una línea de contingencia")

    def test_generate_effort_only_relevant_modules(self):
        """Solo se generan líneas para módulos custom y OCA (is_relevant=True)."""
        self._populate_project_findings()
        wizard = self.env['run.audit.wizard'].create({
            'project_id': self.project.id,
            'generate_effort': True,
        })
        self.project.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()
        wizard._generate_effort_lines(self.project, log=lambda m: None)

        module_lines = self.project.effort_line_ids.filtered(
            lambda l: l.category in ('custom_module', 'oca_module')
        )
        refs = module_lines.mapped('reference')
        self.assertIn('my_custom_module', refs)
        self.assertIn('purchase_discount', refs)
        self.assertNotIn('sale', refs)

    def test_generate_effort_removes_previous_auto_lines(self):
        """Regenerar no acumula líneas duplicadas."""
        self._populate_project_findings()
        wizard = self.env['run.audit.wizard'].create({
            'project_id': self.project.id,
            'generate_effort': True,
        })
        wizard._generate_effort_lines(self.project, log=lambda m: None)
        count_first = len(self.project.effort_line_ids.filtered(lambda l: l.source == 'auto'))
        wizard._generate_effort_lines(self.project, log=lambda m: None)
        count_second = len(self.project.effort_line_ids.filtered(lambda l: l.source == 'auto'))
        self.assertEqual(count_first, count_second,
                         "Regenerar no debe duplicar las líneas auto")

    def test_generate_effort_volume_high_adds_hours(self):
        """El volumen alto debe generar horas adicionales."""
        self._populate_project_findings()
        wizard = self.env['run.audit.wizard'].create({
            'project_id': self.project.id,
            'generate_effort': True,
        })
        self.project.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()
        wizard._generate_effort_lines(self.project, log=lambda m: None)
        volume_lines = self.project.effort_line_ids.filtered(
            lambda l: l.category == 'data_volume'
        )
        self.assertTrue(volume_lines)
        self.assertGreater(volume_lines[0].estimated_hours, 0)

    def test_contingency_is_ten_percent(self):
        """La contingencia debe ser ~10% del subtotal base."""
        self._populate_project_findings()
        wizard = self.env['run.audit.wizard'].create({
            'project_id': self.project.id,
            'generate_effort': True,
        })
        self.project.effort_line_ids.filtered(lambda l: l.source == 'auto').unlink()
        wizard._generate_effort_lines(self.project, log=lambda m: None)

        auto_lines = self.project.effort_line_ids.filtered(lambda l: l.source == 'auto')
        contingency = auto_lines.filtered(lambda l: l.category == 'contingency')
        base_lines = auto_lines.filtered(lambda l: l.category != 'contingency')

        if contingency and base_lines:
            base_total = sum(base_lines.mapped('estimated_hours'))
            expected_contingency = round(base_total * 0.10, 1)
            self.assertAlmostEqual(
                contingency[0].estimated_hours, expected_contingency, delta=0.5,
                msg="La contingencia debe ser aproximadamente el 10% del total base"
            )
