from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.ei_legacy_master.tests.test_parsing import source_bytes


@tagged('post_install', '-at_install', 'ei')
class TestLc(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mk = lambda login, g: cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'group_ids': [Command.set([cls.env.ref(g).id])]})
        cls.mgr = mk('lc_mgr', 'ei_trade_lc.group_ei_trade_manager')
        cls.aud = mk('lc_aud', 'ei_legacy_master.group_ei_auditor')
        cls.env['ei.import.batch'].import_file('EXI.csv', source_bytes())
        cls.LC = cls.env['ei.trade.lc']

    def test_01_all_58_references_preserved_and_idempotent(self):
        self.assertEqual(self.LC.with_user(self.mgr).seed_from_legacy(), 58)
        self.assertEqual(self.LC.search_count([]), 58)
        self.assertEqual(self.LC.with_user(self.mgr).seed_from_legacy(), 0)
        covered = self.LC.search([]).legacy_code_ids
        self.assertEqual(len(covered), 58)
        self.assertEqual(set(covered.mapped('source_sheet_key')), {'IMPORT PUR SALE'})
        self.assertIn('16.10', covered.mapped('legacy_code'))
        self.assertEqual(set(self.LC.search([]).mapped('state')), {'unverified'})

    def test_02_grouping_keeps_every_code(self):
        self.LC.with_user(self.mgr).seed_from_legacy()
        a = self.LC.search([('name', 'like', '16.01 ')])
        b = self.LC.search([('name', 'like', '16.02 ')])
        main = (a + b).with_user(self.mgr).action_group()
        self.assertEqual(set(main.legacy_code_ids.mapped('legacy_code')), {'16.01', '16.02'})
        self.assertEqual(self.LC.search_count([]), 57)
        self.assertEqual(len(self.LC.search([]).legacy_code_ids), 58)

    def test_03_only_lc_codes_allowed(self):
        cust = self.env['ei.legacy.code'].search([('legacy_code', '=', '1.01')], limit=1)
        with self.assertRaises(UserError):
            self.LC.create({'name': 'x', 'legacy_code_ids': [Command.set(cust.ids)]})

    def test_04_verification_needs_bank_facts_and_second_person(self):
        bank = self.env['account.journal'].search([('type', '=', 'bank')], limit=1)
        lc = self.LC.create({'name': 'LC 8114'})
        with self.assertRaises(AccessError):
            lc.with_user(self.aud).action_verify()
        with self.assertRaises(UserError):
            lc.with_user(self.mgr).action_verify()   # nothing from the bank yet
        lc.write({'lc_reference': 'LC-8114/2026', 'bank_journal_id': bank.id, 'lc_amount': 1000000})
        lc.with_user(self.mgr).action_verify()
        self.assertEqual(lc.state, 'verified')
        with self.assertRaises(UserError):
            lc.with_user(self.mgr).unlink()

    def test_05_settlement_is_gated_and_posts_nothing(self):
        lc = self.LC.create({'name': 'LC x'})
        moves = self.env['account.move'].search_count([])
        with self.assertRaises(UserError):
            lc.action_settle()
        self.assertEqual(self.env['account.move'].search_count([]), moves)
        self.assertFalse(lc.settlement_enabled)
