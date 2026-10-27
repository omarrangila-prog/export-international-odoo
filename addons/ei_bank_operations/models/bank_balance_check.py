from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

# How each kind of timing item explains (bank - ledger). Amounts are entered positive.
MAIL_FIELDS = {'message_main_attachment_id', 'message_follower_ids'}
TIMING_SIGN = {'deposit_in_transit': -1, 'uncleared_cheque': 1, 'bank_debit_not_booked': -1, 'bank_credit_not_booked': 1}


class EiBankBalanceCheck(models.Model):
    _name = 'ei.bank.balance.check'
    _description = 'Morning bank balance confirmation vs ledger'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'bank')]", index=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency')
    date = fields.Date(required=True, default=fields.Date.context_today)
    bank_balance = fields.Monetary('Balance stated by the bank', required=True, currency_field='currency_id')
    confirmed_via = fields.Selection([
        ('call', 'Phone call to bank'), ('sms', 'Bank SMS'), ('portal', 'Bank portal / statement'),
    ], required=True, default='call')
    evidence_count = fields.Integer('Proof attached', compute='_compute_evidence')
    evidence_state = fields.Selection([('evidenced', 'Bank-confirmed: proof attached'), ('stated', 'Typed in: no proof yet')],
                                      compute='_compute_evidence',
                                      help="A balance typed in from a phone call is not bank-confirmed until the bank's own proof "
                                           "(statement page, portal screenshot, SMS) is attached.")
    timing_ids = fields.One2many('ei.bank.balance.timing', 'check_id', string='Timing items')
    timing_total = fields.Monetary('Explained by timing items', compute='_compute_unexplained', store=True, currency_field='currency_id')
    unexplained_difference = fields.Monetary(compute='_compute_unexplained', store=True, currency_field='currency_id',
                                             help="Bank minus ledger, less what the listed timing items explain.")
    signed_by = fields.Many2one('res.users', readonly=True)
    signed_at = fields.Datetime(readonly=True)
    ledger_balance = fields.Monetary('Ledger balance at end of day', readonly=True, currency_field='currency_id')
    difference = fields.Monetary(readonly=True, currency_field='currency_id')
    state = fields.Selection([('matched', 'Matched'), ('difference', 'Difference'), ('explained', 'Explained'), ('signed', 'Signed off')],
                             readonly=True, default='difference')
    note = fields.Text()
    entered_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    entered_at = fields.Datetime(readonly=True, default=fields.Datetime.now)

    def _compute_evidence(self):
        data = dict(self.env['ir.attachment'].sudo()._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.evidence_count = data.get(r.id, 0)
            r.evidence_state = 'evidenced' if r.evidence_count else 'stated'

    @api.depends('difference', 'timing_ids.amount', 'timing_ids.kind')
    def _compute_unexplained(self):
        for r in self:
            r.timing_total = sum(t.effect for t in r.timing_ids)
            r.unexplained_difference = r.currency_id.round(r.difference - r.timing_total) if r.currency_id else r.difference - r.timing_total

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
        if not self.env.context.get('ei_system') and set(vals) - MAIL_FIELDS:
            if set(vals) - {'note', 'timing_ids'} - MAIL_FIELDS:
                raise UserError(_("A balance confirmation is an audit record; only the note and timing items can be edited. "
                                  "Enter a new confirmation instead."))
            if any(r.state == 'signed' for r in self):
                raise UserError(_("This confirmation is signed off and final."))
        return super().write(vals)

    def action_explain(self):
        for r in self:
            if r.state != 'difference':
                continue
            if not r.currency_id.is_zero(r.unexplained_difference) and not r.note:
                raise UserError(_("%(d)s is not explained by timing items. List them, or write the explanation in the note.",
                                  d=r.unexplained_difference))
            r.with_context(ei_system=True).state = 'explained'

    def action_open_form(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'views': [(False, 'form')]}

    def action_sign_off(self):
        """The second person's review. Locks the confirmation, its proof status and its timing items."""
        if not self.env.user.has_group('ei_bank_operations.group_ei_bank_approver'):
            raise AccessError(_("Only a bank approver can sign off a balance confirmation."))
        for r in self:
            if r.state not in ('matched', 'explained'):
                raise UserError(_("Explain the difference first (timing items or a note)."))
            if r.entered_by == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: the person who entered the balance cannot sign it off."))
            if r.evidence_state != 'evidenced':
                raise UserError(_("Attach the bank's proof of the balance first. A typed-in figure is not bank-confirmed."))
            r.with_context(ei_system=True).write({'state': 'signed', 'signed_by': self.env.user.id, 'signed_at': fields.Datetime.now()})


class EiBankBalanceTiming(models.Model):
    _name = 'ei.bank.balance.timing'
    _description = 'Timing item explaining a bank vs ledger difference'
    _order = 'id'

    check_id = fields.Many2one('ei.bank.balance.check', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='check_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='check_id.currency_id')
    kind = fields.Selection([
        ('deposit_in_transit', 'Deposit in our books, not yet at the bank'),
        ('uncleared_cheque', 'Cheque we issued, not yet presented'),
        ('bank_debit_not_booked', 'Bank charge or debit not yet in our books'),
        ('bank_credit_not_booked', 'Bank credit not yet in our books'),
    ], required=True)
    reference = fields.Char(required=True, help="Cheque number, deposit slip, bank reference.")
    amount = fields.Monetary(required=True, currency_field='currency_id', help="Enter it positive; the kind gives the direction.")
    effect = fields.Monetary(compute='_compute_effect', currency_field='currency_id', help="How much of (bank - ledger) this explains.")
    added_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)

    @api.depends('kind', 'amount')
    def _compute_effect(self):
        for t in self:
            t.effect = TIMING_SIGN.get(t.kind, 0) * t.amount

    @api.constrains('amount')
    def _check_amount(self):
        for t in self:
            if t.amount <= 0:
                raise UserError(_("Enter a timing item as a positive amount; its kind gives the direction."))

    def _guard(self, checks):
        if any(c.state == 'signed' for c in checks):
            raise UserError(_("This confirmation is signed off; its timing items are final."))

    @api.model_create_multi
    def create(self, vals_list):
        self._guard(self.env['ei.bank.balance.check'].browse([v.get('check_id') for v in vals_list]))
        return super().create(vals_list)

    def write(self, vals):
        self._guard(self.check_id)
        return super().write(vals)

    def unlink(self):
        self._guard(self.check_id)
        return super().unlink()


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
