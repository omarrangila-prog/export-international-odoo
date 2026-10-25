from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiCashCount(models.Model):
    _name = 'ei.cash.count'
    _description = 'Daily cash count'
    _inherit = ['mail.thread']
    _order = 'date desc, journal_id'

    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'cash')]", index=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency')
    date = fields.Date(required=True, default=fields.Date.context_today)
    custodian_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user)
    line_ids = fields.One2many('ei.cash.count.line', 'count_id')
    counted_amount = fields.Monetary(compute='_compute_amounts', store=True, readonly=False, currency_field='currency_id')
    book_balance = fields.Monetary(readonly=True, currency_field='currency_id')
    opening_balance = fields.Monetary(readonly=True, currency_field='currency_id')
    receipts = fields.Monetary(readonly=True, currency_field='currency_id')
    payments = fields.Monetary(readonly=True, currency_field='currency_id')
    discrepancy = fields.Monetary(readonly=True, currency_field='currency_id')
    discrepancy_note = fields.Text()
    state = fields.Selection([('draft', 'Draft'), ('closed', 'Closed')], default='draft', readonly=True, tracking=True)
    closed_by = fields.Many2one('res.users', readonly=True)
    closed_at = fields.Datetime(readonly=True)
    adjustment_move_id = fields.Many2one('account.move', readonly=True)

    _uniq = models.Constraint('unique(journal_id, date)', 'A cash count already exists for this journal and date.')

    @api.depends('journal_id')
    def _compute_currency(self):
        for r in self:
            r.currency_id = r.journal_id.currency_id or r.journal_id.company_id.currency_id

    @api.depends('line_ids.subtotal')
    def _compute_amounts(self):
        for r in self:
            if r.line_ids:
                r.counted_amount = sum(r.line_ids.mapped('subtotal'))

    def _figures(self):
        self.ensure_one()
        Line = self.env['account.move.line'].sudo()
        acc = self.journal_id.default_account_id
        base = [('account_id', '=', acc.id), ('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted')]
        opening = sum(Line.search(base + [('date', '<', self.date)]).mapped('balance'))
        day = Line.search(base + [('date', '=', self.date)])
        rec = sum(l.balance for l in day if l.balance > 0)
        pay = -sum(l.balance for l in day if l.balance < 0)
        return opening, rec, pay

    def action_close(self):
        if not self.env.user.has_group('ei_cashbook.group_ei_cash_approver'):
            raise AccessError(_("Only a cash approver can close the day."))
        for r in self:
            if r.state == 'closed':
                continue
            if r.custodian_id == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: the custodian who counted the cash cannot close it."))
            opening, rec, pay = r._figures()
            book = opening + rec - pay
            diff = r.currency_id.round(r.counted_amount - book)
            if not r.currency_id.is_zero(diff) and not (r.discrepancy_note or '').strip():
                raise UserError(_("Counted %(c)s differs from book %(b)s by %(d)s; write a note first.",
                                  c=r.counted_amount, b=book, d=diff))
            r.write({'opening_balance': opening, 'receipts': rec, 'payments': pay, 'book_balance': book,
                     'discrepancy': diff, 'state': 'closed', 'closed_by': self.env.user.id,
                     'closed_at': fields.Datetime.now()})

    def action_post_discrepancy(self):
        """Optional, explicit: post the difference to the journal's profit/loss account."""
        if not self.env.user.has_group('ei_cashbook.group_ei_cash_approver'):
            raise AccessError(_("Only a cash approver can post a cash difference."))
        for r in self:
            if r.state != 'closed' or r.adjustment_move_id or r.currency_id.is_zero(r.discrepancy):
                raise UserError(_("Nothing to post, or already posted."))
            j = r.journal_id
            gain = r.discrepancy > 0
            counter = j.profit_account_id if gain else j.loss_account_id
            if not counter:
                raise UserError(_("Set the cash difference %s account on the journal first.", 'gain' if gain else 'loss'))
            amt = abs(r.discrepancy)
            move = self.env['account.move'].create({
                'move_type': 'entry', 'journal_id': j.id, 'date': r.date, 'ref': _('Cash difference %s', r.date),
                'line_ids': [
                    (0, 0, {'account_id': j.default_account_id.id, 'name': 'Cash difference',
                            'debit': amt if gain else 0.0, 'credit': 0.0 if gain else amt}),
                    (0, 0, {'account_id': counter.id, 'name': 'Cash difference',
                            'debit': 0.0 if gain else amt, 'credit': amt if gain else 0.0}),
                ]})
            move.action_post()
            r.adjustment_move_id = move


class EiCashCountLine(models.Model):
    _name = 'ei.cash.count.line'
    _description = 'Cash count denomination line'

    count_id = fields.Many2one('ei.cash.count', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='count_id.currency_id')
    denomination = fields.Monetary(required=True, currency_field='currency_id')
    quantity = fields.Integer(required=True)
    subtotal = fields.Monetary(compute='_compute_subtotal', store=True, currency_field='currency_id')

    @api.depends('denomination', 'quantity')
    def _compute_subtotal(self):
        for r in self:
            r.subtotal = r.denomination * r.quantity
