"""Profit and loss, balance sheet, trial balance and cash flow: PREVIEWS worked out from the POSTED ledger as it stands today.

They are labelled previews on purpose. The chart of accounts, the opening balances and the tax and commission rules have not been approved by
the client's accountant, so these must not be used for tax, statutory accounts or a lender. What they ARE: every figure is a sum of posted
journal items, every row opens the items behind it, and the totals agree with the figures Home and the management summary already show
(revenue and cost use the same account types). Four checks are shown beside the figures: debits equal credits, assets equal liabilities plus
equity plus the result so far, cash movements reconcile with the ledger, and the result equals the management summary."""
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

REVENUE = ('income', 'income_other')
COSTS = ('expense', 'expense_depreciation', 'expense_direct_cost')
PNL_SECTIONS = [('income', _lt("Sales and other income"), ('income', 'income_other')),
                ('direct', _lt("Direct costs"), ('expense_direct_cost',)),
                ('expense', _lt("Expenses"), ('expense',)),
                ('deprec', _lt("Depreciation"), ('expense_depreciation',))]
BS_SECTIONS = [('cash', _lt("Bank and cash"), ('asset_cash',)),
               ('receivable', _lt("Customers owe us"), ('asset_receivable',)),
               ('current_assets', _lt("Other current assets"), ('asset_current', 'asset_prepayments')),
               ('fixed_assets', _lt("Fixed assets"), ('asset_fixed', 'asset_non_current')),
               ('payable', _lt("We owe suppliers"), ('liability_payable',)),
               ('current_liab', _lt("Other current liabilities"), ('liability_current', 'liability_credit_card')),
               ('long_liab', _lt("Long-term liabilities"), ('liability_non_current',)),
               ('equity', _lt("Equity"), ('equity', 'equity_unaffected'))]
ASSET_KEYS, LIABILITY_KEYS = ('cash', 'receivable', 'current_assets', 'fixed_assets'), ('payable', 'current_liab', 'long_liab')
# the people who may already read the journal items behind every row (the auditor role cannot: open decision no. 29)
GROUPS = ('account.group_account_user', 'account.group_account_manager', 'ei_management_dashboard.group_ei_management')
STATEMENTS = ('summary', 'pnl', 'balance_sheet', 'trial_balance', 'cash_flow')


