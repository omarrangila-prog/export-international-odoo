"""A button a person can see must be a button that person may press. Found in the screenshot gallery: the CEO saw "New" on the cards of
contracts, delivery advices, daily orders, loadings, cash vouchers, supplier invoices, parent statements and bank imports, and every click
ended in an Access Error. Odoo hides New on its own when the user lacks the create right - unless the view forces create="1", which the
cards did. The access rules are not touched; the screen just stops inviting what the server refuses."""
import re

from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney

CARD_MODELS = ('ei.bank.import', 'ei.cash.voucher', 'ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting', 'ei.parent.statement', 'ei.supplier.intake')


@tagged('post_install', '-at_install', 'ei')
class TestVisibleActions(TestJourney):

    def root_attrs(self, user, model, view_type):
        if not self.env[model].with_user(user).has_access('read'):
            return None                                                         # a person who cannot open the screen at all
        try:
            arch = self.env[model].with_user(user).get_view(view_type=view_type)['arch']
        except ValueError:
            return None                                                         # this model has no such view
        return dict(re.findall(r'(\w+)="([^"]*)"', re.search(r'<%s\b[^>]*>' % view_type, arch).group(0)))

    def test_v01_new_is_never_offered_to_someone_who_may_not_create(self):
        users = (self.ceo, self.maker, self.capprover, self.dispatch, self.reviewer, self.cashclerk, self.officer, self.bapprover, self.invoicer, self.rclerk, self.importer)
        offered = denied = 0
        for model in CARD_MODELS:
            for user in users:
                may = self.env[model].with_user(user).has_access('create')
                for view_type in ('kanban', 'list', 'form'):
                    attrs = self.root_attrs(user, model, view_type)
                    if attrs is None:
                        continue
                    shown = attrs.get('create', 'true').lower() not in ('false', '0')
                    if shown:                       # a screen may choose NOT to offer New (an import is done with a wizard), never the reverse
                        self.assertTrue(may, f'{model} {view_type} for {user.login}: New is shown but create access is denied')
                    offered += shown
                    denied += not may
        self.assertTrue(offered and denied, 'the test must cover both people who may create and people who may not')

    def test_v01b_the_people_who_create_still_see_new(self):
        for model, user in (('ei.contract', self.maker), ('ei.da', self.maker), ('ei.cash.voucher', self.cashclerk), ('ei.lifting', self.dispatch), ('ei.supplier.intake', self.invoicer)):
            self.assertTrue(self.env[model].with_user(user).has_access('create'), f'{model} {user.login}')
            self.assertNotIn(self.root_attrs(user, model, 'kanban').get('create', 'true').lower(), ('false', '0'), model)       # access rules unchanged: they still create

    def test_v02_the_ceo_is_not_invited_to_create_what_the_policy_forbids(self):
        for model in CARD_MODELS:
            self.assertFalse(self.env[model].with_user(self.ceo).has_access('create'), model)       # the CEO is view/approve-only on these
            attrs = self.root_attrs(self.ceo, model, 'kanban')
            if attrs is not None:
                self.assertIn(attrs.get('create', 'true').lower(), ('false', '0'), model)
