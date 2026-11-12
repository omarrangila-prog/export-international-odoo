"""Online feeding and cash book entries, fed the way the old system fed them: one amount, a CREDIT code and a DEBIT code from the
client's own code list (CUSTOMER, BANK, FOR PURCHASE, ...), the two narrations, cheque and slip numbers.

Three kinds, kept apart on purpose (client recording of 12 Nov 2026):
  * online  - a payment that reached a bank account: the DEBIT side is the bank (a BANK code), the CREDIT side the party.
              A screenshot or SMS is proof that someone SAYS it was paid; the entry is "bank-confirmed" only when it is linked to a
              line of an imported bank statement.
  * cash    - the cash book: one side is the cash box or a bank account (a BANK code such as the safe), the other side anything.
  * opening - "balance brought forward": ONE code and an amount. It is a carried balance, not a movement of the day, so it has no
              second side and is never counted as the day's receipts or payments.

What this record is NOT: an Odoo journal entry. The old codes are not yet mapped to Odoo accounts by the accountant, so nothing here
moves an Odoo account balance; the ledgers here are ledgers BY OLD CODE. That keeps a wrong guess out of the books (see docs/daybook.md).
Every entry is PKR. A different person approves it (maker-checker), and an approved entry is corrected by a reversal, never edited or
deleted."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

KINDS = [('online', 'Online feeding (bank)'), ('cash', 'Cash book'), ('opening', 'Balance brought forward')]
STATES = [('draft', 'Draft'), ('submitted', 'Waiting for approval'), ('approved', 'Approved'), ('rejected', 'Rejected'),
          ('reversed', 'Reversed')]
LOCKED = {'kind', 'date', 'particular_date', 'amount', 'credit_code_id', 'debit_code_id', 'credit_narration', 'debit_narration',
          'chq_no', 'slip_no', 'proof_ref', 'missing_code', 'missing_side', 'duplicate_ok_reason'}
MAKER_GROUP = {'online': 'ei_bank_operations.group_ei_bank_officer', 'cash': 'ei_cashbook.group_ei_cash_clerk',
               'opening': 'ei_cashbook.group_ei_cash_clerk'}
CHECKER_GROUP = {'online': 'ei_bank_operations.group_ei_bank_approver', 'cash': 'ei_cashbook.group_ei_cash_approver',
                 'opening': 'ei_cashbook.group_ei_cash_approver'}


class EiDaybookEntry(models.Model):
    _name = 'ei.daybook.entry'
    _description = 'Online feeding / cash book entry'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'ei.review.option.mixin', 'ei.approval.mixin']
    _order = 'date desc, id desc'
    _ei_flow = 'daybook'
    _ei_ap_flow = 'daybook'
    _ei_ap_waiting = ('submitted',)

    name = fields.Char('Entry no.', readonly=True, copy=False, default='New')
    kind = fields.Selection(KINDS, required=True, default='online', tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, readonly=True, index=True)
    currency_id = fields.Many2one('res.currency', required=True, readonly=True, default=lambda s: s.env.ref('base.PKR'))
    date = fields.Date('Entry date', required=True, default=fields.Date.context_today, tracking=True, index=True)
    particular_date = fields.Date('Particular date', help="The date written on the slip, SMS or cheque, when it differs from the entry date.")
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    credit_code_id = fields.Many2one('ei.legacy.code', string='Credit code', tracking=True, index=True,
                                     domain="[('verification_status', '!=', 'rejected')]")
    debit_code_id = fields.Many2one('ei.legacy.code', string='Debit code', tracking=True, index=True,
                                    domain="[('verification_status', '!=', 'rejected')]")
    credit_name = fields.Char('Credit name', related='credit_code_id.original_name')
    debit_name = fields.Char('Debit name', related='debit_code_id.original_name')
    credit_sheet = fields.Char('Credit code list', related='credit_code_id.source_sheet_key')
    debit_sheet = fields.Char('Debit code list', related='debit_code_id.source_sheet_key')
    credit_narration = fields.Char('Credit narration')
    debit_narration = fields.Char('Debit narration')
    chq_no = fields.Char('CHQ #')
    slip_no = fields.Char('SLIP #')
    proof_ref = fields.Char('Bank SMS / transaction ref.', help="The reference printed on the bank SMS, slip or screenshot. Two entries "
                                                                "cannot carry the same reference.")
    missing_code = fields.Char('Code not in the code list',
                               help="A code written on the paper that is not in the code list (a code the old system had but the supplied list does not). The entry can be kept "
                                    "as a draft but cannot be submitted until the accountant confirms the code; nothing is guessed.")
    missing_side = fields.Selection([('credit', 'Credit'), ('debit', 'Debit')], string='Side of the missing code')
    duplicate_ok_reason = fields.Char('Why this is not a duplicate',
                                      help="Only when another entry has the same date, amount and codes and both are real.")
    state = fields.Selection(STATES, default='draft', required=True, readonly=True, tracking=True, index=True)
    maker_id = fields.Many2one('res.users', 'Entered by', readonly=True, default=lambda s: s.env.user)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    reject_reason = fields.Char(readonly=True, copy=False)
    reverse_reason = fields.Char(readonly=True, copy=False)
    reversal_id = fields.Many2one('ei.daybook.entry', 'Reversed by', readonly=True, copy=False)
    reversal_of_id = fields.Many2one('ei.daybook.entry', 'Reverses', readonly=True, copy=False)
    bank_line_id = fields.Many2one('ei.bank.import.line', 'Bank statement line', copy=False, tracking=True,
                                   help="The line of an imported bank statement that shows this money. Only then is the entry bank-confirmed.")
    bank_status = fields.Selection([('entered', 'Entered, no proof'), ('proof', 'Proof received, not bank-confirmed'),
                                    ('confirmed', 'Bank-confirmed (statement line)')], compute='_compute_bank_status', string='Bank status')
    attachment_count = fields.Integer('Proof attached', compute='_compute_attachment_count')
    code_warning = fields.Char('Code check', compute='_compute_code_warning')
    books_note = fields.Char('Books', compute='_compute_books_note')

    # ------------------------------------------------------------------ computed
    def _compute_attachment_count(self):
        data = dict(self.env['ir.attachment']._read_group([('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.attachment_count = data.get(r.id, 0)

    @api.depends('kind', 'proof_ref', 'bank_line_id')
    def _compute_bank_status(self):
        for r in self:
            if r.kind != 'online':
                r.bank_status = False
            elif r.bank_line_id:
                r.bank_status = 'confirmed'
            elif r.proof_ref or r.attachment_count:
                r.bank_status = 'proof'
            else:
                r.bank_status = 'entered'

    @api.depends('credit_code_id', 'debit_code_id', 'missing_code')
    def _compute_code_warning(self):
        for r in self:
            r.code_warning = ' '.join(r._warnings()) or False

    def _compute_books_note(self):
        for r in self:
            r.books_note = _("Kept in the day book by old code. Not an Odoo journal entry: the old codes are not mapped to Odoo accounts yet.")

    @property
    def _ei_ap_group(self):
        return CHECKER_GROUP.get(self[:1].kind or 'online')

    @api.depends('name', 'kind', 'amount')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s %s' % (r.name or _('New'), dict(KINDS).get(r.kind, ''))

    # ------------------------------------------------------------------ checks
    def _sides(self):
        return [c for c in (self.credit_code_id, self.debit_code_id) if c]

    def _shape_problems(self):
        """Plain-words reasons the codes do not fit the kind of entry (checked on save)."""
        self.ensure_one()
        out = []
        c_cr, c_dr = self.credit_code_id, self.debit_code_id
        if c_cr and c_dr and c_cr == c_dr:
            out.append(_("The credit and debit code are the same (%s).", c_cr.legacy_code))
        if self.missing_code and not self.missing_side:
            out.append(_("Say on which side the missing code %s belongs.", self.missing_code))
        if self.missing_code and self.missing_side and self['%s_code_id' % self.missing_side]:
            out.append(_("The %s side has a code already; the missing code goes on the other side.", self.missing_side))
        if self.kind == 'online' and not self.reversal_of_id:          # a reversal swaps the sides on purpose
            if c_dr and c_dr.source_sheet_key != 'BANK':
                out.append(_("Online feeding: the DEBIT side is the bank that received the money. %(c)s %(n)s is a %(s)s code, not a BANK code.",
                             c=c_dr.legacy_code, n=c_dr.original_name, s=c_dr.source_sheet_key))
        elif self.kind == 'cash':
            if c_cr and c_dr and 'BANK' not in (c_cr.source_sheet_key, c_dr.source_sheet_key):
                out.append(_("Cash book: one side is the cash box or a bank (a BANK code, such as the safe)."))
        elif self.kind == 'opening':
            if c_cr and c_dr:
                out.append(_("A balance brought forward has ONE code: it is a carried balance, not a movement with two sides."))
            if self.missing_code:
                out.append(_("A balance brought forward needs a code from the code list."))
            for c in self._sides():
                if c.source_sheet_key != 'BANK':
                    out.append(_("A balance brought forward here is for the cash box or a bank (a BANK code); %(c)s is a %(s)s code.",
                                 c=c.legacy_code, s=c.source_sheet_key))
        return out

    def _submit_problems(self):
        """Why the entry cannot go to the checker yet (empty: it can)."""
        self.ensure_one()
        out = list(self._shape_problems())
        if self.amount <= 0:
            out.append(_("Type the amount (more than zero)."))
        if self.missing_code:
            out.append(_("Code %s is not in the code list. The accountant must confirm the code and what it is before this entry can be "
                         "submitted; nothing is guessed.", self.missing_code))
        if self.kind == 'opening':
            if len(self._sides()) != 1:
                out.append(_("Choose the one code whose balance is brought forward."))
        else:
            if not self.credit_code_id and not (self.missing_code and self.missing_side == 'credit'):
                out.append(_("Choose the CREDIT code."))
            if not self.debit_code_id and not (self.missing_code and self.missing_side == 'debit'):
                out.append(_("Choose the DEBIT code."))
        return out

    def _warnings(self):
        self.ensure_one()
        out = []
        for c in self._sides():
            if c.verification_status != 'approved':
                out.append(_("Code %(c)s %(n)s is not yet verified by the accountant.", c=c.legacy_code, n=c.original_name))
        if self.missing_code:
            out.append(_("Code %s is not in the code list: needs the accountant.", self.missing_code))
        return out

    @api.constrains('amount')
    def _check_amount(self):
        for r in self:
            if r.amount < 0:
                raise UserError(_("The amount cannot be negative. Swap the credit and debit codes instead."))

    @api.constrains('currency_id')
    def _check_currency(self):
        for r in self:
            if r.currency_id.name != 'PKR':
                raise UserError(_("New entries are in PKR only (got %s).", r.currency_id.name))

    @api.constrains('kind', 'credit_code_id', 'debit_code_id', 'missing_code', 'missing_side')
    def _check_shape(self):
        for r in self:
            problems = r._shape_problems()
            if problems:
                raise UserError('\n'.join(problems))

    @api.constrains('kind', 'date', 'amount', 'credit_code_id', 'debit_code_id', 'proof_ref', 'duplicate_ok_reason', 'state')
    def _check_duplicate(self):
        for r in self.filtered(lambda x: x.state not in ('rejected', 'reversed') and not x.reversal_of_id):
            live = [('id', '!=', r.id), ('company_id', '=', r.company_id.id), ('state', 'not in', ('rejected', 'reversed')),
                    ('reversal_of_id', '=', False)]
            if r.proof_ref:
                twin = self.search(live + [('proof_ref', '=ilike', r.proof_ref.strip())], limit=1)
                if twin:
                    raise UserError(_("Bank reference %(p)s is already on %(n)s. The same payment cannot be fed twice.", p=r.proof_ref, n=twin.name))
            if r.kind == 'opening':
                code = r.credit_code_id or r.debit_code_id
                if code and self.search_count(live + [('kind', '=', 'opening'), ('date', '=', r.date), '|',
                                                      ('credit_code_id', '=', code.id), ('debit_code_id', '=', code.id)]):
                    raise UserError(_("%(c)s already has a balance brought forward on %(d)s.", c=code.legacy_code, d=r.date))
                continue
            if r.amount and not (r.duplicate_ok_reason or '').strip():
                twin = self.search(live + [('kind', '=', r.kind), ('date', '=', r.date), ('amount', '=', r.amount),
                                           ('credit_code_id', '=', r.credit_code_id.id), ('debit_code_id', '=', r.debit_code_id.id)], limit=1)
                if twin and r.credit_code_id and r.debit_code_id:
                    raise UserError(_("%(n)s already has the same date, amount and codes. If both are real, write why under "
                                      "'Why this is not a duplicate'.", n=twin.name))

    # ------------------------------------------------------------------ create / write / delete
    def _check_maker_role(self, kind):
        if self.env.su or self.env.context.get('ei_system'):
            return
        if not self.env.user.has_group(MAKER_GROUP[kind]) and not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Your role cannot enter %s entries.", dict(KINDS)[kind].lower()))

    @api.model_create_multi
    def create(self, vals_list):
        pkr = self.env.ref('base.PKR')
        for v in vals_list:
            self._check_maker_role(v.get('kind') or 'online')
            if v.get('currency_id') and v['currency_id'] != pkr.id:
                raise UserError(_("New entries are in PKR only."))
            v['currency_id'] = pkr.id
            if v.get('name', 'New') == 'New':
                v['name'] = self.env['ir.sequence'].next_by_code('ei.daybook.entry') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('ei_system'):
            if LOCKED & set(vals) and any(r.state != 'draft' for r in self):
                raise UserError(_("Only a draft entry can be changed. An approved entry is corrected with Reverse."))
            if 'kind' in vals:
                self._check_maker_role(vals['kind'])
            if 'bank_line_id' in vals and not (self.env.user.has_group('ei_bank_operations.group_ei_bank_officer')
                                                or self.env.user.has_group('ei_bank_operations.group_ei_bank_approver') or self.env.su):
                raise AccessError(_("Only the bank desk links a bank statement line."))
            if 'currency_id' in vals and self.env['res.currency'].browse(vals['currency_id']).name != 'PKR':
                raise UserError(_("New entries are in PKR only."))
        return super().write(vals)

    def unlink(self):
        """Delete Draft: only a draft that never reached a checker in its current form. Anything else is reversed."""
        for r in self:
            if r.state != 'draft':
                raise UserError(_("%s is not a draft. An approved entry is corrected with Reverse, never deleted.", r.name))
            if self.env['ei.approval.request'].sudo()._pending_for(r):
                raise UserError(_("%s is waiting for approval; withdraw it first.", r.name))
        for r in self:
            self.env['ei.daybook.deleted'].sudo().create({'name': r.name, 'kind': r.kind, 'date': r.date, 'amount': r.amount,
                                                          'credit': r.credit_code_id.display_name or r.missing_code or '',
                                                          'debit': r.debit_code_id.display_name or '', 'deleted_by': self.env.user.id})
        return super().unlink()

    def action_delete_draft(self):
        """The Delete draft button: deletes, then goes back to the list the entry came from."""
        kind = self[:1].kind
        self.unlink()
        xml = 'ei_daybook.ei_daybook_online_action' if kind == 'online' else 'ei_daybook.ei_daybook_cash_action'
        return self.env['ir.actions.act_window']._for_xml_id(xml)

    def _sys(self, vals):
        return self.with_context(ei_system=True).write(vals)

    # ------------------------------------------------------------------ workflow
    def action_submit(self):
        """Save & Submit: checked, then sent to a different person (or confirmed at once if approval is switched off)."""
        for r in self:
            if r.state != 'draft':
                raise UserError(_("%s is not a draft.", r.name))
            if r.maker_id != self.env.user and not self.env.su and not self.env.user.has_group('base.group_system'):
                raise AccessError(_("Only the person who entered %s submits it.", r.name))
            problems = r._submit_problems()
            if problems:
                raise UserError(_("%(n)s cannot be submitted yet:\n- %(p)s", n=r.name, p='\n- '.join(problems)))
            r._sys({'state': 'submitted'})
            if r._approval_required():
                self.env['ei.approval.request']._submit(r)
            else:
                r.with_context(ei_ap_deciding=True)._ei_ap_do_approve()
        return True

    def action_approve(self):
        if self.env.context.get('ei_ap_deciding'):
            return self._ei_ap_do_approve()
        return self._ei_ap_route_approve()

    def _ei_ap_do_approve(self):
        for r in self:
            if r.state != 'submitted':
                raise UserError(_("Only an entry waiting for approval can be approved."))
            problems = r._submit_problems()
            if problems:
                raise UserError('\n'.join(problems))
            r._sys({'state': 'approved', 'approved_by': self.env.user.id, 'approved_at': fields.Datetime.now()})
        return True

    def _ei_ap_do_submit(self):
        return self.action_submit()

    def _ei_ap_do_return(self, reason):
        self._sys({'state': 'draft'})

    def _ei_ap_do_reject(self, reason):
        self._sys({'state': 'rejected', 'reject_reason': reason})

    def _ei_ap_after_approved(self):
        if self.kind == 'opening':
            return _("Balance brought forward recorded (a carried balance, not a movement of the day).")
        return _("In the day book and the ledgers by code.")

    def action_withdraw(self):
        Req = self.env['ei.approval.request']
        for r in self:
            req = Req._pending_for(r)
            if not req:
                raise UserError(_("%s is not waiting for approval.", r.name))
            Req.browse(req.id).action_withdraw()
        return True

    def action_reverse(self, reason=None):
        """An approved entry is corrected by an equal entry with the sides swapped, approved by the person who reverses it. Both stay."""
        for r in self:
            if r.state != 'approved' or r.reversal_of_id:
                raise UserError(_("Only an approved entry can be reversed (%s is %s).", r.name, dict(STATES)[r.state].lower()))
            if not (reason or '').strip():
                raise UserError(_("Write why it is reversed."))
            if not (self.env.user.has_group(CHECKER_GROUP[r.kind]) or self.env.su):
                raise AccessError(_("Only a checker of %s entries can reverse one.", dict(KINDS)[r.kind].lower()))
            if self.env.user == r.maker_id and not self.env.su:
                raise AccessError(_("Maker-checker: you entered %s, so a different person reverses it.", r.name))
            rev = r.sudo().with_context(ei_system=True).create({
                'kind': r.kind, 'date': fields.Date.context_today(self), 'particular_date': r.date, 'amount': r.amount,
                'credit_code_id': r.debit_code_id.id, 'debit_code_id': r.credit_code_id.id,
                'credit_narration': _("Reversal of %(n)s: %(w)s", n=r.name, w=reason.strip()),
                'debit_narration': _("Reversal of %(n)s: %(w)s", n=r.name, w=reason.strip()),
                'reversal_of_id': r.id, 'state': 'approved', 'maker_id': self.env.user.id,
                'approved_by': self.env.user.id, 'approved_at': fields.Datetime.now()})
            r._sys({'state': 'reversed', 'reverse_reason': reason.strip(), 'reversal_id': rev.id})
            r.message_post(body=_("Reversed by %(u)s with %(n)s: %(w)s", u=self.env.user.name, n=rev.name, w=reason.strip()))
        return True

    def action_open_reverse_wizard(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.reason.wizard', 'view_mode': 'form', 'target': 'new',
                'views': [(False, 'form')], 'name': _("Reverse %s", self.name),
                'context': {'default_res_model': self._name, 'default_method': 'action_reverse', 'active_ids': self.ids, 'active_id': self.id}}

    def action_open_ledger(self):
        self.ensure_one()
        codes = [c.id for c in self._sides()]
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.daybook.leg', 'name': _("Ledger of the codes of %s", self.name),
                'views': [(False, 'list')], 'domain': [('code_id', 'in', codes)],
                'context': {'search_default_g_code': 1, 'search_default_f_approved': 1}}

    # ------------------------------------------------------------------ approval centre
    def _ei_ap_info(self):
        party = self.credit_code_id if self.kind == 'online' else (self.debit_code_id or self.credit_code_id)
        partner = self.env['res.partner']
        if party.linked_model == 'res.partner' and party.linked_res_id:
            partner = partner.browse(party.linked_res_id).exists()
        return {'name': _("%(k)s %(n)s", k=dict(KINDS)[self.kind], n=self.name), 'partner': partner, 'amount': self.amount,
                'currency': self.currency_id}

    def _ei_ap_fingerprint_values(self):
        return {'kind': self.kind, 'date': self.date, 'amount': self.amount, 'cr': self.credit_code_id.id, 'dr': self.debit_code_id.id,
                'crn': self.credit_narration, 'drn': self.debit_narration, 'chq': self.chq_no, 'slip': self.slip_no, 'ref': self.proof_ref}

    def _ei_ap_detail(self):
        money = lambda v: self._ei_ap_money(v, self.currency_id)
        code = lambda c: c and '%s %s' % (c.legacy_code, c.original_name) or ''
        head = [[_("Entry"), self.name], [_("Kind"), dict(KINDS)[self.kind]], [_("Entry date"), str(self.date or '')]]
        if self.particular_date:
            head.append([_("Particular date"), str(self.particular_date)])
        for label, val in ((_("CHQ #"), self.chq_no), (_("SLIP #"), self.slip_no), (_("Bank SMS / ref."), self.proof_ref)):
            if val:
                head.append([label, val])
        if self.kind == 'online':
            head.append([_("Bank status"), dict(self._fields['bank_status']._description_selection(self.env)).get(self.bank_status, '')])
        rows = []
        if self.debit_code_id:
            rows.append([_("Debit"), code(self.debit_code_id), self.debit_sheet or '', self.debit_narration or '', money(self.amount), ''])
        if self.credit_code_id:
            rows.append([_("Credit"), code(self.credit_code_id), self.credit_sheet or '', self.credit_narration or '', '', money(self.amount)])
        return {'head': head, 'columns': [_("Side"), _("Code"), _("Code list"), _("Narration"), _("Debit"), _("Credit")], 'rows': rows,
                'warnings': self._warnings(),
                'totals': [[_("Amount"), money(self.amount)]] + ([[_("Note"), _("Carried balance, not a movement of the day")]] if self.kind == 'opening' else [])}


class EiDaybookDeleted(models.Model):
    """What a deleted draft was, so a deletion is never silent."""
    _name = 'ei.daybook.deleted'
    _description = 'Deleted draft day book entry'
    _order = 'id desc'

    name = fields.Char(readonly=True)
    kind = fields.Selection(KINDS, readonly=True)
    date = fields.Date(readonly=True)
    amount = fields.Float(readonly=True)
    credit = fields.Char(readonly=True)
    debit = fields.Char(readonly=True)
    deleted_by = fields.Many2one('res.users', readonly=True)
    deleted_at = fields.Datetime(readonly=True, default=fields.Datetime.now)


class EiReasonWizard(models.TransientModel):
    _inherit = 'ei.reason.wizard'

    def _allowed(self):
        return super()._allowed() | {('ei.daybook.entry', 'action_reverse')}
