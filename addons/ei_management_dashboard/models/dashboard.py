from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

BANK_GROUPS = ('ei_bank_operations.group_ei_bank_officer', 'ei_bank_operations.group_ei_bank_approver',
               'ei_bank_operations.group_ei_bank_poster')
FINANCE_GROUPS = ('account.group_account_user', 'account.group_account_manager', 'ei_bank_operations.group_ei_bank_approver',
                  'ei_cashbook.group_ei_cash_approver')
OPS_GROUPS = ('ei_contract_da.group_ei_contract_staff', 'ei_material_lifting.group_ei_dispatch_officer')
STALE_HOURS_PARAM = 'ei_management_dashboard.bank_stale_hours'


class EiDashboard(models.TransientModel):
    _name = 'ei.dashboard'
    _description = 'Management dashboard (computed from posted records at open time)'

    date_from = fields.Date(default=lambda s: fields.Date.context_today(s).replace(day=1))
    date_to = fields.Date(default=fields.Date.context_today)
    partner_id = fields.Many2one('res.partner', string='Party')
    product_id = fields.Many2one('product.product', string='Material')
    contract_id = fields.Many2one('ei.contract')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    generated_at = fields.Datetime(default=fields.Datetime.now, readonly=True)

    @api.depends('generated_at')
    def _compute_display_name(self):
        for d in self:
            d.display_name = _('Dashboard')

    # --- finance (posted, verified)
    ar_open = fields.Monetary('Customer outstanding', compute='_compute_finance', currency_field='currency_id')
    ap_open = fields.Monetary('Supplier payable', compute='_compute_finance', currency_field='currency_id')
    aging_current = fields.Monetary('Not yet due', compute='_compute_finance', currency_field='currency_id')
    aging_30 = fields.Monetary('1-30 days', compute='_compute_finance', currency_field='currency_id')
    aging_60 = fields.Monetary('31-60 days', compute='_compute_finance', currency_field='currency_id')
    aging_90 = fields.Monetary('61-90 days', compute='_compute_finance', currency_field='currency_id')
    aging_90plus = fields.Monetary('Over 90 days', compute='_compute_finance', currency_field='currency_id')
    revenue = fields.Monetary('Posted revenue (period)', compute='_compute_finance', currency_field='currency_id')
    costs = fields.Monetary('Posted costs (period)', compute='_compute_finance', currency_field='currency_id')
    profit = fields.Monetary('Posted profit / loss (period)', compute='_compute_finance', currency_field='currency_id')
    cash_position = fields.Monetary('Cash in hand (ledger)', compute='_compute_finance', currency_field='currency_id')
    # --- banking
    bank_html = fields.Html('Bank balances and freshness', compute='_compute_bank', sanitize=False)
    bank_pending_lines = fields.Integer('Bank lines not yet posted', compute='_compute_bank')
    bank_pending_amount = fields.Monetary('Amount not yet posted', compute='_compute_bank', currency_field='currency_id')
    suspense_lines = fields.Integer('Unreconciled statement lines (suspense)', compute='_compute_bank')
    suspense_amount = fields.Monetary(compute='_compute_bank', currency_field='currency_id')
    # --- operations
    mtl_ordered = fields.Float('Contracted MTL', compute='_compute_ops', digits=(16, 3))
    mtl_allocated = fields.Float('Allocated by DAs', compute='_compute_ops', digits=(16, 3))
    mtl_available = fields.Float('Still available', compute='_compute_ops', digits=(16, 3))
    mtl_lifted = fields.Float('Verified lifted', compute='_compute_ops', digits=(16, 3))
    mtl_pending = fields.Float('Requested, not yet lifted', compute='_compute_ops', digits=(16, 3))
    gross_spread = fields.Monetary('Expected gross spread (provisional)', compute='_compute_ops', currency_field='currency_id')
    pending_supplier_docs = fields.Integer('Supplier invoices awaiting resolution', compute='_compute_ops')
    open_recon_exceptions = fields.Integer('Open parent-ledger exceptions', compute='_compute_ops')
    # --- approvals
    approvals_html = fields.Html('Approval queues', compute='_compute_approvals', sanitize=False)
    approvals_total = fields.Integer(compute='_compute_approvals')

    # -------------------------------------------------------------- security
    @api.model
    def _allowed(self, section):
        u = self.env.user
        if u.has_group('ei_management_dashboard.group_ei_management'):
            return True
        groups = {'bank': BANK_GROUPS + FINANCE_GROUPS, 'finance': FINANCE_GROUPS, 'ops': OPS_GROUPS,
                  'approvals': ('ei_legacy_master.group_ei_user',)}[section]
        return any(u.has_group(g) for g in groups)

    def _company_ids(self):
        return self.env.companies.ids

    # ---------------------------------------------------------- domains (also used for drill-down)
    def _dom_lines(self, kind):
        self.ensure_one()
        types = {'ar': ['asset_receivable'], 'ap': ['liability_payable']}[kind]
        dom = [('company_id', 'in', self._company_ids()), ('parent_state', '=', 'posted'), ('reconciled', '=', False),
               ('account_type', 'in', types)]
        if self.partner_id:
            dom.append(('partner_id', 'child_of', self.partner_id.id))
        return dom

    def _dom_pl(self, kind):
        self.ensure_one()
        types = {'revenue': ['income', 'income_other'], 'costs': ['expense', 'expense_depreciation', 'expense_direct_cost']}[kind]
        dom = [('company_id', 'in', self._company_ids()), ('parent_state', '=', 'posted'), ('account_type', 'in', types)]
        if self.date_from:
            dom.append(('date', '>=', self.date_from))
        if self.date_to:
            dom.append(('date', '<=', self.date_to))
        if self.partner_id:
            dom.append(('partner_id', 'child_of', self.partner_id.id))
        if self.product_id:
            dom.append(('product_id', '=', self.product_id.id))
        return dom

    def _dom_contract_lines(self):
        self.ensure_one()
        dom = [('company_id', 'in', self._company_ids()), ('state', 'in', ('active', 'fulfilled'))]
        if self.contract_id:
            dom.append(('contract_id', '=', self.contract_id.id))
        if self.product_id:
            dom.append(('product_id', '=', self.product_id.id))
        if self.partner_id:
            dom.append(('contract_id.parent_partner_id', '=', self.partner_id.id))
        return dom

    def _dom_pending_bank(self):
        return [('company_id', 'in', self._company_ids()), ('state', 'in', ('new', 'proposed', 'verified', 'unidentified'))]

    def _dom_unreconciled_st(self):
        return [('company_id', 'in', self._company_ids()), ('is_reconciled', '=', False)]

    def _cash_journals(self):
        return self.env['account.journal'].sudo().search([('type', '=', 'cash'), ('company_id', 'in', self._company_ids())])

    def _bank_journals(self):
        return self.env['account.journal'].sudo().search([('type', '=', 'bank'), ('company_id', 'in', self._company_ids())])

    # --------------------------------------------------------------- compute
    @api.depends('date_from', 'date_to', 'partner_id', 'product_id')
    def _compute_finance(self):
        for d in self:
            vals = dict.fromkeys(('ar_open', 'ap_open', 'aging_current', 'aging_30', 'aging_60', 'aging_90', 'aging_90plus',
                                  'revenue', 'costs', 'profit', 'cash_position'), 0.0)
            if self._allowed('finance'):
                L = self.env['account.move.line'].sudo()
                ar = L.search(d._dom_lines('ar'))
                vals['ar_open'] = sum(ar.mapped('amount_residual'))
                vals['ap_open'] = -sum(L.search(d._dom_lines('ap')).mapped('amount_residual'))
                today = d.date_to or fields.Date.context_today(d)
                for l in ar:
                    age = (today - (l.date_maturity or l.date)).days
                    key = ('aging_current' if age <= 0 else 'aging_30' if age <= 30 else 'aging_60' if age <= 60
                           else 'aging_90' if age <= 90 else 'aging_90plus')
                    vals[key] += l.amount_residual
                vals['revenue'] = -sum(L.search(d._dom_pl('revenue')).mapped('balance'))
                vals['costs'] = sum(L.search(d._dom_pl('costs')).mapped('balance'))
                vals['profit'] = vals['revenue'] - vals['costs']
                vals['cash_position'] = sum(j._ei_ledger_balance(d.date_to or fields.Date.context_today(d)) for j in d._cash_journals())
            d.update(vals)

    @api.depends('date_to')
    def _compute_bank(self):
        stale = self.env['ir.config_parameter'].sudo().get_float(STALE_HOURS_PARAM, 24.0)
        for d in self:
            vals = {'bank_html': False, 'bank_pending_lines': 0, 'bank_pending_amount': 0.0, 'suspense_lines': 0, 'suspense_amount': 0.0}
            if self._allowed('bank'):
                rows = Markup('')
                now = fields.Datetime.now()
                for j in d._bank_journals():
                    ledger = j._ei_ledger_balance(d.date_to or fields.Date.context_today(d))
                    chk = self.env['ei.bank.balance.check'].sudo().search([('journal_id', '=', j.id)], order='entered_at desc', limit=1)
                    imp = self.env['ei.bank.import'].sudo().search([('journal_id', '=', j.id), ('state', '=', 'posted')],
                                                                   order='posted_at desc', limit=1)
                    if chk and chk.state in ('matched', 'explained') and (now - chk.entered_at) <= timedelta(hours=stale):
                        label = _("Verified: bank-confirmed %s", fields.Datetime.to_string(chk.entered_at))
                        css = 'text-success'
                    elif chk:
                        label = _("PROVISIONAL: last bank confirmation %(t)s, %(s)s", t=fields.Datetime.to_string(chk.entered_at), s=chk.state)
                        css = 'text-warning'
                    else:
                        label = _("PROVISIONAL: never confirmed with the bank")
                        css = 'text-danger'
                    rows += Markup('<tr><td>%s</td><td class="text-end">%s</td><td class="%s">%s</td><td>%s</td></tr>') % (
                        j.name, j.currency_id.round(ledger) if j.currency_id else round(ledger, 2), css, label,
                        fields.Datetime.to_string(imp.posted_at) if imp else _('no statement posted'))
                vals['bank_html'] = Markup('<table class="table table-sm"><thead><tr><th>Bank account</th><th class="text-end">Ledger balance</th>'
                                           '<th>Bank confirmation</th><th>Last statement posted</th></tr></thead><tbody>%s</tbody></table>') % rows
                pend = self.env['ei.bank.import.line'].sudo().search(d._dom_pending_bank())
                vals['bank_pending_lines'] = len(pend)
                vals['bank_pending_amount'] = sum(pend.mapped('amount'))
                st = self.env['account.bank.statement.line'].sudo().search(d._dom_unreconciled_st())
                vals['suspense_lines'] = len(st)
                vals['suspense_amount'] = sum(st.mapped('amount'))
            d.update(vals)

    @api.depends('partner_id', 'product_id', 'contract_id')
    def _compute_ops(self):
        for d in self:
            vals = dict.fromkeys(('mtl_ordered', 'mtl_allocated', 'mtl_available', 'mtl_lifted', 'mtl_pending', 'gross_spread',
                                  'pending_supplier_docs', 'open_recon_exceptions'), 0)
            if self._allowed('ops') or self._allowed('finance'):
                lines = self.env['ei.contract.line'].sudo().search(d._dom_contract_lines())
                vals['mtl_ordered'] = sum(lines.mapped('ordered_mtl'))
                vals['mtl_allocated'] = sum(lines.mapped('allocated_mtl'))
                vals['mtl_available'] = sum(lines.mapped('remaining_mtl'))
                vals['mtl_lifted'] = sum(lines.mapped('lifted_mtl'))
                vals['gross_spread'] = sum(lines.mapped('expected_gross_spread'))
                ol = self.env['ei.daily.order.line'].sudo().search([('state', '=', 'approved'), ('company_id', 'in', d._company_ids()),
                                                                    ('da_line_id.contract_line_id', 'in', lines.ids)])
                vals['mtl_pending'] = sum(max(l.remaining_mtl, 0) for l in ol)
                vals['pending_supplier_docs'] = self.env['ei.supplier.intake'].sudo().search_count(
                    [('company_id', 'in', d._company_ids()), ('state', 'in', ('draft', 'mismatch'))])
                vals['open_recon_exceptions'] = self.env['ei.parent.statement.line'].sudo().search_count(
                    [('company_id', 'in', d._company_ids()), ('status', '!=', 'matched'), ('resolution_state', '=', 'open')])
            d.update(vals)

    QUEUES = [
        ('Contracts to approve', 'ei.contract', [('state', '=', 'reviewed')]),
        ('DAs to approve', 'ei.da', [('state', '=', 'under_review')]),
        ('Daily orders to approve', 'ei.daily.order', [('state', '=', 'draft')]),
        ('Liftings to verify', 'ei.lifting', [('state', '=', 'draft')]),
        ('Cash vouchers to approve', 'ei.cash.voucher', [('state', '=', 'submitted')]),
        ('Bank imports to approve', 'ei.bank.import', [('state', 'in', ('validated', 'proposed', 'received'))]),
        ('Bank imports to post', 'ei.bank.import', [('state', '=', 'approved')]),
        ('Supplier invoices in mismatch', 'ei.supplier.intake', [('state', '=', 'mismatch')]),
        ('Parent statements awaiting sign-off', 'ei.parent.statement', [('state', '=', 'resolved')]),
        ('Legacy-code mappings to classify', 'ei.legacy.code', [('verification_status', 'in', ('proposed', 'needs_review'))]),
        ('Formulas awaiting approval', 'ei.formula.definition', [('state', '=', 'draft')]),
    ]

    @api.depends()
    def _compute_approvals(self):
        for d in self:
            html, total = Markup(''), 0
            if self._allowed('approvals'):
                for label, model, dom in self.QUEUES:
                    if model not in self.env:
                        continue
                    try:
                        n = self.env[model].search_count(dom)
                    except AccessError:
                        continue
                    total += n
                    html += Markup('<tr><td>%s</td><td class="text-end"><b>%s</b></td></tr>') % (_(label), n)
            d.approvals_total = total
            d.approvals_html = Markup('<table class="table table-sm"><tbody>%s</tbody></table>') % html if html else False

    # ---------------------------------------------------------------- opening
    @api.model
    def open_dashboard(self):
        d = self.create({})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': d.id, 'views': [(False, 'form')],
                'target': 'current', 'name': _('Dashboard')}

    def action_open_kpi(self):
        """Every KPI opens the original Odoo transactions behind the number."""
        self.ensure_one()
        k = self.env.context.get('kpi')
        M = {
            'ar': ('account.move.line', self._dom_lines('ar'), _('Customer outstanding (open receivable items)')),
            'ap': ('account.move.line', self._dom_lines('ap'), _('Supplier payable (open payable items)')),
            'revenue': ('account.move.line', self._dom_pl('revenue'), _('Posted revenue lines')),
            'costs': ('account.move.line', self._dom_pl('costs'), _('Posted cost lines')),
            'contracts': ('ei.contract.line', self._dom_contract_lines(), _('Contract lines')),
            'bank_pending': ('ei.bank.import.line', self._dom_pending_bank(), _('Bank lines not yet posted')),
            'suspense': ('account.bank.statement.line', self._dom_unreconciled_st(), _('Unreconciled statement lines')),
            'intake': ('ei.supplier.intake', [('company_id', 'in', self._company_ids()), ('state', 'in', ('draft', 'mismatch'))], _('Supplier invoices to resolve')),
            'recon': ('ei.parent.statement.line', [('company_id', 'in', self._company_ids()), ('status', '!=', 'matched'), ('resolution_state', '=', 'open')], _('Open ledger exceptions')),
            'pending_orders': ('ei.daily.order.line', [('state', '=', 'approved'), ('company_id', 'in', self._company_ids())], _('Order request lines')),
        }
        if k in ('aging_30', 'aging_60', 'aging_90', 'aging_90plus', 'aging_current'):
            k = 'ar'
        model, dom, name = M[k]
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model, 'views': [(False, 'list'), (False, 'form')],
                'domain': dom, 'target': 'current'}

    def action_open_queue(self):
        self.ensure_one()
        idx = int(self.env.context.get('queue', 0))
        label, model, dom = self.QUEUES[idx]
        return {'type': 'ir.actions.act_window', 'name': _(label), 'res_model': model, 'views': [(False, 'list'), (False, 'form')], 'domain': dom}

    # --------------------------------------------------------------- summary
    def daily_summary_html(self):
        d = self.create({'date_from': fields.Date.context_today(self), 'date_to': fields.Date.context_today(self)})
        rows = [(_('Customer outstanding'), d.ar_open), (_('Supplier payable'), d.ap_open), (_('Revenue today (posted)'), d.revenue),
                (_('Costs today (posted)'), d.costs), (_('Cash in hand (ledger)'), d.cash_position),
                (_('Bank lines not yet posted'), d.bank_pending_lines), (_('Unreconciled statement lines'), d.suspense_lines),
                (_('Verified lifted MTL (active contracts)'), d.mtl_lifted), (_('Approvals waiting'), d.approvals_total)]
        body = Markup('').join(Markup('<tr><td>%s</td><td style="text-align:right">%s</td></tr>') % (k, v) for k, v in rows)
        return Markup('<p>Posted records only; bank figures carry their own freshness labels in the dashboard. '
                      'Generated %s.</p><table>%s</table>') % (fields.Datetime.to_string(d.generated_at), body)

    @api.model
    def cron_send_daily_summary(self):
        users = self.env.ref('ei_management_dashboard.group_ei_management').sudo().user_ids
        if not users:
            return 0
        html = self.sudo().daily_summary_html()
        self.env['mail.mail'].sudo().create([{
            'subject': _('Export International - daily summary'), 'body_html': html,
            'email_to': u.email, 'auto_delete': True} for u in users if u.email]).send()
        return len(users)
