"""Bank reports. BOOK (what our ledger holds), BANK-CONFIRMED (what somebody typed from the bank) and UNMATCHED (money the bank shows that
nobody has matched to a party yet) are three different things and are never combined into one 'verified' label."""
from odoo import fields, models, _
from odoo.tools import SQL

FRESHNESS = [('confirmed', "Bank-confirmed today"), ('difference', "Differs from the bank today"), ('stale', "Not confirmed today"), ('never', "Never confirmed")]
AGE = [('d0_1', "Today or yesterday"), ('d2_7', "2-7 days"), ('d8_30', "8-30 days"), ('d31p', "Over 30 days")]
LINE_STATE = [('new', "To check"), ('proposed', "Suggestion ready"), ('verified', "Party confirmed"), ('unidentified', "Unidentified"), ('duplicate', "Duplicate")]


class EiReportBankFreshness(models.Model):
    _name = 'ei.report.bank.freshness'
    _inherit = 'ei.report.base'
    _description = "Bank book against bank confirmation"
    _auto = False
    _order = 'age_days desc nulls first, journal_id'

    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    journal_id = fields.Many2one('account.journal', "Bank account", readonly=True)
    book_balance = fields.Monetary("Book balance today", readonly=True, currency_field='currency_id', help="Posted ledger balance of the account, today.")
    confirmed_date = fields.Date("Last bank confirmation", readonly=True)
    entered_at = fields.Datetime("Typed in at", readonly=True)
    bank_balance = fields.Monetary("Balance the bank gave", readonly=True, currency_field='currency_id')
    ledger_at_confirmation = fields.Monetary("Book balance then", readonly=True, currency_field='currency_id')
    difference = fields.Monetary("Difference then", readonly=True, currency_field='currency_id', help="Bank balance less book balance at that time.")
    freshness = fields.Selection(FRESHNESS, "Confirmation", readonly=True)
    age_days = fields.Integer("Days since confirmed", readonly=True, aggregator='max')

    def _select_sql(self):
        today = fields.Date.context_today(self)
        return SQL("""
            SELECT j.id AS id, j.company_id AS company_id, co.currency_id AS currency_id, j.id AS journal_id,
                   COALESCE((SELECT SUM(l.balance) FROM account_move_line l WHERE l.account_id = j.default_account_id AND l.company_id = j.company_id
                                AND l.parent_state = 'posted' AND l.date <= %(today)s), 0) AS book_balance,
                   c.date AS confirmed_date, c.entered_at AS entered_at, c.bank_balance AS bank_balance, c.ledger_balance AS ledger_at_confirmation,
                   c.difference AS difference,
                   CASE WHEN c.id IS NULL THEN 'never' WHEN c.date = %(today)s::date THEN (CASE WHEN c.state = 'difference' THEN 'difference' ELSE 'confirmed' END)
                        ELSE 'stale' END AS freshness,
                   CASE WHEN c.id IS NULL THEN NULL ELSE (%(today)s::date - c.date) END AS age_days
              FROM account_journal j
              JOIN res_company co ON co.id = j.company_id
              LEFT JOIN LATERAL (SELECT * FROM ei_bank_balance_check b WHERE b.journal_id = j.id ORDER BY b.entered_at DESC, b.id DESC LIMIT 1) c ON TRUE
             WHERE j.type = 'bank'
        """, today=today)

    def action_open_source(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Bank balance confirmations"), 'res_model': 'ei.bank.balance.check',
                'domain': [('journal_id', '=', self.journal_id.id)], 'views': [[False, 'list'], [False, 'form']], 'target': 'current'}


class EiReportBankUnmatched(models.Model):
    _name = 'ei.report.bank.unmatched'
    _inherit = 'ei.report.base'
    _description = "Bank lines not yet in the books"
    _auto = False
    _order = 'date, id'

    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    journal_id = fields.Many2one('account.journal', "Bank account", readonly=True)
    import_id = fields.Many2one('ei.bank.import', "Statement", readonly=True)
    date = fields.Date("Bank date", readonly=True)
    age_days = fields.Integer("Days waiting", readonly=True, aggregator='max')
    age_bucket = fields.Selection(AGE, "Waiting for", readonly=True)
    direction = fields.Selection([('receipt', "Money in"), ('payment', "Money out")], readonly=True)
    amount = fields.Monetary("Amount (+ in, - out)", readonly=True, currency_field='currency_id')
    state = fields.Selection(LINE_STATE, "Where it stands", readonly=True)
    partner_id = fields.Many2one('res.partner', "Confirmed party", readonly=True)
    suggested_partner_id = fields.Many2one('res.partner', "Suggested party", readonly=True)
    ref = fields.Char("Bank reference", readonly=True)
    narration = fields.Char("Bank description", readonly=True)

    def _select_sql(self):
        today = fields.Date.context_today(self)
        age = SQL("(%s::date - l.date)", today)
        return SQL("""
            SELECT l.id AS id, l.company_id AS company_id, co.currency_id AS currency_id, l.journal_id AS journal_id, l.import_id AS import_id,
                   l.date AS date, %(age)s AS age_days,
                   CASE WHEN %(age)s <= 1 THEN 'd0_1' WHEN %(age)s <= 7 THEN 'd2_7' WHEN %(age)s <= 30 THEN 'd8_30' ELSE 'd31p' END AS age_bucket,
                   CASE WHEN l.amount >= 0 THEN 'receipt' ELSE 'payment' END AS direction, l.amount AS amount, l.state AS state,
                   l.partner_id AS partner_id, l.suggested_partner_id AS suggested_partner_id, l.ref AS ref, l.narration AS narration
              FROM ei_bank_import_line l
              JOIN res_company co ON co.id = l.company_id
             WHERE l.state IN ('new', 'proposed', 'verified', 'unidentified', 'duplicate')
        """, age=age)

    def action_open_source(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Bank line"), 'res_model': 'ei.bank.import.line', 'res_id': self.id,
                'views': [[False, 'form']], 'target': 'current'}
