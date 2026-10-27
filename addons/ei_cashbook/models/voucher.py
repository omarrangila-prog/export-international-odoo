from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError


class EiCashVoucher(models.Model):
    _name = 'ei.cash.voucher'
    _description = 'Cash voucher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(readonly=True, copy=False, default='New')
    journal_id = fields.Many2one('account.journal', required=True, domain="[('type', '=', 'cash')]", index=True,
                                 tracking=True)
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency')
    date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    kind = fields.Selection([
        ('payment', 'Payment (cash out)'), ('receipt', 'Receipt (cash in)'),
        ('bank_transfer', 'Transfer to bank'), ('safe_transfer', 'Transfer to another cash box'),
    ], required=True, default='payment', tracking=True)
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    category_id = fields.Many2one('ei.cash.category', tracking=True)
    target_journal_id = fields.Many2one('account.journal', string='Transfer to', domain="[('type', 'in', ('bank', 'cash'))]")
    partner_id = fields.Many2one('res.partner')
    party_code_id = fields.Many2one('ei.legacy.code', string='Party code (old system)',
                                    help="The code written on the paper cash book, kept exactly (e.g. 4.20).")
    reference_no = fields.Char('Cheque / slip no.', tracking=True)
    description = fields.Char(required=True)
    analytic_distribution = fields.Json()
    analytic_precision = fields.Integer(default=2)
    state = fields.Selection([
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('posted', 'Posted'),
        ('rejected', 'Rejected'), ('reversed', 'Reversed'),
    ], default='draft', readonly=True, tracking=True, index=True)
    maker_id = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    checker_id = fields.Many2one('res.users', readonly=True)
    decided_at = fields.Datetime(readonly=True)
    reject_reason = fields.Char(readonly=True)
    reverse_reason = fields.Char(readonly=True)
    move_id = fields.Many2one('account.move', readonly=True, copy=False)
    reversal_move_id = fields.Many2one('account.move', readonly=True, copy=False)
    attachment_count = fields.Integer('Papers attached', compute='_compute_attachment_count')

    @api.depends('journal_id')
    def _compute_currency(self):
        for r in self:
            r.currency_id = r.journal_id.currency_id or r.journal_id.company_id.currency_id

    def _compute_attachment_count(self):
        data = dict(self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.attachment_count = data.get(r.id, 0)

    @api.constrains('amount')
    def _check_amount(self):
        for r in self:
            if r.amount <= 0:
                raise UserError(_("Amount must be positive."))

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'New') == 'New':
                v['name'] = self.env['ir.sequence'].next_by_code('ei.cash.voucher') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        locked = {'journal_id', 'date', 'kind', 'amount', 'category_id', 'target_journal_id', 'partner_id', 'description', 'party_code_id', 'reference_no'}
        if locked & set(vals) and any(r.state != 'draft' for r in self):
            raise UserError(_("Only a draft voucher can be edited. Reject or reverse it instead."))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_("Only draft vouchers can be deleted."))
        return super().unlink()

    # -------------------------------------------------------------- workflow
    def action_submit(self):
        for r in self:
            if r.state != 'draft':
                raise UserError(_("Only a draft can be submitted."))
            if r.maker_id != self.env.user and not self.env.su:
                raise AccessError(_("Only the maker can submit this voucher."))
            if r.kind in ('payment', 'receipt') and not r.category_id:
                raise UserError(_("Choose a category."))
            if r.kind in ('bank_transfer', 'safe_transfer'):
                if not r.target_journal_id or r.target_journal_id == r.journal_id:
                    raise UserError(_("Choose a different journal to transfer to."))
                if r.kind == 'bank_transfer' and r.target_journal_id.type != 'bank':
                    raise UserError(_("A bank transfer must target a bank journal."))
                if r.kind == 'safe_transfer' and r.target_journal_id.type != 'cash':
                    raise UserError(_("A safe transfer must target a cash journal."))
            j = r.journal_id
            if r.kind == 'payment' and r.amount > j.ei_receipt_required_over and not r.attachment_count:
                raise UserError(_("Attach the receipt before submitting (required over %s).", j.ei_receipt_required_over))
            r.state = 'submitted'

    def _check_checker(self):
        if not self.env.user.has_group('ei_cashbook.group_ei_cash_approver'):
            raise AccessError(_("Only a cash approver can decide a voucher."))

    def action_approve(self):
        """Approve and post in one controlled step."""
        self._check_checker()
        for r in self:
            if r.state != 'submitted':
                raise UserError(_("Only a submitted voucher can be approved."))
            if r.maker_id == self.env.user and not self.env.su and r.amount > r.journal_id.ei_self_approve_limit:
                raise AccessError(_("Maker-checker: you cannot approve your own voucher of %(a)s (self-approval limit %(l)s).",
                                    a=r.amount, l=r.journal_id.ei_self_approve_limit))
            move = r._create_move()
            r.write({'state': 'posted', 'checker_id': self.env.user.id, 'decided_at': fields.Datetime.now(),
                     'move_id': move.id})

    def action_reject(self, reason=None):
        self._check_checker()
        for r in self:
            if r.state != 'submitted':
                raise UserError(_("Only a submitted voucher can be rejected."))
            if not (reason or '').strip():
                raise UserError(_("A rejection reason is required."))
            r.write({'state': 'rejected', 'reject_reason': reason, 'checker_id': self.env.user.id,
                     'decided_at': fields.Datetime.now()})

    def action_reverse(self, reason=None):
        self._check_checker()
        for r in self:
            if r.state != 'posted':
                raise UserError(_("Only a posted voucher can be reversed."))
            if not (reason or '').strip():
                raise UserError(_("A reversal reason is required."))
            rev = r.move_id._reverse_moves([{'date': fields.Date.context_today(r), 'ref': _('Reversal of %s', r.name)}],
                                           cancel=True)
            r.write({'state': 'reversed', 'reverse_reason': reason, 'reversal_move_id': rev.id})

    # ---------------------------------------------------------------- ledger
    def _create_move(self):
        self.ensure_one()
        j = self.journal_id
        cash_acc = j.default_account_id
        if not cash_acc:
            raise UserError(_("Journal %s has no cash account.", j.display_name))
        if self.kind in ('payment', 'receipt'):
            counter = self.category_id.account_id
            if self.category_id.company_id != self.company_id:
                raise UserError(_("Category %s belongs to another company.", self.category_id.name))
        elif self.kind == 'bank_transfer':
            counter = self.company_id.transfer_account_id
            if not counter:
                raise UserError(_("Set the internal transfer account on the company before transferring cash to the bank."))
        else:
            counter = self.target_journal_id.default_account_id
        cash_in = self.kind == 'receipt'
        lines = [
            Command.create({'account_id': cash_acc.id, 'name': self.description, 'partner_id': self.partner_id.id,
                            'debit': self.amount if cash_in else 0.0, 'credit': 0.0 if cash_in else self.amount}),
            Command.create({'account_id': counter.id, 'name': self.description, 'partner_id': self.partner_id.id,
                            'debit': 0.0 if cash_in else self.amount, 'credit': self.amount if cash_in else 0.0,
                            'analytic_distribution': self.analytic_distribution or False}),
        ]
        move = self.env['account.move'].create({
            'move_type': 'entry', 'journal_id': j.id, 'date': self.date, 'ref': self.name, 'line_ids': lines})
        move.action_post()
        return move
