"""The two legs of every day book entry, one row each: what the old system listed as Dr and Cr lines. A read-only view over
ei_daybook_entry (no second copy of the figures, so a ledger can never disagree with its entries). A balance brought forward is one
row marked as a carried balance; it never counts as a movement of the day."""
from odoo import fields, models
from odoo.tools import SQL

from .entry import KINDS, STATES


class EiDaybookLeg(models.Model):
    _name = 'ei.daybook.leg'
    _description = 'Day book line (one side of an entry)'
    _auto = False
    _order = 'date desc, entry_id desc, side'

    entry_id = fields.Many2one('ei.daybook.entry', string='Entry', readonly=True)
    kind = fields.Selection(KINDS, readonly=True)
    state = fields.Selection(STATES, readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    date = fields.Date(readonly=True)
    side = fields.Selection([('debit', 'Dr'), ('credit', 'Cr')], readonly=True)
    code_id = fields.Many2one('ei.legacy.code', string='Code', readonly=True)
    code_list = fields.Char('Code list', readonly=True)
    other_code_id = fields.Many2one('ei.legacy.code', string='Other side', readonly=True)
    narration = fields.Char(readonly=True)
    is_opening = fields.Boolean('Brought forward', readonly=True)
    debit = fields.Monetary(currency_field='currency_id', readonly=True)
    credit = fields.Monetary(currency_field='currency_id', readonly=True)
    movement_debit = fields.Monetary('Dr (day)', currency_field='currency_id', readonly=True)
    movement_credit = fields.Monetary('Cr (day)', currency_field='currency_id', readonly=True)
    maker_id = fields.Many2one('res.users', 'Entered by', readonly=True)

    @property
    def _table_sql(self):
        one = lambda side, code, other, narr: SQL("""
            SELECT e.id * 2 + %(n)s AS id, e.id AS entry_id, e.kind, e.state, e.company_id, e.currency_id, e.date,
                   %(side)s::varchar AS side, e.%(code)s AS code_id, c.source_sheet_key AS code_list, e.%(other)s AS other_code_id,
                   e.%(narr)s AS narration, e.kind = 'opening' AS is_opening,
                   CASE WHEN %(side)s::varchar = 'debit' THEN e.amount ELSE 0 END AS debit,
                   CASE WHEN %(side)s::varchar = 'credit' THEN e.amount ELSE 0 END AS credit,
                   CASE WHEN %(side)s::varchar = 'debit' AND e.kind != 'opening' THEN e.amount ELSE 0 END AS movement_debit,
                   CASE WHEN %(side)s::varchar = 'credit' AND e.kind != 'opening' THEN e.amount ELSE 0 END AS movement_credit,
                   e.maker_id
              FROM ei_daybook_entry e JOIN ei_legacy_code c ON c.id = e.%(code)s""",
                                               n=1 if side == 'credit' else 0, side=side, code=SQL.identifier(code),
                                               other=SQL.identifier(other), narr=SQL.identifier(narr))
        return SQL("(%s UNION ALL %s)", one('debit', 'debit_code_id', 'credit_code_id', 'debit_narration'),
                   one('credit', 'credit_code_id', 'debit_code_id', 'credit_narration'))

    def action_open_entry(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.daybook.entry', 'res_id': self.entry_id.id, 'views': [(False, 'form')]}
