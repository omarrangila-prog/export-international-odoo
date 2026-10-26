"""Automation rules on the SAME world the end-to-end journey builds (real role users and records, nothing mocked):
order DOR (approved, 10 MTL), 4 MTL lifted, supplier bill, customer invoice paid by a bank receipt."""
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.ei_management_dashboard.tests.test_journey import TestJourney
from odoo.addons.ei_automation.models import recipes
from odoo.addons.ei_automation.models.rule import AUTO_PREFIX


@tagged('post_install', '-at_install', 'ei')
class TestAutomation(TestJourney):

    def rule(self, key, **vals):
        R = self.env['ei.rule']
        r = R.search([('key', '=', key), ('company_id', '=', self.co.id)])
        defaults = {'days': recipes.RECIPES[key]['default_days'], 'repeat_days': 3, 'max_per_run': 20}
        return r or R.create({'key': key, 'company_id': self.co.id, **defaults, **vals})

    def sql_age(self, rec, column, days):
        self.env.cr.execute("UPDATE %s SET %s = %s - interval '%d days' WHERE id = %%s" % (rec._table, column, column, days), (rec.id,))
        rec.invalidate_recordset()

    def acts(self, rec):
        return self.env['mail.activity'].sudo().search([('res_model', '=', rec._name), ('res_id', '=', rec.id), ('summary', '=like', AUTO_PREFIX + '%')])

    def make_unpaid_invoice(self, due_days_ago=20):
        inv = self.init_invoice('out_invoice', partner=self.customer, invoice_date='2026-01-05', amounts=[500000], company=self.co)
        inv.invoice_user_id = self.invoicer
        inv.action_post()
        self.env.cr.execute("UPDATE account_move SET invoice_date_due = %s WHERE id = %s",
                            (fields.Date.today() - timedelta(days=due_days_ago), inv.id))
        inv.invalidate_recordset()
        return inv

    # ------------------------------------------------------------------ safety defaults
    def test_01_every_rule_ships_off_and_the_schedule_ignores_off_rules(self):
        for rec in self.env['ei.rule'].search([]):
            self.assertFalse(rec.enabled, '%s must ship switched off' % rec.key)
        r = self.rule('missing_supplier_invoice')
        self.assertFalse(r.enabled)
        self.sql_age(self.order, 'approved_at', 5)
        self.env['ei.rule'].cron_run_all()
        self.assertFalse(self.env['ei.rule.run'].search([('rule_id', '=', r.id)]), 'a switched-off rule is not run by the schedule')
        with self.assertRaises(UserError):
            r.with_user(self.ceo).action_run()

    # ------------------------------------------------------------------ A17
    def test_02_missing_supplier_invoice_reminds_the_preparer_once(self):
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = NULL")
        self.sql_age(self.order, 'approved_at', 5)
        r = self.rule('missing_supplier_invoice', days=3, enabled=True)
        run = r.with_user(self.ceo)._run('preview')
        self.assertEqual((run.found, run.created), (1, 0), 'preview finds it and creates nothing')
        self.assertEqual(run.finding_ids.status, 'would_remind')
        self.assertFalse(self.acts(self.order))
        run = r.with_user(self.ceo)._run('live')
        self.assertEqual((run.found, run.created), (1, 1))
        act = self.acts(self.order)
        self.assertEqual(act.user_id, self.maker, 'the person who prepared the order is told')
        self.assertIn('Supplier invoice still missing', act.summary)
        self.assertIn('Nothing is booked', act.note)
        # duplicate protection: still open -> not again
        run2 = r.with_user(self.ceo)._run('live')
        self.assertEqual((run2.created, run2.finding_ids.status), (0, 'skipped_open'))
        # closed, but inside the repeat window -> not again
        act.action_feedback(feedback='done')
        run3 = r.with_user(self.ceo)._run('live')
        self.assertEqual((run3.created, run3.finding_ids.status), (0, 'skipped_recent'))
        # outside the repeat window and still missing -> again
        self.env.cr.execute("UPDATE ei_rule_finding SET create_date = create_date - interval '4 days'")
        self.env.invalidate_all()
        self.assertEqual(r.with_user(self.ceo)._run('live').created, 1)

    def test_03_recording_the_invoice_or_a_younger_order_clears_it(self):
        r = self.rule('missing_supplier_invoice', days=3, enabled=True)
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = NULL")
        self.sql_age(self.order, 'approved_at', 1)
        self.assertEqual(r._run('preview').found, 0, 'an order approved yesterday is inside the 3 days')
        self.sql_age(self.order, 'approved_at', 5)
        self.assertEqual(r._run('preview').found, 1)
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = 'SUP-INV-1'")
        self.env.invalidate_all()
        self.assertEqual(r._run('preview').found, 0, 'once the supplier invoice number is recorded there is nothing to chase')

    # ------------------------------------------------------------------ A18
    def test_04_lifting_waiting_looks_at_real_movement_not_invoices(self):
        r = self.rule('lifting_waiting', days=5, enabled=True)
        self.sql_age(self.order, 'approved_at', 8)
        self.assertEqual(r._run('preview').found, 0, '4 MTL were loaded today: the line is moving')
        self.sql_age(self.lift, 'date', 9)
        run = r._run('preview')
        self.assertEqual(run.found, 1)
        live = r.with_user(self.ceo)._run('live')
        act = self.acts(self.order)
        self.assertEqual(live.created, 1)
        self.assertIn('6.000 MTL still to lift', act.note)
        self.assertEqual(act.user_id, self.maker)
        # a supplier invoice number alone does not count as movement
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = 'SUP-INV-1'")
        self.env.invalidate_all()
        act.unlink()
        self.assertEqual(r._run('preview').found, 1)

    # ------------------------------------------------------------------ A19
    def test_05_overdue_collection_drafts_wording_and_sends_nothing(self):
        r = self.rule('overdue_collection', days=7, enabled=True)
        before_mail = self.env['mail.mail'].sudo().search_count([])
        paid_found = [f for f in recipes.overdue_collection(self.env, r) if f.record == self.invoice]
        self.assertFalse(paid_found, 'the invoice that was paid by the bank receipt is never chased')
        inv = self.make_unpaid_invoice(due_days_ago=20)
        run = r.with_user(self.ceo)._run('live')
        self.assertEqual((run.found, run.created), (1, 1))
        act = self.acts(inv)
        self.assertEqual(act.user_id, self.invoicer)
        self.assertIn('Draft reminder', act.note)
        self.assertIn(self.customer.name, act.note)
        self.assertIn(inv.name, act.note)
        self.assertIn('500,000.00', act.note)
        self.assertIn('Nothing is sent to the customer', act.note)
        sent = self.env['mail.mail'].sudo().search([('id', '>', before_mail)])
        users_partners = self.env['res.users'].sudo().search([]).partner_id
        self.assertFalse(sent.filtered(lambda m: m.recipient_ids - users_partners), 'only colleagues were notified, never the customer')
        # not yet overdue -> not chased
        inv2 = self.make_unpaid_invoice(due_days_ago=3)
        self.assertNotIn(inv2, [f.record for f in recipes.overdue_collection(self.env, r)])

    def test_06_collection_reminder_warns_when_unmatched_bank_money_may_cover_it(self):
        r = self.rule('overdue_collection', days=7, enabled=True)
        inv = self.make_unpaid_invoice(due_days_ago=20)
        self.env.cr.execute("UPDATE ei_bank_import_line SET state = 'proposed', suggested_partner_id = %s, partner_id = NULL WHERE id = %s",
                            (self.customer.id, self.bline.id))
        self.env.invalidate_all()
        f = [x for x in recipes.overdue_collection(self.env, r) if x.record == inv][0]
        self.assertIn('waiting to be matched', f.note)
        self.assertIn('may already cover it', f.note)

    # ------------------------------------------------------------------ A24
    def test_07_anomalies_go_to_every_manager(self):
        r = self.rule('critical_anomaly', days=1, enabled=True)
        self.assertEqual(r._run('preview').found, 0, 'no problem, no reminder')
        self.env.cr.execute("UPDATE ei_bank_import_line SET state = 'duplicate' WHERE id = %s", (self.bline.id,))
        self.env.invalidate_all()
        live = r.with_user(self.ceo)._run('live')
        self.assertEqual(live.created, 1)
        act = self.acts(self.bline)
        self.assertEqual(act.user_id, self.ceo)
        self.assertIn('Possible duplicate bank payment', act.summary)

    # ------------------------------------------------------------------ the cap, failures, owners
    def test_08_the_cap_limits_one_run(self):
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = NULL")
        self.sql_age(self.order, 'approved_at', 5)
        inv = self.make_unpaid_invoice(20)
        r = self.rule('overdue_collection', days=7, enabled=True, max_per_run=1)
        self.make_unpaid_invoice(30)
        run = r.with_user(self.ceo)._run('live')
        self.assertEqual((run.found, run.created), (2, 1))
        self.assertEqual(sorted(run.finding_ids.mapped('status')), ['reminded', 'skipped_cap'])
        self.assertTrue(inv)

    def test_09_one_failing_recipe_does_not_stop_the_others(self):
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = NULL")
        self.sql_age(self.order, 'approved_at', 5)
        bad = self.rule('critical_anomaly', enabled=True)
        good = self.rule('missing_supplier_invoice', days=3, enabled=True)
        boom = lambda env, rule: (_ for _ in ()).throw(RuntimeError('boom'))
        with patch.dict(recipes.RECIPES['critical_anomaly'], {'find': boom}):
            self.env['ei.rule'].cron_run_all()
        self.assertIn('boom', bad.run_ids.errors)
        self.assertEqual(good.run_ids.created, 1, 'the healthy rule still ran')
        self.assertEqual(good.run_ids.mode, 'cron')

    def test_10_a_reminder_goes_only_to_someone_who_can_open_the_record(self):
        self.env.cr.execute("UPDATE ei_daily_order_line SET invoice_ref = NULL")
        self.sql_age(self.order, 'approved_at', 5)
        self.maker.active = False                                  # the preparer has left
        r = self.rule('missing_supplier_invoice', days=3, enabled=True)
        f = recipes.missing_supplier_invoice(self.env, r)[0]
        self.assertNotIn(self.maker, f.owners)
        self.assertIn(self.ceo, f.owners, 'the managers are told instead')
        self.assertFalse(self.cashclerk in f.owners)

    # ------------------------------------------------------------------ who may change the switchboard (T12-style)
    def test_11_only_management_can_change_or_run_a_rule_and_changes_are_logged(self):
        r = self.rule('missing_supplier_invoice')
        for user in (self.cashclerk, self.maker, self.capprover):
            with self.assertRaises(AccessError):
                r.with_user(user).write({'enabled': True})
            with self.assertRaises(AccessError):
                r.with_user(user).action_preview()
            with self.assertRaises(AccessError):
                self.env['ei.rule'].with_user(user).create({'key': 'lifting_waiting', 'company_id': self.co.id})
        count = lambda: self.env['mail.message'].sudo().search_count([('model', '=', 'ei.rule'), ('res_id', '=', r.id)])
        n = count()
        r.with_user(self.ceo).with_context(tracking_disable=False, mail_notrack=False).write({'enabled': True, 'days': 4})
        self.env.cr.precommit.run()                      # Odoo writes tracking messages just before commit
        self.assertGreater(count(), n, 'switching a rule on or changing its numbers leaves a trace')
        self.assertEqual(r.days, 4)
        with self.assertRaises(UserError):
            r.with_user(self.ceo).write({'max_per_run': 0})
        # runs and findings cannot be edited by anyone through the screen
        run = r.with_user(self.ceo)._run('preview')
        with self.assertRaises(AccessError):
            run.with_user(self.ceo).write({'found': 99})
        self.assertTrue(run.with_user(self.ceo).read(['found']))

    def test_12_another_company_cannot_see_the_rules(self):
        r = self.rule('missing_supplier_invoice')
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.ceo.write({'company_ids': [(4, other.id)]})
        self.assertFalse(self.env['ei.rule'].with_user(self.ceo).with_context(allowed_company_ids=[other.id]).search([('id', '=', r.id)]))

    def test_13_every_recipe_explains_itself(self):
        for key, rec in recipes.RECIPES.items():
            self.assertTrue(rec['code'].startswith('A'), key)
            for field in ('checks', 'does', 'owner_text', 'days_label', 'name'):
                self.assertTrue(str(rec[field]), '%s lacks %s' % (key, field))
            r = self.rule(key)
            self.assertIn('never does', r.explanation)
            self.assertIn('does not post, pay, send anything outside the company', r.explanation)
