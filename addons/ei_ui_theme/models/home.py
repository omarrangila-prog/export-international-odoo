"""Data behind the Home page, in three layers: (1) summary figures, (2) the action centre - alerts, My Work, grouped
quick actions, (3) insight - pipeline, charts, recent activity.

Everything here is read-only counting / aggregation on records the current user may see. A section the role cannot
see is ABSENT, never shown as a false zero. Every figure has an `open_*` method that opens the records behind it.
The role profile only decides which figures lead and in which order; it never grants access (the ORM does)."""
import re
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import html2plaintext
from odoo.tools.misc import format_amount, format_date

from .labels import LABELS
from .work import WORK, OVERDUE_DEFAULT, OVERDUE_PARAM

KANBAN_MODELS = {'ei.bank.import', 'ei.cash.voucher', 'ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting',
                 'ei.supplier.intake', 'ei.parent.statement'}
CHART_DAYS = 14
ACTIVITY_ITEMS = 8

# key, icon, label, hint, model, domain, tone when > 0, area   (used by alerts, pipeline and the task click-through)
TASKS = [
    ('bank_lines', 'fa-university', "Bank payments to check", "Match each payment to the right party",
     'ei.bank.import.line', [('state', 'in', ('new', 'proposed'))], 'warning', 'money'),
    ('bank_approve', 'fa-check-square-o', "Bank statements to approve", "A second person must approve before posting",
     'ei.bank.import', [('state', 'in', ('received', 'validated', 'proposed'))], 'warning', 'money'),
    ('bank_post', 'fa-paper-plane-o', "Bank statements ready to post", "Approved - waiting to go into the books",
     'ei.bank.import', [('state', '=', 'approved')], 'warning', 'money'),
    ('vouchers', 'fa-money', "Cash vouchers to approve", "Cash paid out or received, waiting for a check",
     'ei.cash.voucher', [('state', '=', 'submitted')], 'warning', 'money'),
    ('contracts', 'fa-file-text-o', "Contracts waiting for approval", "Reviewed - needs a second person",
     'ei.contract', [('state', '=', 'reviewed')], 'warning', 'orders'),
    ('das', 'fa-truck', "Delivery advices waiting for approval", "Check quantities and rates",
     'ei.da', [('state', '=', 'under_review')], 'warning', 'orders'),
    ('orders', 'fa-list-alt', "Daily orders to approve", "Approve, then print or email",
     'ei.daily.order', [('state', '=', 'draft')], 'warning', 'orders'),
    ('liftings', 'fa-balance-scale', "Truck loadings to verify", "Check the gate pass and weighbridge slip",
     'ei.lifting', [('state', '=', 'draft')], 'warning', 'orders'),
    ('intake', 'fa-exclamation-triangle', "Supplier invoices with a problem", "Quantity, rate or total does not match",
     'ei.supplier.intake', [('state', '=', 'mismatch')], 'danger', 'bills'),
    ('to_invoice', 'fa-file-o', "Delivered material not yet invoiced", "Verified loadings ready to invoice",
     'ei.lifting', [('invoice_status', '=', 'to_invoice')], 'warning', 'bills'),
    ('recon', 'fa-balance-scale', "Differences with the parent company", "Month-end ledger items to resolve",
     'ei.parent.statement.line', [('status', '!=', 'matched'), ('resolution_state', '=', 'open')], 'warning', 'month'),
    ('codes', 'fa-tags', "Old codes waiting to be classified", "An accountant decides what each one becomes",
     'ei.legacy.code', [('verification_status', 'in', ('proposed', 'needs_review'))], 'info', 'setup'),
]
TASK_BY_KEY = {t[0]: t for t in TASKS}

# key, icon, label, hint, group, kind, target, model   (kind: wizard/list open a window action by xml id, form opens a new record)
QUICK = [
    ('q_bank', 'fa-upload', "Import a bank statement", "Upload the bank's statement file", 'money', 'wizard',
     'ei_bank_operations.ei_bank_import_wizard_action', 'ei.bank.import.wizard'),
    ('q_voucher', 'fa-money', "New cash voucher", "Cash paid out or received", 'money', 'form', 'ei.cash.voucher', 'ei.cash.voucher'),
    ('q_contract', 'fa-file-text-o', "New contract", "Enter a parent-company contract", 'contracts', 'form', 'ei.contract', 'ei.contract'),
    ('q_da', 'fa-truck', "New delivery advice", "Copy a DA from the parent company", 'contracts', 'form', 'ei.da', 'ei.da'),
    ('q_lift', 'fa-balance-scale', "Record a truck loading", "Gate pass and weighbridge slip", 'orders', 'form', 'ei.lifting', 'ei.lifting'),
    ('q_orders', 'fa-list-alt', "Daily orders", "Today's order requests", 'orders', 'list', 'ei_daily_orders.ei_daily_order_action', 'ei.daily.order'),
    ('q_intake', 'fa-inbox', "Enter a supplier invoice", "Checked against the delivery advice", 'bills', 'form', 'ei.supplier.intake', 'ei.supplier.intake'),
    ('q_invoice', 'fa-file-o', "Invoice delivered material", "One click creates the customer invoices", 'bills', 'list',
     'ei_invoice_extensions.ei_billable_action', 'ei.invoice.wizard'),
    ('q_banklines', 'fa-university', "Bank payments to check", "Match each payment to the right party", 'review', 'list',
     'ei_bank_operations.ei_bank_line_action', 'ei.bank.import.line'),
    ('q_parent', 'fa-upload', "Import parent statement", "Compare the parent company's ledger with ours", 'review', 'wizard',
     'ei_parent_reconciliation.ei_parent_import_wizard_action', 'ei.parent.import.wizard'),
    ('q_balance', 'fa-university', "Confirm bank balances", "Type what the bank says, morning check", 'daily', 'list',
     'ei_bank_operations.ei_balance_check_action', 'ei.bank.balance.check'),
    ('q_cash', 'fa-money', "Count the cash", "Cash in the box against the books", 'daily', 'list',
     'ei_cashbook.ei_cash_count_action', 'ei.cash.count'),
    ('q_codes_import', 'fa-upload', "Import old codes", "Load the code list file (safe to repeat)", 'setup', 'wizard',
     'ei_legacy_master.ei_import_wizard_action', 'ei.import.wizard'),
    ('q_codes', 'fa-tags', "Classify old codes", "Decide what each old code becomes", 'setup', 'list',
     'ei_legacy_master.ei_legacy_code_queue_action', 'ei.legacy.code'),
]
QUICK_GROUPS = [('money', "Money"), ('contracts', "Contracts & delivery advice"), ('orders', "Orders & lifting"),
                ('bills', "Bills & invoices"), ('review', "Exceptions & review"), ('daily', "Daily work"),
                ('setup', "Setup")]

