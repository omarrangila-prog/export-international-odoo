"""Data behind the guided Home page. Everything here is read-only counting/aggregation on records the
current user is allowed to see; a section a user cannot access simply does not appear."""
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools.misc import format_amount

from .labels import LABELS

KANBAN_MODELS = {'ei.bank.import', 'ei.cash.voucher', 'ei.contract', 'ei.da', 'ei.daily.order', 'ei.lifting',
                 'ei.supplier.intake', 'ei.parent.statement'}

# key, icon, label, hint, model, domain, tone when > 0, area
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
AREAS = [('money', "Money"), ('orders', "Orders and trucks"), ('bills', "Bills and invoices"),
         ('month', "Month-end"), ('setup', "Setup")]

# key, icon, label, kind, target
QUICK = [
    ('q_bank', 'fa-upload', "Import a bank statement", 'wizard', 'ei_bank_operations.ei_bank_import_wizard_action', 'ei.bank.import.wizard'),
    ('q_voucher', 'fa-money', "New cash voucher", 'form', 'ei.cash.voucher', 'ei.cash.voucher'),
    ('q_contract', 'fa-file-text-o', "New contract", 'form', 'ei.contract', 'ei.contract'),
    ('q_da', 'fa-truck', "New delivery advice", 'form', 'ei.da', 'ei.da'),
    ('q_lift', 'fa-balance-scale', "Record a truck loading", 'form', 'ei.lifting', 'ei.lifting'),
    ('q_intake', 'fa-inbox', "Enter a supplier invoice", 'form', 'ei.supplier.intake', 'ei.supplier.intake'),
    ('q_invoice', 'fa-file-o', "Invoice delivered material", 'list', 'ei_invoice_extensions.ei_billable_action', 'ei.invoice.wizard'),
    ('q_parent', 'fa-upload', "Import parent statement", 'wizard', 'ei_parent_reconciliation.ei_parent_import_wizard_action', 'ei.parent.import.wizard'),
]


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

    @api.model
    def _views_for(self, model):
        return [[False, 'kanban'], [False, 'list'], [False, 'form']] if model in KANBAN_MODELS else [[False, 'list'], [False, 'form']]

    # ------------------------------------------------------------------ the page
    @api.model
    def get_data(self):
        env, user = self.env, self.env.user
        now = fields.Datetime.context_timestamp(self, datetime.now())
        hour = now.hour
        data = {
            'name': (user.name or '').split(' ')[0],
            'greeting': _("Good morning") if hour < 12 else _("Good afternoon") if hour < 17 else _("Good evening"),
            'date': now.strftime('%A, %d %B %Y'),
            'company': env.company.name,
            'updated': now.strftime('%H:%M'),
        }
        # --- things that need attention
        tasks = []
        for key, icon, label, hint, model, domain, tone, area in TASKS:
            n = self._count(model, domain)
            if n is None:
                continue
            if key == 'codes' and not env['ei.legacy.code'].has_access('write'):
                continue   # only people who can classify codes need this card
            tasks.append({'key': key, 'icon': icon, 'label': label, 'hint': hint, 'count': n, 'area': area,
                          'tone': tone if n else 'ok'})
        data['areas'] = [{'key': k, 'label': l, 'tasks': [t for t in tasks if t['area'] == k]}
                         for k, l in AREAS if any(t['area'] == k for t in tasks)]
        data['attention'] = sum(t['count'] for t in tasks if t['tone'] in ('warning', 'danger'))
        # --- quick start
        quick = []
        for key, icon, label, kind, target, model in QUICK:
            if model not in env:
                continue
            try:
                ok = env[model].has_access('create')
            except AccessError:
                ok = False
            if ok:
                quick.append({'key': key, 'icon': icon, 'label': label})
        data['quick'] = quick
        # --- the day, step by step
        data['steps'] = self._day_steps()
        # --- money, banks, material
        data['money'] = self._money()
        data['banks'] = self._banks()
        data['material'] = self._material()
        data['empty'] = not (tasks or quick)
        return data

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
                n == 0, _("%s loadings ready to invoice", n) if n else _("Nothing to invoice"))
        return steps

    def _money(self):
        env = self.env
        if 'ei.dashboard' not in env or not env['ei.dashboard'].has_access('create'):
            return []
        d = env['ei.dashboard'].create({})
        items = []
        for key, icon, label, hint, value, tone in (
                ('ar', 'fa-arrow-circle-down', _("Customers owe us"), _("Unpaid customer invoices"), d.ar_open, 'in'),
                ('ap', 'fa-arrow-circle-up', _("We owe suppliers"), _("Unpaid supplier bills"), d.ap_open, 'out'),
                ('cash', 'fa-money', _("Cash in hand"), _("According to the books"), d.cash_position, 'neutral'),
                ('profit', 'fa-line-chart', _("Profit this month"), _("From posted entries only"), d.profit, 'neutral')):
            if self._allowed_finance():
                items.append({'key': key, 'icon': icon, 'label': label, 'hint': hint, 'value': self._fmt(value), 'tone': tone})
        return items

    def _allowed_finance(self):
        return self.env['ei.dashboard']._allowed('finance')

    def _banks(self):
        env = self.env
        if 'ei.dashboard' not in env or not env['ei.dashboard']._allowed('bank'):
            return []
        today = fields.Date.context_today(self)
        out = []
        for j in env['account.journal'].sudo().search([('type', '=', 'bank'), ('company_id', 'in', env.companies.ids)]):
            chk = env['ei.bank.balance.check'].sudo().search([('journal_id', '=', j.id)], order='entered_at desc', limit=1)
            ledger = j._ei_ledger_balance(today)
            if not chk:
                tone, text = 'danger', _("Never confirmed with the bank")
            elif chk.date == today and chk.state in ('matched', 'explained'):
                tone, text = 'ok', _("Confirmed with the bank today")
            elif chk.date == today:
                tone, text = 'danger', _("Bank and books differ by %s", self._fmt(chk.difference))
            else:
                tone, text = 'warning', _("Last confirmed on %s", fields.Date.to_string(chk.date))
            out.append({'name': j.name, 'balance': self._fmt(ledger), 'tone': tone, 'text': text})
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
        return {'ordered': round(ordered, 3), 'allocated': round(alloc, 3), 'lifted': round(lifted, 3),
                'left': round(ordered - alloc, 3), 'pct_alloc': round(100 * alloc / ordered), 'pct_lift': round(100 * lifted / ordered)}

    # ------------------------------------------------------------------ clicks
    @api.model
    def open_task(self, key):
        for k, _icon, label, _hint, model, domain, _tone, _area in TASKS:
            if k == key:
                return {'type': 'ir.actions.act_window', 'name': label, 'res_model': model, 'domain': domain,
                        'views': self._views_for(model), 'target': 'current'}
        return False

    @api.model
    def open_quick(self, key):
        for k, _icon, label, kind, target, model in QUICK:
            if k != key:
                continue
            if kind in ('wizard', 'list'):
                return self.env['ir.actions.act_window']._for_xml_id(target)
            return {'type': 'ir.actions.act_window', 'name': label, 'res_model': target, 'views': [[False, 'form']],
                    'target': 'current'}
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
    def open_step(self, key):
        m = {'s_balance': 'ei_bank_operations.ei_balance_check_action', 's_bank': 'ei_bank_operations.ei_bank_line_action',
             's_da': 'ei_contract_da.ei_da_action', 's_cash': 'ei_cashbook.ei_cash_count_action',
             's_order': 'ei_daily_orders.ei_daily_order_action', 's_lift': 'ei_material_lifting.ei_lifting_action',
             's_intake': 'ei_invoice_extensions.ei_intake_action', 's_invoice': 'ei_invoice_extensions.ei_billable_action'}
        return self.env['ir.actions.act_window']._for_xml_id(m[key]) if key in m else False
