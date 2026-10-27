"""Before an approval takes effect the person sees what is being approved, who prepared it, what changed, the documents, what will happen,
and whether they may do it. Documents open beside the record. Only what the person may already read is ever shown."""
from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney


@tagged('post_install', '-at_install', 'ei')
class TestApprovalEvidence(TestJourney):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        prod = cls.env['product.product'].create({'name': 'Rev coil', 'uom_id': cls.env.ref('uom.product_uom_ton').id})
        parent = cls.env['res.partner'].create({'name': 'Rev Parent Mill'})
        cls.c = cls.env['ei.contract'].with_user(cls.maker).create({'parent_partner_id': parent.id, 'contract_ref': 'REV-1', 'line_ids': [Command.create({
            'product_id': prod.id, 'ordered_mtl': 5, 'purchase_rate': 1, 'sale_rate': 2})]})
        cls.doc = cls.env['ir.attachment'].create({'name': 'signed-contract.pdf', 'res_model': 'ei.contract', 'res_id': cls.c.id, 'raw': b'%PDF-1.4 x', 'mimetype': 'application/pdf'})
        cls.env.flush_all()
        cls.env.cr.precommit.run()                                                    # the creation is committed first...
        cls.c.with_user(cls.maker).write({'contract_ref': 'REV-1B'})                 # ...then a tracked change before review
        cls.env.flush_all()
        cls.env.cr.precommit.run()                                                    # Odoo writes tracked changes when the transaction commits
        cls.c.with_user(cls.maker).action_review()
        cls.E = cls.env['ei.approval.evidence']

    def ev(self, user, model='ei.contract', res_id=None, method='action_approve'):
        return self.E.with_user(user).get_evidence(model, res_id or self.c.id, method)

    def test_e01_the_approver_sees_what_who_changes_documents_and_effect(self):
        e = self.ev(self.capprover)
        self.assertEqual(e['verb'], 'Approve')
        facts = {f['label']: f['value'] for f in e['facts']}
        self.assertIn('REV-1B', facts.values())
        self.assertIn('Rev Parent Mill', facts.values())
        self.assertEqual(e['maker']['name'], self.maker.name)
        self.assertTrue(e['you']['has_role'] and not e['you']['self_made'])
        self.assertFalse(e['blocked'])
        change = next((ch for ch in e['changes'] if ch['old'] == 'REV-1'), None)
        self.assertTrue(change, e['changes'])
        self.assertEqual((change['new'], change['who']), ('REV-1B', self.maker.name))
        self.assertEqual([d['name'] for d in e['documents']], ['signed-contract.pdf'])
        self.assertEqual(e['documents'][0]['kind'], 'pdf')
        self.assertIn('delivery advices', e['effect'])

    def test_e02_the_maker_and_someone_without_the_role_are_told_why_not(self):
        own = self.ev(self.maker)
        self.assertTrue(own['blocked'])
        self.assertFalse(own['you']['has_role'])
        self.capprover.group_ids = [Command.link(self.env.ref('ei_contract_da.group_ei_contract_staff').id)]
        c2 = self.env['ei.contract'].with_user(self.capprover).create({'parent_partner_id': self.c.parent_partner_id.id, 'contract_ref': 'REV-OWN'})
        mine = self.ev(self.capprover, res_id=c2.id)
        self.assertTrue(mine['you']['self_made'])
        self.assertIn('maker-checker', mine['blocked'])

    def test_e03_the_dialog_never_replaces_the_server_rule(self):
        with self.assertRaises(AccessError):
            self.c.with_user(self.maker).action_approve()                   # whatever the screen shows, the method still refuses
        self.c.with_user(self.capprover).action_approve()
        self.assertEqual(self.c.state, 'approved')

    def test_e04_only_known_buttons_and_only_readable_records(self):
        self.assertFalse(self.E.with_user(self.capprover).get_evidence('ei.contract', self.c.id, 'unlink'))
        self.assertFalse(self.E.with_user(self.capprover).get_evidence('res.partner', 1, 'action_approve'))
        with self.assertRaises(AccessError):
            self.ev(self.cashclerk)                                          # cannot read contracts, so sees nothing of one
        buttons = self.E.with_user(self.capprover).approval_buttons()
        self.assertIn('action_approve', buttons['ei.contract'])
        self.assertNotIn('ei.contract', self.E.with_user(self.cashclerk).approval_buttons())

    def test_e05_every_listed_approval_points_at_a_real_button_and_role(self):
        from odoo.addons.ei_app_shell.models.approval import APPROVALS
        for (model, method), (verb, effect, group, maker, facts) in APPROVALS.items():
            if model not in self.env:
                continue
            self.assertTrue(hasattr(self.env[model], method), f'{model}.{method}')
            self.assertTrue(self.env.ref(group, raise_if_not_found=False), group)
            for f in facts + [maker]:
                self.assertIn(f, self.env[model]._fields, f'{model}.{f}')

    def test_e06_documents_beside_the_record_follow_the_record_rights(self):
        D = self.env['ei.documents']
        docs = D.with_user(self.capprover).list_for('ei.contract', self.c.id)
        self.assertEqual([(d['name'], d['kind']) for d in docs], [('signed-contract.pdf', 'pdf')])
        self.assertNotIn('access_token', docs[0]['url'])                     # never a shareable link
        with self.assertRaises(AccessError):
            D.with_user(self.cashclerk).list_for('ei.contract', self.c.id)
        self.assertEqual(D.with_user(self.capprover).list_for('ei.contract', 0), [])
