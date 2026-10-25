from collections import Counter

from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError

from . import bank_parsing as bp

LOCKED_STATES = ('approved', 'posted', 'rejected')


class EiBankImport(models.Model):
    _name = 'ei.bank.import'
    _description = 'Bank statement import batch'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True, copy=False, default='New')
    journal_id = fields.Many2one('account.journal', required=True, readonly=True, index=True,
                                 domain="[('type', '=', 'bank')]")
    company_id = fields.Many2one(related='journal_id.company_id', store=True, index=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency')
    filename = fields.Char(readonly=True)
    file_sha256 = fields.Char('File SHA-256', readonly=True, index=True)
    source = fields.Selection([('statement_file', 'Bank statement file (CSV)'),
                               ('manual_confirmed', 'Manually keyed, confirmed against bank')],
                              default='statement_file', readonly=True)
    state = fields.Selection([
        ('received', 'Needs a look'), ('validated', 'Checked OK'), ('proposed', 'Suggestions ready'),
        ('approved', 'Approved'), ('posted', 'In the books'), ('rejected', 'Rejected'),
    ], default='received', readonly=True, tracking=True, index=True)
    opening_balance = fields.Monetary('Opening balance (per statement)', readonly=True, currency_field='currency_id')
    closing_balance = fields.Monetary('Closing balance (per statement)', readonly=True, currency_field='currency_id')
    ledger_opening = fields.Monetary('Ledger balance before first line', readonly=True, currency_field='currency_id')
    opening_diff = fields.Monetary('Opening vs ledger', readonly=True, currency_field='currency_id')
    computed_closing = fields.Monetary(compute='_compute_balances', store=True, currency_field='currency_id')
    closing_diff = fields.Monetary('Closing vs opening+lines', compute='_compute_balances', store=True,
                                   currency_field='currency_id')
    variance_note = fields.Text(help="Required to approve when a balance difference exists.")
    issues = fields.Text(readonly=True)
    line_ids = fields.One2many('ei.bank.import.line', 'import_id', readonly=True)
    n_lines = fields.Integer(compute='_compute_counts')
    n_duplicate = fields.Integer(compute='_compute_counts')
    n_open = fields.Integer('Unresolved', compute='_compute_counts')
    imported_by = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    imported_at = fields.Datetime(readonly=True, default=fields.Datetime.now)
    approved_by = fields.Many2one('res.users', readonly=True)
    posted_by = fields.Many2one('res.users', readonly=True)
    posted_at = fields.Datetime(readonly=True)
    statement_id = fields.Many2one('account.bank.statement', readonly=True)

    @api.depends('journal_id')
    def _compute_currency(self):
        for r in self:
            r.currency_id = r.journal_id.currency_id or r.journal_id.company_id.currency_id

    @api.depends('opening_balance', 'closing_balance', 'line_ids.amount', 'line_ids.state')
    def _compute_balances(self):
        for r in self:
            live = r.line_ids.filtered(lambda l: l.state != 'rejected')
            r.computed_closing = r.opening_balance + sum(live.mapped('amount'))
            r.closing_diff = r.currency_id.round(r.closing_balance - r.computed_closing) if r.currency_id else 0.0

    @api.depends('line_ids.state')
    def _compute_counts(self):
        for r in self:
            r.n_lines = len(r.line_ids)
            r.n_duplicate = len(r.line_ids.filtered(lambda l: l.state == 'duplicate'))
            r.n_open = len(r.line_ids.filtered(lambda l: l.state in ('new', 'proposed')))

    # ---------------------------------------------------------------- import
    @api.model
    def import_file(self, journal, filename, data, opening_balance, closing_balance, source='statement_file'):
        """Stage a statement. Never touches the ledger. A rejected batch keeps the audit trail."""
        if not self.env.user.has_group('ei_bank_operations.group_ei_bank_officer'):
            raise AccessError(_("Only bank officers can import statements."))
        if journal.type != 'bank':
            raise UserError(_("%s is not a bank journal.", journal.display_name))
        res = bp.parse_statement_csv(data)
        issues = list(res.errors)
        batch = self.create({
            'name': _('%(j)s statement, %(t)s', j=journal.name, t=fields.Datetime.now().strftime('%d %b %Y %H:%M')),
            'journal_id': journal.id, 'filename': filename, 'file_sha256': res.sha256, 'source': source,
            'opening_balance': opening_balance, 'closing_balance': closing_balance,
        })
        dup_file = self.search([('journal_id', '=', journal.id), ('file_sha256', '=', res.sha256),
                                ('state', '!=', 'rejected'), ('id', '!=', batch.id)], limit=1)
        if dup_file:
            issues.append(_("This exact file was already imported as %s.", dup_file.name))
        if issues:
            batch.write({'state': 'rejected', 'issues': '\n'.join(issues)})
            return batch

        Line = self.env['ei.bank.import.line']
        seen = Counter()
        vals_list = []
        for l in res.lines:
            key = (l['date'], l['amount'], '' if l['ref'] else bp.normalise_text(l['narration']), l['ref'])
            seen[key] += 1
            fp = bp.fingerprint(journal.id, l['date'], l['amount'], l['ref'], l['narration'], seen[key])
            vals_list.append({
                'import_id': batch.id, 'sequence': l['sequence'], 'date': l['date'], 'amount': l['amount'],
                'ref': l['ref'] or False, 'narration': l['narration'], 'balance': l['balance'] or 0.0,
                'has_balance': l['balance'] is not None, 'fingerprint': fp, 'state': 'new'})
        # duplicate guard: same fingerprint already live on this journal in another batch
        live = Line.search([('journal_id', '=', journal.id), ('state', 'not in', ('rejected', 'duplicate')),
                            ('fingerprint', 'in', [v['fingerprint'] for v in vals_list])])
        by_fp = {o.fingerprint: o for o in live}
        for v in vals_list:
            if v['fingerprint'] in by_fp:
                v.update(state='duplicate', duplicate_of_id=by_fp[v['fingerprint']].id)
        lines = Line.create(vals_list)
        # balance checks
        first = min(lines.mapped('date'))
        ledger = journal._ei_ledger_balance(first, inclusive=False)
        batch.write({'ledger_opening': ledger, 'opening_diff': batch.currency_id.round(opening_balance - ledger)})
        if not batch.currency_id.is_zero(batch.opening_diff):
            issues.append(_("Opening balance %(o)s differs from ledger %(l)s before %(d)s.",
                            o=opening_balance, l=ledger, d=first))
        if not batch.currency_id.is_zero(batch.closing_diff):
            issues.append(_("Closing balance %(c)s differs from opening + lines %(x)s.",
                            c=closing_balance, x=batch.computed_closing))
        running = None
        for line in lines.sorted('sequence'):
            if line.has_balance and running is not None and not batch.currency_id.is_zero(
                    line.balance - (running + line.amount)):
                issues.append(_("Running balance breaks at statement line %s.", line.sequence))
            running = line.balance if line.has_balance else None
        batch.write({'issues': '\n'.join(issues) or False, 'state': 'received' if issues else 'validated'})
        return batch

    # ---------------------------------------------------------------- suggest
    def action_suggest(self):
        for b in self:
            if b.state in LOCKED_STATES:
                raise UserError(_("Batch %s is %s.", b.name, b.state))
            b.line_ids.filtered(lambda l: l.state in ('new', 'proposed'))._suggest_partner()
            if b.state in ('validated', 'received') and not b.issues:
                b.state = 'proposed'

    # -------------------------------------------------------------- approval
    def _param_strict(self):
        return self.env['ir.config_parameter'].sudo().get_bool('ei_bank_operations.strict_separation', True)

    def action_approve(self):
        if not self.env.user.has_group('ei_bank_operations.group_ei_bank_approver'):
            raise AccessError(_("Only a bank approver can approve an import."))
        for b in self:
            if b.imported_by == self.env.user and not self.env.su:
                raise AccessError(_("Separation of duties: the importer cannot approve the same batch."))
            if b.state not in ('validated', 'proposed', 'received'):
                raise UserError(_("Batch %s cannot be approved from state %s.", b.name, b.state))
            if b.n_open:
                raise UserError(_("%s lines are not yet resolved (verify a partner, mark unidentified, "
                                  "reject, or confirm as duplicate).", b.n_open))
            has_diff = b.issues or not b.currency_id.is_zero(b.closing_diff) or not b.currency_id.is_zero(b.opening_diff)
            if has_diff and not (b.variance_note or '').strip():
                raise UserError(_("Balance differences exist; write the explanation in 'Variance note' first."))
            if not b.line_ids.filtered(lambda l: l.state in ('verified', 'unidentified')):
                raise UserError(_("No postable lines in this batch."))
            b.write({'state': 'approved', 'approved_by': self.env.user.id})

    def action_reject(self):
        for b in self:
            if b.state in ('posted', 'rejected'):
                raise UserError(_("Batch %s is already %s.", b.name, b.state))
            if not self.env.user.has_group('ei_bank_operations.group_ei_bank_approver'):
                raise AccessError(_("Only a bank approver can reject an import."))
            b.write({'state': 'rejected'})
            b.line_ids.filtered(lambda l: l.state != 'posted').write({'state': 'rejected'})

    # ------------------------------------------------------------------ post
    def action_post(self):
        if not self.env.user.has_group('ei_bank_operations.group_ei_bank_poster'):
            raise AccessError(_("Only a bank posting user can post to the ledger."))
        for b in self:
            if b.state != 'approved':
                raise UserError(_("Only an approved batch can be posted."))
            if not self.env.su:
                if b.imported_by == self.env.user:
                    raise AccessError(_("Separation of duties: the importer cannot post the batch."))
                if self._param_strict() and b.approved_by == self.env.user:
                    raise AccessError(_("Separation of duties: the approver cannot post the batch."))
            todo = b.line_ids.filtered(lambda l: l.state in ('verified', 'unidentified')).sorted('sequence')
            live = self.env['ei.bank.import.line'].search([
                ('journal_id', '=', b.journal_id.id), ('state', '=', 'posted'),
                ('fingerprint', 'in', todo.mapped('fingerprint'))])
            if live:
                raise UserError(_("Line(s) %s were already posted by another batch; reject duplicates first.",
                                  ', '.join(live.mapped('fingerprint'))[:80]))
            statement = self.env['account.bank.statement'].create({
                'name': b.name, 'journal_id': b.journal_id.id, 'date': max(todo.mapped('date')),
                'balance_start': b.opening_balance, 'balance_end_real': b.closing_balance,
            })
            for line in todo:
                line._post_to_ledger(statement)
            b.write({'state': 'posted', 'posted_by': self.env.user.id, 'posted_at': fields.Datetime.now(),
                     'statement_id': statement.id})


class EiBankImportLine(models.Model):
    _name = 'ei.bank.import.line'
    _description = 'Staged bank line'
    _inherit = ['mail.thread']
    _order = 'import_id desc, sequence'

    import_id = fields.Many2one('ei.bank.import', required=True, ondelete='restrict', index=True, readonly=True)
    journal_id = fields.Many2one(related='import_id.journal_id', store=True, index=True)
    company_id = fields.Many2one(related='import_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='import_id.currency_id')
    imported_on = fields.Date(compute='_compute_imported_on', store=True)
    sequence = fields.Integer(readonly=True)
    date = fields.Date(readonly=True)
    amount = fields.Monetary(readonly=True, currency_field='currency_id', help="Positive = receipt, negative = payment.")
    ref = fields.Char('Bank reference', readonly=True)
    narration = fields.Char(readonly=True)
    balance = fields.Monetary(readonly=True, currency_field='currency_id')
    has_balance = fields.Boolean(readonly=True)
    fingerprint = fields.Char(readonly=True, index=True)
    state = fields.Selection([
        ('new', 'To check'), ('proposed', 'Suggestion ready'), ('verified', 'Party confirmed'),
        ('unidentified', 'Unidentified'), ('duplicate', 'Duplicate'),
        ('rejected', 'Rejected'), ('posted', 'In the books'),
    ], default='new', readonly=True, tracking=True, index=True)
    is_unidentified = fields.Boolean(readonly=True)
    duplicate_of_id = fields.Many2one('ei.bank.import.line', readonly=True)
    suggested_partner_id = fields.Many2one('res.partner', readonly=True)
    confidence = fields.Float(readonly=True, aggregator=False)
    match_note = fields.Char(readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True, string='Verified party')
    verified_by = fields.Many2one('res.users', readonly=True)
    evidence_note = fields.Text(readonly=True)
    allocation_ids = fields.One2many('ei.bank.allocation', 'line_id')
    allocated = fields.Monetary(compute='_compute_allocated', currency_field='currency_id')
    statement_line_id = fields.Many2one('account.bank.statement.line', readonly=True)

    _fp_live = models.UniqueIndex("(journal_id, fingerprint) WHERE state IN ('new','proposed','verified','unidentified','posted')",
                                  "This bank line is already live on the journal (duplicate guard).")

    @api.depends('import_id.imported_at')
    def _compute_imported_on(self):
        for r in self:
            r.imported_on = fields.Date.to_date(r.import_id.imported_at)

    @api.depends('allocation_ids.amount')
    def _compute_allocated(self):
        for r in self:
            r.allocated = sum(r.allocation_ids.mapped('amount'))

    def _check_editable(self):
        for r in self:
            if r.import_id.state in LOCKED_STATES:
                raise UserError(_("Batch %s is %s; its lines are locked.", r.import_id.name, r.import_id.state))

    # ----------------------------------------------------------- suggestions
    def _suggest_partner(self):
        Alias = self.env['ei.partner.alias']
        aliases = Alias.search([('company_id', '=', self.env.company.id)])
        for line in self:
            narr = bp.normalise_text(line.narration)
            hits = aliases.filtered(lambda a: a.alias_norm in narr)
            approved = hits.filtered(lambda a: a.state == 'approved')
            pool = approved or hits
            partners = pool.mapped('partner_id')
            vals = {'suggested_partner_id': False, 'confidence': 0.0, 'match_note': False}
            if len(partners) == 1:
                vals.update(suggested_partner_id=partners.id, confidence=0.9 if approved else 0.4,
                            match_note=_("Alias %s (%s)", pool[0].alias, pool[0].state))
            elif len(partners) > 1:
                vals['match_note'] = _("Ambiguous: %s - human choice required", ', '.join(partners.mapped('name')))
            else:
                sign = 1 if line.amount > 0 else -1
                moves = self.env['account.move'].search([
                    ('company_id', '=', line.company_id.id), ('state', '=', 'posted'),
                    ('payment_state', 'in', ('not_paid', 'partial')),
                    ('move_type', 'in', ('out_invoice', 'in_refund') if sign > 0 else ('in_invoice', 'out_refund')),
                    ('amount_residual', '=', abs(line.amount))])
                if len(moves.partner_id) == 1:
                    vals.update(suggested_partner_id=moves.partner_id.id, confidence=0.5,
                                match_note=_("Amount equals open invoice %s", moves[0].name))
                elif len(moves) > 1:
                    vals['match_note'] = _("Amount equals %s open invoices of different parties", len(moves))
            line.write(vals)
            if vals['suggested_partner_id'] or vals['match_note']:
                line.state = 'proposed' if line.state == 'new' else line.state

    # -------------------------------------------------- human review actions
    def _check_officer(self):
        if not self.env.user.has_group('ei_bank_operations.group_ei_bank_officer'):
            raise AccessError(_("Only bank officers can review bank lines."))

    def action_verify_partner(self, partner, note=None):
        """Human confirmation of the counterparty. A suggestion alone never allocates anything."""
        self._check_officer()
        self._check_editable()
        for r in self:
            if r.state in ('duplicate', 'rejected', 'posted'):
                raise UserError(_("A %s line cannot be assigned a party.", r.state))
            if not partner:
                raise UserError(_("Choose the party."))
            needs_note = not (r.suggested_partner_id == partner and r.confidence >= 0.9)
            if needs_note and not (note or '').strip():
                raise UserError(_("Evidence note required: the party is not an approved-alias match "
                                  "(e.g. payment image checked, bank call)."))
            r.write({'partner_id': partner.id, 'state': 'verified', 'verified_by': self.env.user.id,
                     'evidence_note': note or r.evidence_note, 'is_unidentified': False})

    def action_mark_unidentified(self, note=None):
        self._check_officer()
        self._check_editable()
        for r in self:
            if r.state in ('duplicate', 'rejected', 'posted'):
                raise UserError(_("A %s line cannot be marked unidentified.", r.state))
            if r.allocation_ids:
                raise UserError(_("Remove the allocations first."))
            r.write({'partner_id': False, 'state': 'unidentified', 'is_unidentified': True,
                     'evidence_note': note or r.evidence_note, 'verified_by': self.env.user.id})

    def action_reject(self, reason=None):
        self._check_officer()
        self._check_editable()
        for r in self:
            if r.state == 'posted':
                raise UserError(_("Posted lines are corrected with a reversing entry, not rejected."))
            if not (reason or '').strip():
                raise UserError(_("A rejection reason is required."))
            r.write({'state': 'rejected', 'evidence_note': reason})

    # ----------------------------------------------------------------- post
    def _post_to_ledger(self, statement):
        self.ensure_one()
        st_line = self.env['account.bank.statement.line'].create({
            'statement_id': statement.id, 'journal_id': self.journal_id.id, 'date': self.date,
            'payment_ref': ('%s %s' % (self.ref or '', self.narration or '')).strip() or '/',
            'amount': self.amount, 'partner_id': self.partner_id.id, 'partner_name': self.partner_id.name or False,
            'transaction_details': False,
        })
        self.write({'statement_line_id': st_line.id, 'state': 'posted'})
        if self.allocation_ids:
            self.allocation_ids._apply(st_line)
        return st_line


class EiBankAllocation(models.Model):
    _name = 'ei.bank.allocation'
    _description = 'Allocation of a bank line to an invoice or bill'

    line_id = fields.Many2one('ei.bank.import.line', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='line_id.currency_id')
    partner_id = fields.Many2one(related='line_id.partner_id')
    invoice_id = fields.Many2one('account.move', required=True, domain="[('state', '=', 'posted')]")
    amount = fields.Monetary(required=True, currency_field='currency_id')

    @api.constrains('amount', 'invoice_id', 'line_id')
    def _check_alloc(self):
        for a in self:
            line = a.line_id
            if line.state in ('posted', 'duplicate', 'rejected'):
                raise UserError(_("Allocations are locked on a %s line.", line.state))
            if not line.partner_id or line.state != 'verified':
                raise UserError(_("Allocation needs a verified counterparty on the bank line first."))
            if a.amount <= 0:
                raise UserError(_("Allocation amount must be positive."))
            inv = a.invoice_id
            if inv.partner_id.commercial_partner_id != line.partner_id.commercial_partner_id:
                raise UserError(_("Invoice %s belongs to another party.", inv.name))
            if inv.company_id != line.company_id:
                raise UserError(_("Invoice %s belongs to another company.", inv.name))
            if inv.currency_id != line.currency_id:
                raise UserError(_("Foreign-currency allocation is not supported yet (invoice %s).", inv.name))
            inbound = line.amount > 0
            if inbound and inv.move_type not in ('out_invoice', 'in_refund'):
                raise UserError(_("A receipt can only settle customer invoices or vendor refunds."))
            if not inbound and inv.move_type not in ('in_invoice', 'out_refund'):
                raise UserError(_("A payment can only settle vendor bills or customer refunds."))
            if a.amount > inv.amount_residual:
                raise UserError(_("Allocation %(a)s exceeds the open amount %(r)s of %(i)s.",
                                  a=a.amount, r=inv.amount_residual, i=inv.name))
            if sum(line.allocation_ids.mapped('amount')) > abs(line.amount):
                raise UserError(_("Allocations exceed the bank line amount."))

    def _apply(self, st_line):
        """Replace (part of) the suspense leg of the statement entry by receivable/payable legs and
        reconcile each with its invoice. The remainder, if any, stays on suspense, never invented."""
        move = st_line.move_id
        _liq, suspense, _other = st_line._seek_for_lines()
        suspense = suspense[:1]
        inbound = st_line.amount > 0
        total = sum(self.mapped('amount'))
        pairs = []
        move.button_draft()
        cmds = []
        for a in self:
            inv_line = a.invoice_id.line_ids.filtered(
                lambda l: l.account_type in ('asset_receivable', 'liability_payable') and not l.reconciled)
            if len(inv_line) != 1:
                raise UserError(_("Invoice %s has no single open receivable/payable line.", a.invoice_id.name))
            cmds.append(Command.create({
                'move_id': move.id, 'account_id': inv_line.account_id.id, 'partner_id': inv_line.partner_id.id,
                'name': a.invoice_id.name, 'credit': a.amount if inbound else 0.0, 'debit': 0.0 if inbound else a.amount}))
            pairs.append(inv_line)
        remainder = abs(st_line.amount) - total
        if remainder > 0:
            cmds.append(Command.update(suspense.id, {'credit': remainder if inbound else 0.0,
                                                    'debit': 0.0 if inbound else remainder}))
        else:
            cmds.append(Command.delete(suspense.id))
        move.write({'line_ids': cmds})
        move.action_post()
        new_lines = move.line_ids.filtered(lambda l: l.account_type in ('asset_receivable', 'liability_payable'))
        for inv_line in pairs:
            mine = new_lines.filtered(lambda l: l.account_id == inv_line.account_id and not l.reconciled
                                      and l.name == inv_line.move_id.name)[:1]
            (mine + inv_line).reconcile()
