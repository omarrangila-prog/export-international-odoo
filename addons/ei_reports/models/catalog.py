"""The report catalog: what is delivered, what is partial and what is not built (and why). Honest by construction: a report is marked
delivered only when a real screen exists; a report that needs an approved tax rule, a bank feed or data we do not have says so."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiReportFavourite(models.Model):
    _name = 'ei.report.favourite'
    _description = "A person's favourite report"
    _order = 'id'

    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user, ondelete='cascade', index=True)
    key = fields.Char(required=True)

    _user_key = models.UniqueIndex("(user_id, key)")


# How far each report is from being relied on for real money. Nothing is past 'demo_tested' until real books are loaded and the
# accountant signs: the ladder is shown, so nobody reads "built" as "finance approved".
READINESS = {'delivered': 'demo_tested', 'preview': 'demo_tested', 'partial': 'ui_available', 'pending_source': 'blocked', 'not_built': 'not_built'}
READINESS_LADDER = [('ui_available', "Screen available"), ('demo_tested', "Tested on sample data"), ('data_validated', "Checked against real books"),
                    ('finance_approved', "Approved by finance"), ('production_verified', "Verified in daily use")]


class EiReportCatalog(models.AbstractModel):
    _name = 'ei.report.catalog'
    _description = "Report catalog"

    def _entries(self):
        R = lambda key, area, title, question, definition, source, status, action=None, model=None, note='': dict(
            key=key, area=area, title=title, question=question, definition=definition, source=source, status=status, action=action, model=model, note=note)
        fin, trade, ctl = _("Money"), _("Trade and invoicing"), _("Management and controls")
        return [
            R('ar_aging', fin, _("Aged receivables"), _("Who owes us, and how late?"),
              _("Every open receivable item of a posted customer invoice, with the days it is past due (0 = not yet due) and its band: not due, 1-30, 31-60, 61-90, over 90 days. The total is the Home figure 'Customers owe us'."),
              _("Posted ledger items on receivable accounts, not reconciled"), 'delivered', 'ei_reports.action_report_ar_aging', 'ei.report.ar.aging'),
            R('bank_freshness', fin, _("Bank book against bank confirmation"), _("Is what we hold in the books what the bank says, and when did someone last check?"),
              _("One row per bank account: the BOOK balance today, the last balance somebody typed from the bank, when, and the difference. A confirmation that is not from today is shown as stale. Book, bank-confirmed and unmatched are three different things."),
              _("Posted ledger balance of the bank account; the morning bank-balance confirmations"), 'delivered', 'ei_reports.action_report_bank_freshness', 'ei.report.bank.freshness'),
            R('bank_unmatched', fin, _("Bank lines not yet in the books"), _("What did the bank show that nobody has matched to a party yet, and for how long?"),
              _("Imported bank lines that are still to check, suggested, party-confirmed, unidentified or duplicate, by how many days they have waited. Posted and rejected lines are not listed."),
              _("Imported bank statement lines"), 'delivered', 'ei_reports.action_report_bank_unmatched', 'ei.report.bank.unmatched'),
            R('invoices', fin, _("Customer invoices and collections"), _("What did we invoice, and what is paid?"),
              _("Odoo's own invoice analysis: posted invoices by date, customer and payment status (paid, partly paid, not paid). Collections show as the payment status."),
              _("Posted customer invoices (Odoo accounting)"), 'delivered', 'account.action_account_invoice_report_all', 'account.invoice.report', _("Odoo's native report; filters and saved views work as in Odoo.")),
            R('contract_spread', trade, _("Contracts: ordered, promised, lifted, expected spread"), _("How much did each contract line order, promise and lift, and what is the expected gross spread?"),
              _("Per contract line: ordered MTL, promised on delivery advices, lifted (verified loadings only), promised-not-lifted, not-yet-promised, and the expected GROSS spread = ordered MTL x (sale rate - purchase rate). Before commission, costs and taxes: not profit, provisional until the tax and commission basis is approved."),
              _("Contract lines and verified truck loadings"), 'delivered', 'ei_reports.action_report_contract_spread', 'ei.report.contract.spread', _("Provisional by definition.")),
            R('lifting', trade, _("Material lifting"), _("What was lifted, when, for whom, on which contract?"),
              _("Every truck loading with its gate-pass quantity, the verified lifted quantity (verified loadings only), and any difference. By day, month, customer, contract and delivery advice."),
              _("Truck loadings"), 'delivered', 'ei_reports.action_report_lifting', 'ei.report.lifting'),
            R('journal', fin, _("General ledger (journal items)"), _("Which posted entries make up an account or a party?"),
              _("Odoo's journal-item list and pivot, filterable by account, party and date, with a link to every entry. No running balance column yet."),
              _("Posted journal items (Odoo accounting)"), 'partial', 'account.action_account_moves_all', 'account.move.line', _("Running balance and the standard ledger layout are not built.")),
            R('party', fin, _("Customer and supplier ledger"), _("Everything about one party on one page."), _("Party 360: every figure with its basis, open items, documents and history."),
              _("Ledger, contracts, bank evidence"), 'partial', 'ei_party360.action_ei_party360', 'ei.party360', _("A page per party, not yet a printable ledger.")),
            R('da', trade, _("Delivery advice register"), _("What was advised, revised and approved?"), _("The delivery advices list with status, quantities and authorisation."),
              _("Delivery advices"), 'partial', 'ei_contract_da.ei_da_action', 'ei.da', _("The list exists; a dedicated report with revision history and remaining MTL is not built.")),
            R('supplier_matching', trade, _("Supplier invoice matching"), _("Which supplier invoices matched, which are blocked and why?"), _("The supplier invoice intake list: matched, mismatch, billed."),
              _("Supplier invoice intake"), 'partial', 'ei_invoice_extensions.ei_intake_action', 'ei.supplier.intake', _("Variance impact and approver history are not summarised yet.")),
            R('parent_recon', trade, _("Parent-company ledger reconciliation"), _("Where do the parent's ledger and ours disagree?"), _("Parent statements and their open differences."),
              _("Parent statement lines"), 'partial', 'ei_parent_reconciliation.ei_parent_statement_action', 'ei.parent.statement', _("Aging of differences and period totals are not built.")),
            R('pnl', fin, _("Profit and loss"), _("What did we earn and spend, by account?"),
              _("Posted income and costs in the period you choose: sales and other income, direct costs, expenses and depreciation, account by account, ending in the result. Revenue and costs use the same account types as the management summary, so the result agrees with it. Every row opens the posted items behind it."),
              _("Posted income and expense items"), 'preview', 'ei_reports.action_report_pnl', 'ei.report.financials', _("Preview: the chart of accounts, opening balances and the tax and commission basis are not approved yet. Not for tax or statutory accounts.")),
            R('balance_sheet', fin, _("Balance sheet"), _("What do we own and owe?"),
              _("Posted balances as at the end date: bank and cash, customers, other assets, suppliers, other liabilities and equity, plus the result so far (there is no year-end closing entry yet) so that assets equal liabilities plus equity plus result. A check on the page says whether they agree."),
              _("Posted balances"), 'preview', 'ei_reports.action_report_balance_sheet', 'ei.report.financials', _("Preview: opening balances from signed statements are not loaded, so earlier years are not in it.")),
            R('trial_balance', fin, _("Trial balance"), _("Do the books balance?"),
              _("Debits, credits and balance by account for the period, with a check that total debits equal total credits. Every row opens its posted items."),
              _("Posted journal items"), 'preview', 'ei_reports.action_report_trial_balance', 'ei.report.financials', _("Preview: movements in the period; it does not carry opening balances forward.")),
            R('cash_flow', fin, _("Cash flow"), _("Money in and out of the bank and cash accounts."),
              _("Posted movements on bank and cash accounts in the period, classified by what is on the other side of the entry (customers, suppliers, everything else), from the opening balance to the closing balance, which agrees with the ledger."),
              _("Posted bank and cash items"), 'preview', 'ei_reports.action_report_cash_flow', 'ei.report.financials', _("Preview: direct method, classified by the other side of each entry; no forecast.")),
            R('cash_book', fin, _("Cash book / petty cash"), _("What did the cash box open, receive, pay and count?"), _("Daily cash movements and the physical count variance."),
              _("Cash vouchers and counts"), 'not_built', None, None, _("Vouchers and counts exist as lists; the daily report is not built.")),
            R('expense', fin, _("Expenses by category"), _("Where does the money go?"), _("Spending by category with the supporting voucher."), _("Cash vouchers"), 'not_built'),
            R('approvals', ctl, _("Approvals and workload"), _("What waits for a decision, with whom, for how long?"), _("Home's 'What is stuck' list and the Approvals menu."),
              _("Work queues"), 'partial', 'ei_management_dashboard.ei_approval_contracts', 'ei.contract', _("Service-level and backlog aging are not summarised.")),
            R('audit', ctl, _("Audit trail"), _("Who changed what, and when?"), _("Every record's chatter records who created, changed and approved it, with before and after values."),
              _("Record history (chatter)"), 'partial', None, None, _("Per record; no cross-record audit report yet.")),
            R('month_end', ctl, _("Month-end close"), _("What is left to close the month?"), _("A checklist of unreconciled entries, missing documents and approval backlog."), _("Several"), 'not_built'),
            R('tax_fbr', ctl, _("Tax and FBR readiness"), _("Is anything ready to send to the tax authority?"), _("Only from approved statutory logic and a real integration."),
              _("None yet"), 'pending_source', None, None, _("Blocked: no approved tax rules and no FBR access. Nothing here may imply acceptance by FBR.")),
        ]

    @api.model
    def get_catalog(self):
        env = self.env
        fav = set(env['ei.report.favourite'].search([('user_id', '=', env.user.id)]).mapped('key'))
        out = []
        for e in self._entries():
            can = False
            if e['action']:
                try:
                    if e['model'] == 'ei.report.financials':
                        can = env['ei.report.financials']._allowed()                 # an abstract model has no access rows: who may open it is a rule of its own
                    else:
                        can = e['model'] in env and env[e['model']].has_access('read')
                    if can and e['action']:
                        env.ref(e['action'])
                except (AccessError, ValueError):
                    can = False
            readiness = READINESS.get(e['status'], 'not_built')
            out.append(dict(e, can_open=bool(can), favourite=e['key'] in fav, readiness=readiness,
                            contract=self._data_contract(e)))
        return out

    def _data_contract(self, e):
        """What every figure of a report rests on, stated the same way for all of them."""
        return {
            'company': ', '.join(self.env.companies.mapped('name')),
            'currency': self.env.company.currency_id.name,
            'as_of': _("Worked out when you open it, from the records as they are at that moment"),
            'excludes': e.get('excludes') or _("Drafts, cancelled and rejected records"),
            'owner': _("Finance") if e['area'] == _("Money") else _("Operations") if e['area'] == _("Trade and invoicing") else _("Management"),
        }

    @api.model
    def readiness_ladder(self):
        return [{'key': k, 'label': _(l)} for k, l in READINESS_LADDER]

    @api.model
    def toggle_favourite(self, key):
        if key not in {e['key'] for e in self._entries()}:
            raise UserError(_("Unknown report."))
        F = self.env['ei.report.favourite']
        mine = F.search([('user_id', '=', self.env.user.id), ('key', '=', key)])
        if mine:
            mine.unlink()
            return False
        F.create({'key': key})
        return True