# role profile: first match wins. It decides which figures lead and in which order, never what a user may open.
PROFILES = [
    ('executive', "Executive view", ('ei_management_dashboard.group_ei_management',)),
    ('finance', "Finance manager", ('account.group_account_manager', 'ei_bank_operations.group_ei_bank_approver',
                                    'ei_cashbook.group_ei_cash_approver')),
    ('accountant', "Accountant", ('account.group_account_user', 'ei_bank_operations.group_ei_bank_poster',
                                  'ei_parent_reconciliation.group_ei_recon_user', 'ei_invoice_extensions.group_ei_invoicing')),
    ('logistics', "Logistics", ('ei_material_lifting.group_ei_dispatch_officer', 'ei_material_lifting.group_ei_lifting_reviewer')),
    ('contract', "Contract desk", ('ei_contract_da.group_ei_contract_staff', 'ei_contract_da.group_ei_contract_approver',
                                   'ei_daily_orders.group_ei_order_approver')),
    ('data_entry', "Data entry", ('ei_bank_operations.group_ei_bank_officer', 'ei_cashbook.group_ei_cash_clerk',
                                  'ei_legacy_master.group_ei_importer')),
    ('admin', "System administrator", ('base.group_system',)),
    ('general', "Staff", ('ei_legacy_master.group_ei_user',)),
]
PROFILE_KPIS = {
    'executive': ['bank', 'ar', 'ap', 'collected', 'waiting', 'cash', 'spread', 'recon'],
    'finance': ['bank', 'ar', 'ap', 'collected', 'waiting', 'cash', 'recon'],
    'accountant': ['bank', 'ar', 'ap', 'collected', 'waiting', 'recon'],
    'logistics': ['k_verify', 'k_left', 'k_orders', 'k_toinvoice'],
    'contract': ['k_contracts', 'k_das', 'k_left', 'k_orders'],
    'data_entry': ['k_banklines', 'k_vouchers', 'k_intake', 'k_toinvoice'],
    'admin': [],
    'general': ['k_contracts', 'k_left'],
}
PROFILE_LAYOUT = {
    # the "New" menu in the header holds the starting points; the launcher section stays only where starting things IS the job.
    # The three money roles open on a summary strip and one block of "what needs you" (alerts + decisions): the first screen is the work.
    'executive': ['summary', 'decide', 'hero', 'flows', 'recent', 'kpis', 'work', 'charts', 'activity'],
    'finance': ['summary', 'decide', 'hero', 'flows', 'recent', 'kpis', 'work', 'charts', 'activity'],
    'accountant': ['summary', 'decide', 'hero', 'flows', 'recent', 'kpis', 'work', 'charts', 'activity'],
    'logistics': ['work', 'kpis', 'quick', 'hero', 'flows', 'alerts', 'recent', 'activity', 'charts'],
    'contract': ['work', 'kpis', 'quick', 'hero', 'flows', 'alerts', 'recent', 'activity', 'charts'],
    'data_entry': ['work', 'quick', 'kpis', 'alerts', 'hero', 'recent', 'activity', 'charts', 'flows'],
    'admin': ['system', 'alerts', 'quick', 'hero', 'activity', 'work', 'recent', 'charts', 'kpis', 'flows'],
    'general': ['work', 'kpis', 'quick', 'hero', 'alerts', 'flows', 'recent', 'activity', 'charts'],
}


BANK_STALE_RED_DAYS = 3        # a bank confirmation this old is urgent (red); older than today is already amber


def _n(n, one, many):
    """'1 loading' / '2 loadings' with the number filled in."""
    return (one if n == 1 else many) % n


