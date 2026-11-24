"""Release settings from the private package (24 Nov 2026), with synthetic users only: checkers named by their existing Odoo
user (login or full name, no password shared), approval never switched on with nobody to approve, only the named checkers
approving when the owner chooses it, and accountant-signed code pairs."""
import logging

from odoo import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons import export_international as ex

log = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'ei')
class TestRelease(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        U = cls.env['res.users'].with_context(no_reset_password=True)
        staff = cls.env.ref('ei_contract_da.group_ei_contract_staff')
        cls.c1 = U.create({'name': 'Synthetic Checker One', 'login': 'syn.chk1', 'group_ids': [Command.set([staff.id])]})
        cls.c2 = U.create({'name': 'Synthetic Checker Two', 'login': 'syn.chk2', 'group_ids': [Command.set([staff.id])]})
        cls.clerk = U.create({'name': 'Synthetic Clerk', 'login': 'syn.clerk', 'group_ids': [Command.set([staff.id])]})
        U.create({'name': 'Synthetic Twin', 'login': 'syn.twin1'}); U.create({'name': 'Synthetic Twin', 'login': 'syn.twin2'})

    def test_01_checkers_by_their_existing_user_name_or_login(self):
        appr = ex._approval_settings(self.env, log, {'maker_checker': True, 'approval_on': True,
                                                     'checkers': ['Synthetic Checker One', 'syn.chk2', 'Synthetic Twin', 'Nobody Here']})
        self.assertEqual(sorted(appr['checkers_found']), sorted([self.c1.id, self.c2.id]))      # the twin name and the unknown are skipped
        rule = self.env['ei.approval.rule'].search([('flow', '=', 'da'), ('name', '=', 'Client checkers')])
        self.assertEqual(set(rule.approver_user_ids.ids), {self.c1.id, self.c2.id})

    def test_02_approval_is_never_switched_on_with_nobody_to_approve(self):
        Policy = self.env['ei.approval.policy']
        Policy.sudo().set_all(False)
        appr = ex._approval_settings(self.env, log, {'maker_checker': True, 'approval_on': True, 'checkers': ['Nobody Here']})
        self.assertFalse(ex._apply_approval(self.env, log, appr))
        self.assertFalse(Policy.flow_on('da'))                                                  # left as it was
        appr = ex._approval_settings(self.env, log, {'maker_checker': True, 'approval_on': True, 'checkers': ['syn.chk1']})
        self.assertTrue(ex._apply_approval(self.env, log, appr))
        self.assertTrue(Policy.flow_on('da'))

    def test_03_only_the_named_checkers_approve(self):
        user = self.env.ref('base.group_user')
        approver = self.env.ref('ei_contract_da.group_ei_contract_approver')
        user.write({'implied_ids': [Command.link(approver.id)]})                             # the 17 Nov open access: everyone approves
        self.assertIn(approver, self.clerk.all_group_ids)
        appr = ex._approval_settings(self.env, log, {'maker_checker': True, 'approval_on': True, 'only_checkers_approve': True,
                                                     'checkers': ['syn.chk1', 'syn.chk2']})
        ex._apply_approval(self.env, log, appr)
        self.clerk.invalidate_recordset(); self.c1.invalidate_recordset()
        self.assertNotIn(approver, self.clerk.all_group_ids)                                   # the clerk still enters work...
        self.assertIn(self.env.ref('ei_contract_da.group_ei_contract_staff'), self.clerk.all_group_ids)
        self.assertIn(approver, self.c1.all_group_ids)                                          # ...the checkers approve
        self.assertIn(approver, self.c2.all_group_ids)

    def test_04_code_pairs_signed_by_the_accountant(self):
        batch = self.env['ei.import.batch'].sudo().create({'name': 'synthetic'})
        mk = lambda c, sheet, name: self.env['ei.legacy.code'].sudo().create({'legacy_code': c, 'source_sheet': sheet, 'source_sheet_key': sheet,
                                                                              'source_row': 1, 'original_name': name, 'batch_id': batch.id})
        t, p = mk('93.01', 'FOR PURCHASE', 'SYN EXPORT PUR & SLS'), mk('98.84', 'PROFIT & LOSS', 'SYN EXPORT P&L')
        ex._code_pairs(self.env, log, {'approved_by': 'Synthetic Accountant', 'date': '2026-11-24', 'pairs': [['93.01', '98.84'], ['93.99', '98.99']]})
        pair = self.env['ei.code.pair'].search([('trade_code_id', '=', t.id), ('pl_code_id', '=', p.id)])
        self.assertEqual(pair.state, 'approved')
        self.assertIn('Synthetic Accountant', pair.note)
