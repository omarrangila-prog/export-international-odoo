from odoo.modules.module import Manifest
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestOneInstall(TransactionCase):

    def test_one_app_brings_everything_and_the_administrator_sees_it(self):
        Module = self.env['ir.module.module'].sudo()
        me = Module.search([('name', '=', 'export_international')])
        self.assertTrue(me.application)
        wanted = Manifest.for_addon('export_international').get('depends')
        self.assertEqual(len(wanted), 22)
        self.assertIn('ei_da_feeding', wanted)
        self.assertIn('ei_approvals', wanted)
        self.assertEqual(set(Module.search([('name', 'in', wanted), ('state', '=', 'installed')]).mapped('name')), set(wanted))
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('ei_legacy_master.group_ei_user'))
        root = self.env.ref('ei_legacy_master.menu_ei_root')
        self.assertIn(root.id, self.env['ir.ui.menu'].with_user(admin)._visible_menu_ids())
        self.assertFalse(self.env.ref('base.public_user').has_group('ei_legacy_master.group_ei_user'))
