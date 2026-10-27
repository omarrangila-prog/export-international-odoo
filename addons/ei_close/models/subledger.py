"""R3: the sum of the party balances against the receivable / payable control accounts, from Odoo's own posted journal items.

Nothing here writes to the accounts. A difference is explained, never balanced away: items on a control account without a party,
entries typed by hand on a control account, and parties whose balance runs the wrong way are listed so that someone can look at them."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

KIND_TYPE = {'receivable': 'asset_receivable', 'payable': 'liability_payable'}
KIND_SIGN = {'receivable': 1, 'payable': -1}   # payables are credits in the books; shown as the amount we owe


class EiSubledgerCheck(models.Model):
    _name = 'ei.subledger.check'
    _description = 'Party balances against the control account'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(compute='_compute_name')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    date = fields.Date('As of', required=True, default=fields.Date.context_today)
    kind = fields.Selection([('receivable', 'Customers (receivable)'), ('payable', 'Suppliers (payable)')], required=True, default='receivable')
    state = fields.Selection([('draft', 'Not run'), ('checked', 'Checked'), ('signed', 'Signed off')], default='draft', readonly=True, tracking=True)
    control_balance = fields.Monetary('Control accounts', readonly=True, currency_field='currency_id')
    party_total = fields.Monetary('Sum of party balances', readonly=True, currency_field='currency_id')
    no_party_amount = fields.Monetary('Items with no party', readonly=True, currency_field='currency_id',
                                      help="Posted on a control account without a customer or supplier: nobody's ledger shows them.")
    difference = fields.Monetary('Control less parties', readonly=True, currency_field='currency_id')
    manual_amount = fields.Monetary('Typed by hand on a control account', readonly=True, currency_field='currency_id',
                                    help="Journal entries that are not an invoice, a bill, a payment or a bank line, posted on a control account.")
    manual_count = fields.Integer('Hand entries', readonly=True)
    wrong_way_count = fields.Integer('Parties with a balance the wrong way', readonly=True,
                                     help="A customer we owe money to (unapplied receipt, credit note) or a supplier who owes us (advance).")
    wrong_way_amount = fields.Monetary('Their total', readonly=True, currency_field='currency_id')
    line_ids = fields.One2many('ei.subledger.check.line', 'check_id', readonly=True)
    note = fields.Text('Explanation')
    checked_by = fields.Many2one('res.users', readonly=True)
    checked_at = fields.Datetime(readonly=True)
    signed_by = fields.Many2one('res.users', readonly=True)
    signed_at = fields.Datetime(readonly=True)

    @api.depends('kind', 'date')
    def _compute_name(self):
        labels = dict(self._fields['kind'].selection)
        for r in self:
            r.name = '%s - %s' % (labels.get(r.kind, ''), r.date or '')

    def _domain(self, extra=None):
        self.ensure_one()
        return [('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted'), ('date', '<=', self.date),
                ('account_id.account_type', '=', KIND_TYPE[self.kind])] + (extra or [])

    @staticmethod
    def _manual_domain():
        return [('move_id.move_type', '=', 'entry'), ('move_id.origin_payment_id', '=', False), ('move_id.statement_line_id', '=', False)]

    def write(self, vals):
        if not self.env.context.get('ei_system') and any(r.state == 'signed' for r in self) and set(vals) - {'message_follower_ids', 'message_main_attachment_id'}:
            raise UserError(_("A signed-off check is final. Run a new one."))
        return super().write(vals)

    def unlink(self):
        if any(r.state == 'signed' for r in self):
            raise UserError(_("A signed-off check is kept as evidence."))
        return super().unlink()

    def action_run(self):
        AML = self.env['account.move.line'].sudo()
        for r in self:
            if r.state == 'signed':
                raise UserError(_("A signed-off check is final. Run a new one."))
            sign, cur = KIND_SIGN[r.kind], r.currency_id
            per_account = AML._read_group(r._domain(), ['account_id'], ['balance:sum'])
            per_party = AML._read_group(r._domain([('partner_id', '!=', False)]), ['partner_id'], ['balance:sum'])
            no_party = AML._read_group(r._domain([('partner_id', '=', False)]), ['account_id'], ['balance:sum'])
            manual = AML._read_group(r._domain(r._manual_domain()), ['account_id'], ['balance:sum', '__count'])
            control = sign * sum(b for _a, b in per_account)
            parties = sign * sum(b for _p, b in per_party)
            wrong = [sign * b for _p, b in per_party if cur.compare_amounts(sign * b, 0) < 0]
            no_p = {a.id: sign * b for a, b in no_party}
            man = {a.id: (sign * b, n) for a, b, n in manual}
            r.check_access('write')
            r.line_ids.sudo().unlink()
            r.with_context(ei_system=True).write({
                'control_balance': control, 'party_total': parties, 'no_party_amount': sum(no_p.values()),
                'difference': cur.round(control - parties),
                'manual_amount': sum(v for v, _n in man.values()), 'manual_count': sum(n for _v, n in man.values()),
                'wrong_way_count': len(wrong), 'wrong_way_amount': sum(wrong),
                'state': 'checked', 'checked_by': self.env.user.id, 'checked_at': fields.Datetime.now(),
            })
            self.env['ei.subledger.check.line'].sudo().create([
                {'check_id': r.id, 'account_id': a.id, 'balance': sign * b, 'no_party_amount': no_p.get(a.id, 0.0),
                 'manual_amount': man.get(a.id, (0.0, 0))[0], 'manual_count': man.get(a.id, (0.0, 0))[1]} for a, b in per_account])
        return True

    def action_sign(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only an accounting manager can sign off party balances."))
        for r in self:
            if r.state != 'checked':
                raise UserError(_("Run the check first."))
            if r.checked_by == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: the person who ran the check cannot sign it off."))
            cur = r.currency_id
            if not (cur.is_zero(r.difference) and cur.is_zero(r.manual_amount)) and not (r.note or '').strip():
                raise UserError(_("Items with no party or entries typed by hand on a control account are listed. "
                                  "Write what they are in the explanation before signing."))
            r.with_context(ei_system=True).write({'state': 'signed', 'signed_by': self.env.user.id, 'signed_at': fields.Datetime.now()})

    def _open_items(self, extra, title):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': title, 'res_model': 'account.move.line',
                'views': [(False, 'list'), (False, 'form')], 'domain': self._domain(extra), 'context': {'create': False}}

    def action_open_no_party(self):
        return self._open_items([('partner_id', '=', False)], _("Control-account items with no party"))

    def action_open_manual(self):
        return self._open_items(self._manual_domain(), _("Entries typed by hand on a control account"))

    def action_open_all(self):
        return self._open_items([], _("Control-account items"))


class EiSubledgerCheckLine(models.Model):
    _name = 'ei.subledger.check.line'
    _description = 'Party balances against the control account: one account'
    _order = 'id'

    check_id = fields.Many2one('ei.subledger.check', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='check_id.currency_id')
    account_id = fields.Many2one('account.account', required=True)
    balance = fields.Monetary(currency_field='currency_id')
    no_party_amount = fields.Monetary('With no party', currency_field='currency_id')
    manual_amount = fields.Monetary('Typed by hand', currency_field='currency_id')
    manual_count = fields.Integer('Hand entries')
