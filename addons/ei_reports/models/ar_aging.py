"""Receivables ageing: one row per OPEN receivable item of a posted invoice, bucketed by how late it is. The rows are exactly the ones
the Home figure "Customers owe us" adds up (posted, not reconciled, receivable account), so the report total equals that figure."""
from odoo import api, fields, models, _
from odoo.tools import SQL

BUCKETS = [('current', "Not due yet"), ('d1_30', "1-30 days late"), ('d31_60', "31-60 days late"), ('d61_90', "61-90 days late"), ('d90p', "Over 90 days late")]


class EiReportArAging(models.Model):
    _name = 'ei.report.ar.aging'
    _inherit = 'ei.report.base'
    _description = "Receivables ageing"
    _auto = False
    _order = 'days_overdue desc, partner_id'

    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    partner_id = fields.Many2one('res.partner', "Customer", readonly=True)
    move_id = fields.Many2one('account.move', "Invoice or entry", readonly=True)
    invoice_date = fields.Date("Dated", readonly=True)
    due_date = fields.Date("Due", readonly=True)
    days_overdue = fields.Integer("Days late", readonly=True, aggregator='max', help="0 when not yet due.")
    bucket = fields.Selection(BUCKETS, "How late", readonly=True)
    amount_residual = fields.Monetary("Still owed", readonly=True, currency_field='currency_id',
                                      help="The open amount of the item, in the company currency. The same items the Home figure adds up.")

    def _select_sql(self):
        today = fields.Date.context_today(self)
        age = SQL("(%s::date - COALESCE(l.date_maturity, l.date))", today)
        return SQL("""
            SELECT l.id AS id, l.company_id AS company_id, c.currency_id AS currency_id, l.partner_id AS partner_id, l.move_id AS move_id,
                   l.date AS invoice_date, COALESCE(l.date_maturity, l.date) AS due_date, GREATEST(%(age)s, 0) AS days_overdue,
                   CASE WHEN %(age)s <= 0 THEN 'current' WHEN %(age)s <= 30 THEN 'd1_30' WHEN %(age)s <= 60 THEN 'd31_60'
                        WHEN %(age)s <= 90 THEN 'd61_90' ELSE 'd90p' END AS bucket,
                   l.amount_residual AS amount_residual
              FROM account_move_line l
              JOIN account_account a ON a.id = l.account_id
              JOIN res_company c ON c.id = l.company_id
             WHERE l.parent_state = 'posted' AND l.reconciled IS NOT TRUE AND a.account_type = 'asset_receivable'
        """, age=age)

    def action_open_source(self):
        self.ensure_one()
        return self._open_record(self.move_id)