class EiReportFinancials(models.AbstractModel):
    _name = 'ei.report.financials'
    _description = "Financial statements (preview)"

    # ------------------------------------------------------------------ who, which period
    @api.model
    def _allowed(self):
        return any(self.env.user.has_group(g) for g in GROUPS)

    @api.model
    def _require(self):
        if not self._allowed():
            raise AccessError(_("The financial previews are for the finance team and management."))

    @api.model
    def _period(self, date_from=None, date_to=None):
        today = fields.Date.context_today(self)
        d_to = fields.Date.to_date(date_to) or today
        d_from = fields.Date.to_date(date_from) or d_to.replace(day=1)
        if d_from > d_to:
            raise UserError(_("The period ends before it starts."))
        return d_from, d_to

    @api.model
    def period_choices(self):
        """The ready-made periods of the picker, as dates the client can send back."""
        t = fields.Date.context_today(self)
        m0 = t.replace(day=1)
        q0 = t.replace(month=3 * ((t.month - 1) // 3) + 1, day=1)
        fy = t.replace(month=1, day=1)
        return [dict(key='month', label=_("This month"), date_from=str(m0), date_to=str(t)),
                dict(key='last_month', label=_("Last month"), date_from=str(m0 - relativedelta(months=1)), date_to=str(m0 - relativedelta(days=1))),
                dict(key='quarter', label=_("This quarter"), date_from=str(q0), date_to=str(t)),
                dict(key='year', label=_("This year"), date_from=str(fy), date_to=str(t)),
                dict(key='all', label=_("Everything so far"), date_from='2000-01-01', date_to=str(t))]

    # ------------------------------------------------------------------ the posted ledger
    @api.model
    def _lines(self, extra=()):
        return [('company_id', 'in', self.env.companies.ids), ('parent_state', '=', 'posted')] + list(extra)

    @api.model
    def _balances(self, types, d_from=None, d_to=None):
        """{account: (debit, credit, balance)} of posted items on accounts of these types in the period (no start date: everything up to d_to)."""
        dom = self._lines([('account_id.account_type', 'in', list(types))])
        if d_from:
            dom.append(('date', '>=', d_from))
        if d_to:
            dom.append(('date', '<=', d_to))
        rows = self.env['account.move.line']._read_group(dom, groupby=['account_id'], aggregates=['debit:sum', 'credit:sum', 'balance:sum'])
        return {acc: (dr, cr, bal) for acc, dr, cr, bal in rows}

    @api.model
    def _account_rows(self, balances, sign=1):
        rows = [dict(account_id=a.id, code=a.code or '', name=a.name, type=a.account_type, debit=dr, credit=cr, amount=sign * bal) for a, (dr, cr, bal) in balances.items()]
        return sorted(rows, key=lambda r: (r['code'], r['name']))

    # ------------------------------------------------------------------ the four statements
    @api.model
    def _trial_balance(self, d_from, d_to):
        dom = self._lines([('date', '>=', d_from), ('date', '<=', d_to)])
        rows = self.env['account.move.line']._read_group(dom, groupby=['account_id'], aggregates=['debit:sum', 'credit:sum', 'balance:sum'])
        out = [dict(account_id=a.id, code=a.code or '', name=a.name, type=a.account_type, debit=dr, credit=cr, balance=bal) for a, dr, cr, bal in rows]
        out.sort(key=lambda r: (r['code'], r['name']))
        return out

    @api.model
    def _pnl(self, d_from, d_to):
        sections, net = [], 0.0
        for key, label, types in PNL_SECTIONS:
            sign = -1 if key == 'income' else 1                     # income is a credit balance: shown positive; costs are debit balances
            rows = self._account_rows(self._balances(types, d_from, d_to), sign)
            total = sum(r['amount'] for r in rows)
            sections.append(dict(key=key, label=str(label), rows=rows, total=total))
            net += total if key == 'income' else -total
        return dict(sections=sections, net=net)

    @api.model
    def _earnings_to(self, d_to):
        """The result of every period up to d_to (income minus costs), so that the balance sheet balances without a year-end closing entry."""
        inc = sum(b[2] for b in self._balances(REVENUE, None, d_to).values())
        cost = sum(b[2] for b in self._balances(COSTS, None, d_to).values())
        return -inc - cost

    @api.model
    def _balance_sheet(self, d_to):
        sections = []
        totals = {}
        for key, label, types in BS_SECTIONS:
            sign = 1 if key in ASSET_KEYS else -1                   # assets are debit balances; liabilities and equity are credit balances
            rows = self._account_rows(self._balances(types, None, d_to), sign)
            total = sum(r['amount'] for r in rows)
            totals[key] = total
            sections.append(dict(key=key, label=str(label), rows=rows, total=total, side='assets' if key in ASSET_KEYS else 'liabilities'))
        earnings = self._earnings_to(d_to)
        assets = sum(totals[k] for k in ASSET_KEYS)
        liabilities = sum(totals[k] for k in LIABILITY_KEYS)
        equity = totals['equity']
        return dict(sections=sections, earnings=earnings, assets=assets, liabilities=liabilities, equity=equity,
                    liabilities_and_equity=liabilities + equity + earnings, difference=assets - (liabilities + equity + earnings))

    @api.model
    def _cash_flow(self, d_from, d_to):
        cr = self.env.cr
        cids = tuple(self.env.companies.ids)
        cr.execute("""
            SELECT cat, SUM(debit), SUM(credit) FROM (
              SELECT l.debit, l.credit,
                     CASE WHEN EXISTS (SELECT 1 FROM account_move_line o JOIN account_account ao ON ao.id = o.account_id
                                        WHERE o.move_id = l.move_id AND ao.account_type = 'asset_receivable') THEN 'customers'
                          WHEN EXISTS (SELECT 1 FROM account_move_line o JOIN account_account ao ON ao.id = o.account_id
                                        WHERE o.move_id = l.move_id AND ao.account_type = 'liability_payable') THEN 'suppliers'
                          ELSE 'other' END AS cat
                FROM account_move_line l JOIN account_account a ON a.id = l.account_id
               WHERE l.parent_state = 'posted' AND a.account_type = 'asset_cash' AND l.company_id IN %s AND l.date >= %s AND l.date <= %s) x
             GROUP BY cat""", [cids, d_from, d_to])
        got = {cat: (dr or 0.0, cr_ or 0.0) for cat, dr, cr_ in cr.fetchall()}
        labels = dict(customers=_("From customers"), suppliers=_("To suppliers"), other=_("Everything else (the other side is neither a customer nor a supplier)"))
        rows = [dict(key=k, label=labels[k], inflow=got.get(k, (0.0, 0.0))[0], outflow=got.get(k, (0.0, 0.0))[1], net=got.get(k, (0.0, 0.0))[0] - got.get(k, (0.0, 0.0))[1]) for k in ('customers', 'suppliers', 'other')]
        before = sum(b[2] for b in self._balances(('asset_cash',), None, d_from - relativedelta(days=1)).values())
        after = sum(b[2] for b in self._balances(('asset_cash',), None, d_to).values())
        movement = sum(r['net'] for r in rows)
        return dict(rows=rows, opening=before, closing=after, movement=movement, inflow=sum(r['inflow'] for r in rows), outflow=sum(r['outflow'] for r in rows),
                    difference=before + movement - after)

    # ------------------------------------------------------------------ the whole page
    @api.model
    def get_statements(self, date_from=None, date_to=None):
        self._require()
        d_from, d_to = self._period(date_from, date_to)
        pnl, bs, tb, cf = self._pnl(d_from, d_to), self._balance_sheet(d_to), self._trial_balance(d_from, d_to), self._cash_flow(d_from, d_to)
        revenue = next(s['total'] for s in pnl['sections'] if s['key'] == 'income')
        costs = sum(s['total'] for s in pnl['sections'] if s['key'] != 'income')
        receivable = next(s['total'] for s in bs['sections'] if s['key'] == 'receivable')
        payable = next(s['total'] for s in bs['sections'] if s['key'] == 'payable')
        debit, credit = sum(r['debit'] for r in tb), sum(r['credit'] for r in tb)
        cur = self.env.company.currency_id
        rnd = lambda v: cur.round(v)
        checks = [
            dict(key='tb', ok=cur.is_zero(debit - credit), text=_("Debits equal credits"), detail=_("Debits %(d)s, credits %(c)s", d=self._money(debit), c=self._money(credit))),
            dict(key='bs', ok=cur.is_zero(bs['difference']), text=_("Assets equal liabilities plus equity plus the result so far"),
                 detail=_("Difference %s", self._money(bs['difference']))),
            dict(key='cf', ok=cur.is_zero(cf['difference']), text=_("Opening cash plus the movements equals closing cash"), detail=_("Difference %s", self._money(cf['difference']))),
            dict(key='pnl', ok=cur.is_zero(pnl['net'] - (revenue - costs)), text=_("The result equals revenue minus costs"), detail=_("Result %s", self._money(pnl['net']))),
        ]
        top_costs = sorted([dict(label=(r['code'] + ' ' + r['name']).strip(), amount=r['amount'], account_id=r['account_id']) for s in pnl['sections'] if s['key'] != 'income' for r in s['rows']],
                           key=lambda r: -r['amount'])[:6]
        return dict(
            period=dict(date_from=str(d_from), date_to=str(d_to)), currency=cur.name, symbol=cur.symbol, company=self.env.company.name,
            generated=fields.Datetime.to_string(fields.Datetime.now()),
            kpis=[dict(key='revenue', label=_("Revenue"), value=rnd(revenue), sub=_("Posted income in the period"), tone='ok'),
                  dict(key='costs', label=_("Costs"), value=rnd(costs), sub=_("Posted costs in the period"), tone='warning'),
                  dict(key='net', label=_("Result"), value=rnd(pnl['net']), sub=_("Revenue minus costs"), tone='ok' if pnl['net'] >= 0 else 'danger'),
                  dict(key='cash', label=_("Bank and cash"), value=rnd(cf['closing']), sub=_("In the ledger at the end of the period"), tone='info'),
                  dict(key='receivable', label=_("Customers owe us"), value=rnd(receivable), sub=_("Receivable items in the ledger at the end"), tone='info'),
                  dict(key='payable', label=_("We owe suppliers"), value=rnd(payable), sub=_("Payable items in the ledger at the end"), tone='info')],
            composition=top_costs, ranking=self._top_customers(d_from, d_to),
            pnl=pnl, balance_sheet=bs, trial_balance=dict(rows=tb, debit=debit, credit=credit), cash_flow=cf, checks=checks,
            preview=dict(
                title=_("Preview"),
                text=_("Worked out from posted entries as they stand today. The chart of accounts, opening balances and tax rules are not approved by the accountant yet, "
                       "so do not use these for tax, statutory accounts or a lender.")),
        )

    @api.model
    def _money(self, v):
        cur = self.env.company.currency_id
        return f"{cur.symbol or cur.name} {v:,.2f}"

    @api.model
    def _top_customers(self, d_from, d_to):
        rows = self.env['account.move']._read_group(
            [('company_id', 'in', self.env.companies.ids), ('state', '=', 'posted'), ('move_type', '=', 'out_invoice'), ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)],
            groupby=['partner_id'], aggregates=['amount_total_signed:sum'], order='amount_total_signed:sum desc', limit=5)
        return [dict(label=p.name or _("(no customer)"), amount=amt, partner_id=p.id) for p, amt in rows]

    # ------------------------------------------------------------------ a row opens the items behind it
    @api.model
    def open_lines(self, account_id, date_from=None, date_to=None, cumulative=False):
        self._require()
        d_from, d_to = self._period(date_from, date_to)
        account = self.env['account.account'].browse(account_id)
        if not account.exists():
            raise UserError(_("That account no longer exists."))
        dom = self._lines([('account_id', '=', account.id), ('date', '<=', d_to)] + ([] if cumulative else [('date', '>=', d_from)]))
        return {'type': 'ir.actions.act_window', 'name': _("Posted items: %s", account.display_name), 'res_model': 'account.move.line',
                'views': [[False, 'list'], [False, 'form']], 'domain': dom, 'target': 'current'}