class EiHome(models.AbstractModel):
    _name = 'ei.home'
    _description = 'Home page data'

    def _register_hook(self):
        """Apply plain-language labels after the registry is built. Odoo serves field labels from ir_model_fields, so
        the database copy is updated (only when different) and the Python field label is kept in step."""
        cr = self.env.cr
        for model, labels in LABELS.items():
            if model not in self.env:
                continue
            for name, label in labels.items():
                field = self.env[model]._fields.get(name)
                if field is None:
                    continue
                field.string = label
                cr.execute(
                    """UPDATE ir_model_fields SET field_description = field_description || jsonb_build_object('en_US', %s::text)
                        WHERE model = %s AND name = %s AND COALESCE(field_description->>'en_US', '') <> %s""",
                    (label, model, name, label))
        return super()._register_hook()

    # ------------------------------------------------------------------ helpers
    def _count(self, model, domain):
        if model not in self.env:
            return None
        try:
            return self.env[model].search_count(domain)
        except AccessError:
            return None

    def _fmt(self, amount):
        return format_amount(self.env, amount or 0.0, self.env.company.currency_id)

    def _can(self, model, op='read'):
        return model in self.env and self.env[model].has_access(op)

    @api.model
    def _views_for(self, model):
        return [[False, 'kanban'], [False, 'list'], [False, 'form']] if model in KANBAN_MODELS else [[False, 'list'], [False, 'form']]

    def _profile(self):
        user = self.env.user
        for key, label, groups in PROFILES:
            if any(user.has_group(g) for g in groups):
                return key, label
        return 'general', "Staff"

    def _dash(self):
        """A transient dashboard record: the single place the money figures are worked out (same numbers as the
        Detailed report). None when the user may not use it."""
        D = self.env['ei.dashboard']
        return D.create({}) if D.has_access('create') else None

    def _allowed(self, section):
        return self.env['ei.dashboard']._allowed(section)

    def _finance_ok(self):
        return self._allowed('finance') or self.env.user.has_group('ei_legacy_master.group_ei_auditor')

    # ------------------------------------------------------------------ the page
    @api.model
    def get_data(self, period=None):
        env, user = self.env, self.env.user
        now = fields.Datetime.context_timestamp(self, datetime.now())
        profile, role_label = self._profile()
        dash = self._dash()
        work = env['ei.work'].tasks()
        kpis = self._kpis(profile, dash)
        alerts = self._alerts()
        quick = self._quick()
        # bank balances are a finance figure: the people who enter bank lines see what they entered, not what the banks hold
        banks = self._banks() if self._finance_ok() else []
        data = {
            'profile': profile, 'layout': PROFILE_LAYOUT[profile],
            'header': self._header(now, role_label, work, alerts, dash),
            'kpis': kpis, 'alerts': alerts, 'work': work, 'quick': quick,
            'pipeline': self._pipeline(dash), 'charts': self._charts(dash), 'activity': self._activity(),
            'system': self._system() if user.has_group('base.group_system') else None,
            'banks': banks, 'banks_total': self._fmt(sum(b['amount'] for b in banks)) if banks else '', 'steps': self._day_steps(),
            'period': self._period_info(period), 'flows': self._flows(period), 'top_owing': self._top_owing(dash), 'recent': self._recent(),
        }
        data['empty'] = not (kpis or work['items'] or quick or alerts)
        return data

    # ------------------------------------------------------------------ header
    def _header(self, now, role_label, work, alerts, dash):
        env, user = self.env, self.env.user
        bank_at = ''
        if self._allowed('bank') and 'ei.bank.balance.check' in env:
            chk = env['ei.bank.balance.check'].sudo().search([('company_id', 'in', env.companies.ids)] if 'company_id' in env['ei.bank.balance.check']._fields else [],
                                                           order='entered_at desc', limit=1)
            if chk:
                bank_at = fields.Datetime.context_timestamp(self, chk.entered_at).strftime('%d %b %H:%M')
        approvals = sum(1 for t in work['items'] if t['can_act'] and t['type'] in (
            'contract_approve', 'da_approve', 'order_approve', 'lifting_verify', 'voucher_approve', 'bank_approve', 'bank_post',
            'recon_signoff', 'formula_approve'))
        reminders = env['mail.activity'].search_count([('user_id', '=', user.id)])
        return {
            'company': env.company.name, 'user': user.name, 'first_name': (user.name or '').split(' ')[0], 'role': role_label,
            'date': now.strftime('%A, %d %B %Y'), 'time': now.strftime('%H:%M'),
            'bank_confirmed': bank_at, 'approvals': approvals, 'reminders': reminders,
            'attention': sum(a['count'] for a in alerts if a['severity'] in ('danger', 'warning')),
            'greeting': _("Good morning") if now.hour < 12 else _("Good afternoon") if now.hour < 17 else _("Good evening"),
        }

    # ------------------------------------------------------------------ layer 1: figures
    def _kpis(self, profile, dash):
        env, today = self.env, fields.Date.context_today(self)
        fin = dash is not None and self._finance_ok()
        bank_ok = dash is not None and self._allowed('bank')
        out = {}
        if fin:
            ledger_ar = dash.ar_open
            overdue = ledger_ar - dash.aging_current
            out['ar'] = dict(label=_("Customers owe us"), value=self._fmt(ledger_ar), icon='in', tone='warning' if overdue > 0 else 'neutral',
                             sub=(_("%s of it is overdue", self._fmt(overdue)) if overdue > 0 else _("Nothing is overdue")),
                             basis=_("Posted in the books"),
                             help=_("Open receivable items of posted customer invoices, from the ledger. Overdue = past its due date."))
            out['ap'] = dict(label=_("We owe suppliers"), value=self._fmt(dash.ap_open), icon='out', tone='neutral',
                             sub=_("Unpaid supplier bills"), basis=_("Posted in the books"),
                             help=_("Open payable items of posted supplier bills, from the ledger."))
            cash = dash.cash_position
            out['cash'] = dict(label=_("Cash in hand"), value=self._fmt(cash), icon='cash', tone='danger' if cash < 0 else 'neutral',
                               sub=(_("Below zero: the books show more paid out of the cash boxes than was put in. Check the cash count.") if cash < 0
                                    else _("Cash boxes, according to the books")), basis=_("Posted in the books"),
                               help=_("Posted entries on the cash accounts. A negative figure is never normal: it means vouchers or receipts are missing or mis-dated."))
        if fin or bank_ok:
            journals = dash._bank_journals() if dash else env['account.journal']
            if journals:
                total = sum(j._ei_ledger_balance(today) for j in journals)
                checked = env['ei.bank.balance.check'].sudo().search([('date', '=', today), ('journal_id', 'in', journals.ids),
                                                                      ('state', 'in', ('matched', 'explained'))]).journal_id
                tone = 'ok' if len(checked) == len(journals) else 'warning'
                out['bank'] = dict(label=_("Bank balances"), value=self._fmt(total), icon='bank', tone=tone,
                                   sub=_("%(a)s of %(b)s banks confirmed with the bank today", a=len(checked), b=len(journals)),
                                   basis=_("Books, checked against the bank"),
                                   help=_("The BOOK balance of the bank accounts. It is only bank-confirmed when someone has typed what the bank says and the two agree."))
        if self._can('ei.bank.import.line') and (bank_ok or fin):
            L = env['ei.bank.import.line']
            got = L.search([('state', '=', 'posted'), ('amount', '>', 0), ('date', '=', today)])
            out['collected'] = dict(label=_("Collected today"), value=self._fmt(sum(got.mapped('amount'))), icon='in',
                                    tone='ok' if got else 'neutral',
                                    sub=(_n(len(got), _("%s receipt posted"), _("%s receipts posted")) if got else _("No receipts posted yet today")),
                                    basis=_("Bank-confirmed and posted"),
                                    help=_("Bank receipts dated today that a person matched and a second person posted."))
            pend = L.search([('state', 'in', ('new', 'proposed', 'verified', 'unidentified')), ('amount', '>', 0)])
            out['waiting'] = dict(label=_("Bank money to match"), value=self._fmt(sum(pend.mapped('amount'))), icon='alert',
                                  tone='warning' if pend else 'ok', sub=(_n(len(pend), _("%s payment needs a person to confirm the payer"), _("%s payments need a person to confirm the payer")) if pend else _("Nothing waiting")),
                                  basis=_("Waiting for a person"),
                                  help=_("Incoming bank lines not yet matched to a party and posted. They are not in the books yet."))
        if fin:
            out['spread'] = dict(label=_("Expected gross spread"), value=self._fmt(dash.gross_spread), icon='chart', tone='neutral',
                                 sub=_("On active contracts, before costs and taxes. Not profit."), basis=_("Provisional"),
                                 help=_("Ordered MTL x (sale rate - purchase rate), summed over active contract lines. Before commission, costs and taxes; provisional until the tax and commission basis is approved. Not net profit."))
        if self._can('ei.parent.statement.line'):
            diffs = env['ei.parent.statement.line'].search(TASK_BY_KEY['recon'][5])
            total = sum(abs(d.difference) for d in diffs)
            out['recon'] = dict(label=_("Differences with parent companies"), value=str(len(diffs)), icon='scale',
                                tone='warning' if diffs else 'ok',
                                sub=(_("Worth %s in total") % self._fmt(total) if diffs else _("Everything agrees")),
                                basis=_("Waiting for a person"))
        # operations figures
        ops = {
            'k_contracts': ('ei.contract', [('state', 'in', ('approved', 'active'))], _("Active contracts"), 'doc',
                            lambda n: _("%s waiting for approval", env['ei.contract'].search_count([('state', '=', 'reviewed')]))),
            'k_das': ('ei.da', [('state', '=', 'under_review')], _("Delivery advices to approve"), 'truck',
                      lambda n: _("%s approved and open", env['ei.da'].search_count([('state', '=', 'approved')]))),
            'k_verify': ('ei.lifting', [('state', '=', 'draft')], _("Truck loadings to verify"), 'scale',
                         lambda n: _("Check each gate pass and weighbridge slip")),
            'k_toinvoice': ('ei.lifting', [('invoice_status', '=', 'to_invoice')], _("Delivered, not yet invoiced"), 'doc',
                            lambda n: _("Verified loadings ready to invoice")),
            'k_banklines': ('ei.bank.import.line', [('state', 'in', ('new', 'proposed', 'unidentified'))], _("Bank payments to check"), 'bank',
                            lambda n: _("Match each payment to the right party")),
            'k_vouchers': ('ei.cash.voucher', [('state', '=', 'submitted')], _("Cash vouchers waiting for approval"), 'cash',
                           lambda n: _("A second person must approve them")),
            'k_intake': ('ei.supplier.intake', [('state', '=', 'mismatch')], _("Supplier invoices with a problem"), 'alert',
                         lambda n: _("Quantity, rate or total does not match")),
        }
        for key, (model, dom, label, icon, sub) in ops.items():
            if self._can(model):
                n = env[model].search_count(dom)
                bad = key in ('k_intake',)
                out[key] = dict(label=label, value=str(n), icon=icon, tone=('danger' if bad else 'warning') if n else 'ok', sub=sub(n),
                                basis=_("Waiting for a person"))
        mat = self._material()
        if mat and mat.get('ordered') and (self._allowed('ops') or fin):
            out['k_left'] = dict(label=_("Still to lift"), value='{:,.3f} MTL'.format(max(mat['allocated'] - mat['lifted'], 0.0)), icon='truck',
                                 tone='info', sub=_("%(a)s MTL promised, %(l)s MTL truly lifted", a=mat['allocated'], l=mat['lifted']),
                                 basis=_("Approved minus verified"))
        if self._can('ei.daily.order.line') and any(k in PROFILE_KPIS.get(profile, ()) for k in ('k_orders',)):
            lines = env['ei.daily.order.line'].search([('state', '=', 'approved')], limit=500).filtered(lambda l: l.remaining_mtl > 0.0005)
            out['k_orders'] = dict(label=_("Open daily orders"), value=str(len(lines.mapped('order_id'))), icon='list',
                                   tone='info', sub=_("%.3f MTL still to lift", sum(lines.mapped('remaining_mtl'))), basis=_("Approved documents"))
        ordered = [dict(key=k, **out[k]) for k in PROFILE_KPIS.get(profile, []) if k in out]
        return ordered

    # ------------------------------------------------------------------ layer 2: alerts (never invented)
    def _alerts(self):
        env, today = self.env, fields.Date.context_today(self)
        alerts = []

        # what a person does next, in verb + object words, and how long the oldest item has waited
        ctas = {'dup_payment': _("Review duplicates"), 'unidentified': _("Identify the payer"), 'intake_mismatch': _("Review the mismatch"),
                'rate_diff': _("Check the rates"), 'missing_docs': _("Attach the paper"), 'overdue_approvals': _("Open the oldest"),
                'recon': _("Resolve the differences"), 'bank_diff': _("Find the difference"), 'bank_stale': _("Confirm the balances")}

        def oldest(model, dom):
            first = env[model].search(dom, order='create_date asc', limit=1)
            return _("oldest waiting %s days", (fields.Date.context_today(self) - first.create_date.date()).days) if first else ''
        ages = {}
        if self._can('ei.bank.import.line'):
            ages['dup_payment'] = oldest('ei.bank.import.line', [('state', '=', 'duplicate')])
            ages['unidentified'] = oldest('ei.bank.import.line', [('state', '=', 'unidentified')])
        if self._can('ei.supplier.intake'):
            ages['intake_mismatch'] = oldest('ei.supplier.intake', [('state', '=', 'mismatch')])

        def add(key, severity, label, count, detail, model=None, domain=None):
            if count:
                alerts.append({'key': key, 'severity': severity, 'label': label, 'count': count, 'detail': detail, 'cta': ctas.get(key, ''), 'age': ages.get(key, '')})
        if self._can('ei.bank.import.line'):
            L = env['ei.bank.import.line']
            add('dup_payment', 'danger', _("Possible duplicate bank payments"), L.search_count([('state', '=', 'duplicate')]),
                _("The same bank line appeared twice. Do not post both."))
            add('unidentified', 'warning', _("Bank receipts nobody has identified"), L.search_count([('state', '=', 'unidentified')]),
                _("Money arrived but nobody knows who paid. It stays out of the books until someone confirms."))
        if self._can('ei.supplier.intake'):
            add('intake_mismatch', 'danger', _("Supplier invoices that do not match"), env['ei.supplier.intake'].search_count([('state', '=', 'mismatch')]),
                _("Quantity, rate or total differs from the delivery advice. They are blocked until someone reviews them."))
        if self._can('ei.da.line'):
            lines = env['ei.da.line'].search([('state', '=', 'approved')], limit=500)
            diff = lines.filtered(lambda l: l.contract_line_id and (abs(l.purchase_rate - l.contract_line_id.purchase_rate) > 0.005
                                                                     or abs(l.sale_rate - l.contract_line_id.sale_rate) > 0.005))
            add('rate_diff', 'warning', _("Delivery advice rates that differ from the contract"), len(diff),
                _("A delivery advice line carries a purchase or sale rate that is not the contract rate. Check the reason."))
        missing = 0
        for model, dom in (('ei.supplier.intake', [('state', 'in', ('draft', 'mismatch'))]), ('ei.lifting', [('state', '=', 'draft')])):
            if self._can(model):
                recs = env[model].search(dom, limit=200)
                if recs:
                    have = {r['res_id'] for r in env['ir.attachment'].sudo().search_read([('res_model', '=', model), ('res_id', 'in', recs.ids)], ['res_id'])}
                    missing += len([r for r in recs if r.id not in have])
        add('missing_docs', 'warning', _("Records waiting without any attached paper"), missing,
            _("Supplier invoices and truck loadings need their paper (invoice, gate pass, weighbridge slip) before they can be checked."))
        overdue_days = env['ei.work']._overdue_days()
        limit_dt = fields.Datetime.now() - timedelta(days=overdue_days)
        stuck = 0
        for spec in WORK:
            if spec['key'] in ('bank_check', 'to_invoice', 'recon_diff', 'code_classify', 'intake_problem'):
                continue
            if self._can(spec['model']):
                stuck += env[spec['model']].search_count(spec['domain'] + [('write_date', '<', limit_dt)])
        add('overdue_approvals', 'warning', _("Approvals waiting too long"), stuck,
            _("Waiting %s days or more for a decision. The number of days is a setting.", int(overdue_days)))
        if self._can('ei.parent.statement.line'):
            n = env['ei.parent.statement.line'].search_count(TASK_BY_KEY['recon'][5])
            add('recon', 'warning', _("Open differences with parent companies"), n,
                _("The parent company's ledger and ours disagree. They stay visible until someone resolves them."))
        if self._finance_ok() or self._allowed('bank'):
            stale = [b for b in self._banks() if b['stale']] if self._finance_ok() else []
            if stale:
                worst = max((b['age_days'] if b['age_days'] is not None else 999) for b in stale)
                ages['bank_stale'] = _("never confirmed") if worst == 999 else _("oldest confirmation %s days ago", worst)
                add('bank_stale', 'danger' if worst >= BANK_STALE_RED_DAYS else 'warning', _("Bank balances not confirmed with the bank today"), len(stale),
                    _("The books show what our ledger holds; only the bank can confirm it. Until someone types the bank's own balance, the figure is a book balance."))
        if self._allowed('bank') and 'ei.bank.balance.check' in env:
            for_banks = env['ei.dashboard']._bank_journals() if self._allowed('bank') else env['account.journal']
            diff_checks = env['ei.bank.balance.check'].sudo().search([('date', '=', today), ('journal_id', 'in', for_banks.ids), ('state', '=', 'difference')])
            add('bank_diff', 'danger', _("Bank balances that do not agree with the books today"), len(diff_checks),
                _("The balance the bank gave is different from our ledger. Find the missing or extra entries."))
        order = {'danger': 0, 'warning': 1, 'info': 2}
        alerts.sort(key=lambda a: (order[a['severity']], -a['count']))
        return alerts

    # ------------------------------------------------------------------ quick actions, grouped
    def _quick(self):
        env, groups = self.env, []
        for gkey, glabel in QUICK_GROUPS:
            items = []
            for key, icon, label, hint, group, kind, target, model in QUICK:
                if group != gkey or model not in env:
                    continue
                try:
                    ok = env[model].has_access('create' if kind in ('form', 'wizard') else 'read')
                except AccessError:
                    ok = False
                if ok:
                    items.append({'key': key, 'icon': icon, 'label': label, 'hint': hint})
            if items:
                groups.append({'key': gkey, 'label': glabel, 'items': items})
        return groups

    # ------------------------------------------------------------------ layer 3: pipeline, charts, activity
    def _pipeline(self, dash):
        env = self.env
        stages = []

        def stage(key, label, model, main_dom, main_text, sub_dom, sub_text, icon, tone_if_sub='warning'):
            if not self._can(model):
                return
            n = env[model].search_count(main_dom)
            s = env[model].search_count(sub_dom) if sub_dom is not None else 0
            stages.append({'key': key, 'label': label, 'icon': icon, 'count': n, 'main': main_text(n),
                           'sub': sub_text(s) if s else _("Nothing waiting"), 'tone': tone_if_sub if s else 'ok', 'waiting': s})
        stage('contract', _("Contracts"), 'ei.contract', [('state', 'in', ('approved', 'active'))], lambda n: _("%s active", n),
              [('state', '=', 'reviewed')], lambda s: _("%s to approve", s), 'doc')
        stage('da', _("Delivery advices"), 'ei.da', [('state', '=', 'approved')], lambda n: _("%s approved", n),
              [('state', '=', 'under_review')], lambda s: _("%s to approve", s), 'truck')
        stage('order', _("Daily orders"), 'ei.daily.order', [('state', '=', 'approved')], lambda n: _("%s approved", n),
              [('state', '=', 'draft')], lambda s: _("%s to approve", s), 'list')
        stage('lifting', _("Material lifting"), 'ei.lifting', [('state', '=', 'verified')], lambda n: _n(n, _("%s loading verified"), _("%s loadings verified")),
              [('state', '=', 'draft')], lambda s: _("%s to verify", s), 'scale')
        stage('supplier', _("Supplier invoices"), 'ei.supplier.intake', [('state', '=', 'billed')], lambda n: _("%s billed", n),
              [('state', 'in', ('draft', 'mismatch'))], lambda s: _("%s to resolve", s), 'inbox')
        stage('invoice', _("Customer invoices"), 'ei.lifting', [('invoice_status', '=', 'invoiced')], lambda n: _n(n, _("%s loading invoiced"), _("%s loadings invoiced")),
              [('invoice_status', '=', 'to_invoice')], lambda s: _("%s to invoice", s), 'doc')
        if self._finance_ok() and self._can('account.move'):
            n = env['account.move'].search_count([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('payment_state', 'in', ('not_paid', 'partial'))])
            m = self._count('ei.bank.import.line', [('state', 'in', ('new', 'proposed', 'verified', 'unidentified')), ('amount', '>', 0)]) or 0
            stages.append({'key': 'payment', 'label': _("Payment"), 'icon': 'cash', 'count': n, 'main': _n(n, _("%s unpaid invoice"), _("%s unpaid invoices")),
                           'sub': _n(m, _("%s bank payment to match"), _("%s bank payments to match")) if m else _("Nothing waiting"), 'tone': 'warning' if m else 'ok', 'waiting': m})
        elif self._can('ei.bank.import.line'):
            m = env['ei.bank.import.line'].search_count([('state', 'in', ('new', 'proposed', 'verified', 'unidentified')), ('amount', '>', 0)])
            stages.append({'key': 'payment', 'label': _("Payment"), 'icon': 'cash', 'count': m, 'main': _n(m, _("%s bank payment"), _("%s bank payments")),
                           'sub': _("to match") if m else _("Nothing waiting"), 'tone': 'warning' if m else 'ok', 'waiting': m})
        stage('recon', _("Reconciliation"), 'ei.parent.statement.line', TASK_BY_KEY['recon'][5], lambda n: _n(n, _("%s open difference"), _("%s open differences")),
              [('statement_id.state', '=', 'resolved')], lambda s: _("%s to sign off", s), 'scale')
        # each step counts its own kind of record: the counts are NOT one series and must never be joined by a line
        defs = {
            'contract': (_("Contracts that are approved or active."), _("Waiting: reviewed, not yet approved.")),
            'da': (_("Delivery advices that are approved."), _("Waiting: still under review.")),
            'order': (_("Daily orders that are approved."), _("Waiting: still a draft.")),
            'lifting': (_("Truck loadings that a reviewer verified."), _("Waiting: draft, not yet verified.")),
            'supplier': (_("Supplier invoices that matched their delivery advice and were billed."), _("Waiting: draft, or a mismatch to resolve.")),
            'invoice': (_("Verified truck loadings already invoiced to the customer."), _("Waiting: verified loadings not yet invoiced.")),
            'payment': (_("Posted customer invoices that are not fully paid (bank payments for roles without finance)."), _("Waiting: incoming bank payments not yet matched to a party.")),
            'recon': (_("Open differences between a parent company's ledger and ours."), _("Waiting: resolved statements that still need a sign-off.")),
        }
        for st in stages:
            st['definition'], st['waiting_def'] = defs.get(st['key'], ('', ''))
        return stages

    def _charts(self, dash):
        env, today = self.env, fields.Date.context_today(self)
        charts = {}
        if self._finance_ok() and dash is not None:
            start = today - timedelta(days=CHART_DAYS - 1)
            days = [start + timedelta(days=i) for i in range(CHART_DAYS)]
            inv, rec = {d: 0.0 for d in days}, {d: 0.0 for d in days}
            if self._can('account.move'):
                for d, total in env['account.move']._read_group(
                        [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('invoice_date', '>=', start), ('invoice_date', '<=', today),
                         ('company_id', 'in', env.companies.ids)], ['invoice_date:day'], ['amount_total_signed:sum']):
                    if d in inv:
                        inv[d] = total or 0.0
            if self._can('ei.bank.import.line'):
                for line in env['ei.bank.import.line'].search_fetch([('state', '=', 'posted'), ('amount', '>', 0), ('date', '>=', start), ('date', '<=', today)],
                                                                    ['date', 'amount']):
                    if line.date in rec:
                        rec[line.date] += line.amount
            total_in, total_rec = sum(inv.values()), sum(rec.values())
            charts['cashflow'] = {
                'title': _("Invoiced and received, last %s days", CHART_DAYS),
                'days': [{'date': d.strftime('%d %b'), 'iso': fields.Date.to_string(d), 'invoiced': round(inv[d], 2), 'received': round(rec[d], 2)} for d in days],
                'empty': not (total_in or total_rec),
                'summary': _("Invoiced %(i)s, received %(r)s in the last %(n)s days.", i=self._fmt(total_in), r=self._fmt(total_rec), n=CHART_DAYS),
            }
            buckets = (('aging_current', _("Not due yet")), ('aging_30', _("1-30 days late")), ('aging_60', _("31-60 days late")),
                       ('aging_90', _("61-90 days late")), ('aging_90plus', _("Over 90 days late")))
            rows = [{'label': label, 'value': round(dash[f], 2), 'text': self._fmt(dash[f])} for f, label in buckets]
            charts['aging'] = {'title': _("Who owes us, by how late"), 'rows': rows, 'empty': not any(r['value'] for r in rows),
                               'summary': _("Total owed %s.", self._fmt(dash.ar_open)), 'total': round(dash.ar_open, 2), 'total_text': self._fmt(dash.ar_open)}
        mat = self._material()
        if mat and mat.get('ordered'):
            charts['material'] = {'title': _("Material on active contracts"), **mat}
        return charts

    def _activity(self):
        env = self.env
        # bulk-created records (the 639 old codes) would drown the feed with one line each
        bulk = {w['model'] for w in WORK if w.get('bulk')}
        models = {w['model'] for w in WORK}
        if self._finance_ok():
            # an invoice's change messages carry its amounts: only people who may see money read them here
            models.add('account.move')
        models = [m for m in sorted(models - bulk) if self._can(m)]
        if not models:
            return []
        msgs = env['mail.message'].search([('model', 'in', models), ('message_type', 'in', ('comment', 'notification', 'tracking')),
                                           ('res_id', '!=', 0)], order='id desc', limit=ACTIVITY_ITEMS * 4)
        out = []
        for m in msgs:
            rec = env[m.model].browse(m.res_id).exists()
            if not rec or not rec.has_access('read'):
                continue
            if m.model == 'account.move' and rec.move_type == 'entry':
                continue        # a bank or journal entry's change messages are bookkeeping noise, the invoice and the statement say it better
            # Odoo 20 writes a status change as a readable message: "Draft -> Reviewed (Status)"
            text = re.sub(r'\*(.+?)\*', r'\1', html2plaintext(m.body or '')).strip().replace('\n', ' ')[:140]
            if not text:
                continue
            ts = fields.Datetime.context_timestamp(self, m.date)
            out.append({'when': ts.strftime('%d %b %H:%M'), 'who': m.author_id.name or _("System"), 'what': rec.display_name, 'text': text,
                        'model': m.model, 'res_id': m.res_id})
            if len(out) >= ACTIVITY_ITEMS:
                break
        return out

    def _system(self):
        """Plain checks for the administrator. Each one is a real check, not a status light."""
        env = self.env
        from odoo.tools import find_in_path
        pdf = bool(find_in_path('wkhtmltopdf'))
        mail = env['ir.mail_server'].sudo().search_count([('active', '=', True)])
        cron = env.ref('ei_management_dashboard.cron_ei_daily_summary', raise_if_not_found=False)
        cron = cron.sudo() if cron else None
        staff = env['res.users'].sudo().search([('share', '=', False), ('active', '=', True)])
        users = len(staff)
        # has_group follows implied groups (a role reaches group_ei_user through the role's own group), a plain search on group_ids does not
        noroles = len(staff.filtered(lambda u: not u.has_group('ei_legacy_master.group_ei_user')))
        adapters = self._count('ei.compliance.adapter', [('state', '!=', 'live')]) if 'ei.compliance.adapter' in env else None
        checks = [
            dict(label=_("PDF engine (printing and emailing orders and invoices)"), ok=pdf,
                 text=_("Found") if pdf else _("Not installed - Daily Order and invoice PDFs cannot be made")),
            dict(label=_("Outgoing email server"), ok=bool(mail), text=_("Configured") if mail else _("None configured - emails stay in the queue")),
            dict(label=_("Daily summary email job"), ok=bool(cron and cron.active), text=_("Switched on") if cron and cron.active else _("Switched off")),
            dict(label=_("Staff accounts"), ok=True, text=_("%(u)s active, %(n)s without an Export International role", u=users, n=noroles)),
        ]
        if adapters is not None:
            checks.append(dict(label=_("Connections to other systems"), ok=not adapters,
                               text=_("%s not configured (nothing is connected yet)", adapters) if adapters else _("All configured")))
        return {'checks': checks}

    # ------------------------------------------------------------------ pieces kept from the previous Home
    def _day_steps(self):
        env, today = self.env, fields.Date.context_today(self)
        steps = []

        def add(key, label, hint, done, info=None):
            if done is None:
                return
            steps.append({'key': key, 'label': label, 'hint': hint, 'done': bool(done), 'info': info or ''})

        banks = env['account.journal'].sudo().search([('type', '=', 'bank'), ('company_id', 'in', env.companies.ids)]) \
            if 'ei.bank.balance.check' in env and env['ei.bank.balance.check'].has_access('read') else env['account.journal']
        if banks:
            checked = env['ei.bank.balance.check'].search([('date', '=', today), ('journal_id', 'in', banks.ids)]).journal_id
            add('s_balance', _("1. Confirm each bank balance with the bank"), _("Call or check the portal, then type the balance"),
                len(checked) == len(banks), _("%(a)s of %(b)s banks confirmed today", a=len(checked), b=len(banks)))
        n = self._count('ei.bank.import.line', [('state', 'in', ('new', 'proposed', 'verified', 'unidentified'))])
        if n is not None:
            add('s_bank', _("2. Import bank statements and check every payment"), _("Match each payment to the right party"),
                n == 0, _("%s payments still to finish", n) if n else _("All payments are done"))
        n = self._count('ei.da', [('create_date', '>=', datetime.combine(today, datetime.min.time()))])
        if n is not None:
            add('s_da', _("3. Enter contracts and delivery advices received today"), _("Copy them from the parent company's papers"),
                n > 0, _("%s entered today", n) if n else _("None entered yet"))
        n = self._count('ei.cash.count', [('date', '=', today), ('state', '=', 'closed')])
        if n is not None:
            add('s_cash', _("4. Enter cash vouchers and count the cash"), _("Receipts and payments, then the cash in the box"),
                n > 0, _("Cash counted and closed") if n else _("Cash not counted yet"))
        n = self._count('ei.daily.order', [('date', '=', today)])
        if n is not None:
            add('s_order', _("5. Prepare today's Daily Order Request"), _("Made from approved delivery advices"),
                n > 0, _("Prepared") if n else _("Not prepared yet"))
        n = self._count('ei.lifting', [('state', '=', 'draft')])
        if n is not None:
            add('s_lift', _("6. Record trucks that loaded and verify them"), _("Gate pass and weighbridge slip"),
                n == 0, _("%s waiting to be verified", n) if n else _("Nothing waiting"))
        n = self._count('ei.supplier.intake', [('state', 'in', ('draft', 'mismatch'))])
        if n is not None:
            add('s_intake', _("7. Enter supplier invoices as they arrive"), _("The system checks them against the delivery advice"),
                n == 0, _("%s need attention", n) if n else _("Nothing waiting"))
        n = self._count('ei.lifting', [('invoice_status', '=', 'to_invoice')])
        if n is not None:
            add('s_invoice', _("8. Invoice the material that was delivered"), _("One click creates the customer invoices"),
                n == 0, _("%s ready to invoice", n) if n else _("Nothing to invoice"))
        return steps

    def _banks(self):
        """One row per bank account: what the BOOKS say, and when the BANK last confirmed it. A confirmation that is not from today
        is an action item (amber, red after BANK_STALE_RED_DAYS), never a quiet caption."""
        env = self.env
        if 'ei.dashboard' not in env or not env['ei.dashboard']._allowed('bank'):
            return []
        today = fields.Date.context_today(self)
        out = []
        for j in env['account.journal'].sudo().search([('type', '=', 'bank'), ('company_id', 'in', env.companies.ids)]):
            chk = env['ei.bank.balance.check'].sudo().search([('journal_id', '=', j.id)], order='entered_at desc', limit=1)
            ledger = j._ei_ledger_balance(today)
            age = (today - chk.date).days if chk else None
            stale = not chk or chk.date != today
            if not chk:
                tone, text = 'danger', _("Never confirmed with the bank")
            elif chk.date == today and chk.state in ('matched', 'explained'):
                tone, text = 'ok', _("Bank-confirmed today")
            elif chk.date == today:
                tone, text = 'danger', _("Bank and books differ by %s", self._fmt(chk.difference))
            else:
                tone = 'danger' if age >= BANK_STALE_RED_DAYS else 'warning'
                text = _("Not confirmed today: last bank confirmation %(n)s days ago (%(d)s)", n=age, d=format_date(env, chk.date, date_format='dd MMM'))
            out.append({'name': j.name, 'balance': self._fmt(ledger), 'amount': ledger, 'tone': tone, 'text': text, 'stale': stale, 'age_days': age})
        return out

    def _material(self):
        env = self.env
        if 'ei.contract.line' not in env:
            return None
        try:
            lines = env['ei.contract.line'].search([('state', 'in', ('active', 'fulfilled'))])
        except AccessError:
            return None
        ordered = sum(lines.mapped('ordered_mtl'))
        if not ordered:
            return {'ordered': 0}
        alloc, lifted = sum(lines.mapped('allocated_mtl')), sum(lines.mapped('lifted_mtl'))
        # three parts that ADD UP to what the contracts ordered: lifted (verified loadings), promised but not yet lifted (approved delivery
        # advices minus lifted) and not yet promised. Lifted is part of what was promised, never an extra slice on top of it.
        promised_open = max(alloc - lifted, 0.0)
        return {'ordered': round(ordered, 3), 'allocated': round(alloc, 3), 'lifted': round(lifted, 3), 'promised_open': round(promised_open, 3),
                'left': round(ordered - alloc, 3), 'pct_alloc': round(100 * alloc / ordered), 'pct_lift': round(100 * lifted / ordered),
                'pct_open': round(100 * promised_open / ordered), 'pct_free': round(100 * max(ordered - alloc, 0.0) / ordered)}

    # ------------------------------------------------------------------ clicks (every figure opens the records behind it)
    @api.model
    def open_task(self, key):
        for k, _icon, label, _hint, model, domain, _tone, _area in TASKS:
            if k == key:
                return {'type': 'ir.actions.act_window', 'name': label, 'res_model': model, 'domain': domain,
                        'views': self._views_for(model), 'target': 'current'}
        return False

    @api.model
    def open_quick(self, key):
        for k, _icon, label, _hint, _group, kind, target, model in QUICK:
            if k != key:
                continue
            if kind in ('wizard', 'list'):
                return self.env['ir.actions.act_window']._for_xml_id(target)
            return {'type': 'ir.actions.act_window', 'name': label, 'res_model': target, 'views': [[False, 'form']], 'target': 'current'}
        return False

    @api.model
    def open_money(self, key):
        d = self.env['ei.dashboard'].create({})
        kpi = {'ar': 'ar', 'ap': 'ap', 'profit': 'revenue'}.get(key)
        if key == 'cash':
            return {'type': 'ir.actions.act_window', 'name': _("Cash"), 'res_model': 'ei.cash.voucher', 'views': self._views_for('ei.cash.voucher'),
                    'domain': [('state', '=', 'posted')]}
        return d.with_context(kpi=kpi).action_open_kpi() if kpi else False

    @api.model
    def open_kpi(self, key):
        """Open exactly the records a figure on Home is made from."""
        env, today = self.env, fields.Date.context_today(self)
        window = lambda name, model, dom: {'type': 'ir.actions.act_window', 'name': name, 'res_model': model, 'domain': dom,
                                           'views': self._views_for(model), 'target': 'current'}
        if key in ('ar', 'ap'):
            return self.open_money(key)
        if key == 'cash':
            return self.open_money('cash')
        if key == 'bank':
            # bank officers/approvers open the morning confirmations; an accountant (who may see the figure but not that
            # screen) opens the posted items on the bank accounts, which add up to the figure
            if self._can('ei.bank.balance.check'):
                return env['ir.actions.act_window']._for_xml_id('ei_bank_operations.ei_balance_check_action')
            accounts = env['account.journal'].search([('type', '=', 'bank'), ('company_id', 'in', env.companies.ids)]).default_account_id
            return window(_("Posted items on the bank accounts"), 'account.move.line',
                          [('account_id', 'in', accounts.ids), ('parent_state', '=', 'posted'), ('company_id', 'in', env.companies.ids)])
        if key == 'collected':
            return window(_("Collected today"), 'ei.bank.import.line', [('state', '=', 'posted'), ('amount', '>', 0), ('date', '=', today)])
        if key == 'waiting':
            return window(_("Bank money to match"), 'ei.bank.import.line', [('state', 'in', ('new', 'proposed', 'verified', 'unidentified')), ('amount', '>', 0)])
        if key == 'spread':
            return env['ei.dashboard'].create({}).with_context(kpi='contracts').action_open_kpi()
        if key == 'recon':
            return self.open_task('recon')
        m = {'k_contracts': ('ei.contract', [('state', 'in', ('approved', 'active'))]), 'k_das': ('ei.da', [('state', '=', 'under_review')]),
             'k_verify': ('ei.lifting', [('state', '=', 'draft')]), 'k_toinvoice': ('ei.lifting', [('invoice_status', '=', 'to_invoice')]),
             'k_banklines': ('ei.bank.import.line', [('state', 'in', ('new', 'proposed', 'unidentified'))]),
             'k_vouchers': ('ei.cash.voucher', [('state', '=', 'submitted')]), 'k_intake': ('ei.supplier.intake', [('state', '=', 'mismatch')]),
             'k_orders': ('ei.daily.order', [('state', '=', 'approved')]), 'k_left': ('ei.contract.line', [('state', 'in', ('active', 'fulfilled'))])}
        if key in m:
            model, dom = m[key]
            labels = {'k_contracts': _("Active contracts"), 'k_das': _("Delivery advices to approve"), 'k_verify': _("Truck loadings to verify"),
                      'k_toinvoice': _("Delivered, not yet invoiced"), 'k_banklines': _("Bank payments to check"),
                      'k_vouchers': _("Cash vouchers waiting for approval"), 'k_intake': _("Supplier invoices with a problem"),
                      'k_orders': _("Open daily orders"), 'k_left': _("Contract lines")}
            return window(labels[key], model, dom)
        raise UserError(_("Unknown figure."))

    @api.model
    def open_alert(self, key):
        m = {'dup_payment': ('ei.bank.import.line', [('state', '=', 'duplicate')], _("Possible duplicate bank payments")),
             'unidentified': ('ei.bank.import.line', [('state', '=', 'unidentified')], _("Bank receipts nobody has identified")),
             'intake_mismatch': ('ei.supplier.intake', [('state', '=', 'mismatch')], _("Supplier invoices that do not match")),
             'recon': ('ei.parent.statement.line', TASK_BY_KEY['recon'][5], _("Open differences with parent companies"))}
        if key in m:
            model, dom, name = m[key]
            return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model, 'domain': dom, 'views': self._views_for(model), 'target': 'current'}
        if key == 'rate_diff':
            lines = self.env['ei.da.line'].search([('state', '=', 'approved')], limit=500).filtered(
                lambda l: l.contract_line_id and (abs(l.purchase_rate - l.contract_line_id.purchase_rate) > 0.005 or abs(l.sale_rate - l.contract_line_id.sale_rate) > 0.005))
            return {'type': 'ir.actions.act_window', 'name': _("Delivery advice rates that differ from the contract"), 'res_model': 'ei.da.line',
                    'domain': [('id', 'in', lines.ids)], 'views': [[False, 'list'], [False, 'form']], 'target': 'current'}
        if key == 'missing_docs':
            ids = []
            for model, dom in (('ei.supplier.intake', [('state', 'in', ('draft', 'mismatch'))]), ('ei.lifting', [('state', '=', 'draft')])):
                recs = self.env[model].search(dom, limit=200)
                have = {r['res_id'] for r in self.env['ir.attachment'].sudo().search_read([('res_model', '=', model), ('res_id', 'in', recs.ids)], ['res_id'])}
                ids.append((model, [r.id for r in recs if r.id not in have]))
            model, rid = next(((m_, i) for m_, i in ids if i), ('ei.supplier.intake', []))
            return {'type': 'ir.actions.act_window', 'name': _("Records waiting without any attached paper"), 'res_model': model,
                    'domain': [('id', 'in', rid)], 'views': self._views_for(model), 'target': 'current'}
        if key == 'overdue_approvals':
            return self.env['ir.actions.act_window']._for_xml_id('ei_management_dashboard.ei_approval_contracts')
        if key in ('bank_diff', 'bank_stale'):
            return self.env['ir.actions.act_window']._for_xml_id('ei_bank_operations.ei_balance_check_action')
        raise UserError(_("Unknown alert."))

    @api.model
    def open_stage(self, key):
        m = {'contract': ('ei.contract', [('state', 'in', ('approved', 'active'))]), 'da': ('ei.da', [('state', '=', 'approved')]),
             'order': ('ei.daily.order', [('state', '=', 'approved')]), 'lifting': ('ei.lifting', [('state', '=', 'verified')]),
             'supplier': ('ei.supplier.intake', [('state', 'in', ('billed', 'draft', 'mismatch'))]),
             'invoice': ('ei.lifting', [('invoice_status', 'in', ('invoiced', 'to_invoice'))]),
             'recon': ('ei.parent.statement.line', TASK_BY_KEY['recon'][5])}
        if key in m:
            model, dom = m[key]
            labels = {'contract': _("Active contracts"), 'da': _("Approved delivery advices"), 'order': _("Approved daily orders"),
                      'lifting': _("Verified truck loadings"), 'supplier': _("Supplier invoices"), 'invoice': _("Invoiced truck loadings"),
                      'recon': _("Open differences with parent companies")}
            return {'type': 'ir.actions.act_window', 'name': labels[key], 'res_model': model, 'domain': dom, 'views': self._views_for(model), 'target': 'current'}
        if key == 'payment':
            if self._finance_ok():
                return {'type': 'ir.actions.act_window', 'name': _("Unpaid customer invoices"), 'res_model': 'account.move',
                        'domain': [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('payment_state', 'in', ('not_paid', 'partial'))],
                        'views': [[False, 'list'], [False, 'form']], 'target': 'current'}
            return self.open_kpi('waiting')
        raise UserError(_("Unknown step."))

    @api.model
    def open_step(self, key):
        m = {'s_balance': 'ei_bank_operations.ei_balance_check_action', 's_bank': 'ei_bank_operations.ei_bank_line_action',
             's_da': 'ei_contract_da.ei_da_action', 's_cash': 'ei_cashbook.ei_cash_count_action',
             's_order': 'ei_daily_orders.ei_daily_order_action', 's_lift': 'ei_material_lifting.ei_lifting_action',
             's_intake': 'ei_invoice_extensions.ei_intake_action', 's_invoice': 'ei_invoice_extensions.ei_billable_action'}
        return self.env['ir.actions.act_window']._for_xml_id(m[key]) if key in m else False

