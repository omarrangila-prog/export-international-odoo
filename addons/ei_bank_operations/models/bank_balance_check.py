from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EiBankBalanceCheck(models.Model):
    _name = 'ei.bank.balance.check'
    _description = 'Morning bank balance confirmation vs ledger'
    _order = 'date desc, id desc'

    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'bank')]", index=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency')
    date = fields.Date(required=True, default=fields.Date.context_today)
    bank_balance = fields.Monetary('Balance confirmed by bank', required=True, currency_field='currency_id')
    confirmed_via = fields.Selection([
        ('call', 'Phone call to bank'), ('sms', 'Bank SMS'), ('portal', 'Bank portal / statement'),
    ], required=True, default='call')
    ledger_balance = fields.Monetary('Ledger balance at end of day', readonly=True, currency_field='currency_id')
    difference = fields.Monetary(readonly=True, currency_field='currency_id')
    state = fields.Selection([('matched', 'Matched'), ('difference', 'Difference'), ('explained', 'Explained')],
                             readonly=True, default='difference')
    note = fields.Text()
    entered_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    entered_at = fields.Datetime(readonly=True, default=fields.Datetime.now)

    @api.depends('journal_id')
    def _compute_currency(self):
        for r in self:
            r.currency_id = r.journal_id.currency_id or r.journal_id.company_id.currency_id

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for r in recs:
            ledger = r.journal_id._ei_ledger_balance(r.date, inclusive=True)
            diff = r.currency_id.round(r.bank_balance - ledger)
            r.with_context(ei_system=True).write({
                'ledger_balance': ledger, 'difference': diff,
                'state': 'matched' if r.currency_id.is_zero(diff) else 'difference'})
        return recs

    def write(self, vals):
        if not self.env.context.get('ei_system') and set(vals) - {'note'}:
            raise UserError(_("A balance confirmation is an audit record; only the note can be edited. "
                              "Enter a new confirmation instead."))
        return super().write(vals)

    def action_explain(self):
        for r in self:
            if r.state != 'difference':
                continue
            if not r.note:
                raise UserError(_("Write the explanation in the note first."))
            r.with_context(ei_system=True).state = 'explained'


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    ei_last_balance_check_at = fields.Datetime('Last bank balance confirmation', compute='_compute_ei_freshness')
    ei_last_import_at = fields.Datetime('Last statement posted', compute='_compute_ei_freshness')

    def _compute_ei_freshness(self):
        for j in self:
            chk = self.env['ei.bank.balance.check'].sudo().search([('journal_id', '=', j.id)], order='entered_at desc', limit=1)
            imp = self.env['ei.bank.import'].sudo().search([('journal_id', '=', j.id), ('state', '=', 'posted')],
                                                    order='posted_at desc', limit=1)
            j.ei_last_balance_check_at = chk.entered_at
            j.ei_last_import_at = imp.posted_at
