"""Daily close and month-end close: a checklist worked out from the records themselves, never ticked by hand.

Each item is OK, a warning or a blocker, says why in words and opens the records behind it. A close is signed off by a second person
only when every blocker is either cleared or waived by an accounting manager with a written reason. The signed checklist is kept as it
was (snapshot). After a month is signed, the books can be locked up to its last day through Odoo's own lock date."""
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

BANK_OPEN = ('new', 'proposed', 'verified')
BANK_ASIDE = ('unidentified', 'duplicate')


class EiClose(models.Model):
    _name = 'ei.close'
    _description = 'Day or month close'
    _inherit = ['mail.thread']
    _order = 'date_to desc, kind, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    kind = fields.Selection([('day', 'Day close'), ('month', 'Month-end close')], 'Close', required=True, default='day')
    date = fields.Date('Day (or any day of the month)', required=True, default=fields.Date.context_today)
    date_from = fields.Date('From', compute='_compute_period', store=True)
    date_to = fields.Date('To', compute='_compute_period', store=True)
    state = fields.Selection([('open', 'Open'), ('signed', 'Signed off')], default='open', readonly=True, tracking=True, index=True)
    item_ids = fields.One2many('ei.close.item', 'close_id', readonly=True)
    n_blockers = fields.Integer('Blockers', compute='_compute_counts')
    n_waived = fields.Integer('Waived', compute='_compute_counts')
    n_warnings = fields.Integer('Warnings', compute='_compute_counts')
    refreshed_by = fields.Many2one('res.users', 'Last checked by', readonly=True)
    refreshed_at = fields.Datetime('Last checked at', readonly=True)
    signed_by = fields.Many2one('res.users', readonly=True)
    signed_at = fields.Datetime(readonly=True)
    snapshot = fields.Json(readonly=True, copy=False)
    books_locked_to = fields.Date('Books locked up to', readonly=True, tracking=True)

    _uniq = models.Constraint('unique(company_id, kind, date_from)', 'This day or month already has a close.')

    @api.depends('kind', 'date')
    def _compute_period(self):
        for r in self:
            if r.kind == 'month' and r.date:
                r.date_from = r.date.replace(day=1)
                r.date_to = r.date_from + relativedelta(months=1, days=-1)
            else:
                r.date_from = r.date_to = r.date

    @api.depends('kind', 'date_from')
    def _compute_name(self):
        for r in self:
            if not r.date_from:
                r.name = False
            elif r.kind == 'month':
                r.name = _("Month-end %s", r.date_from.strftime('%B %Y'))
            else:
                r.name = _("Day close %s", r.date_from.strftime('%d %b %Y'))

    @api.depends('item_ids.status', 'item_ids.waived_by')
    def _compute_counts(self):
        for r in self:
            blockers = r.item_ids.filtered(lambda i: i.status == 'blocker')
            r.n_waived = len(blockers.filtered('waived_by'))
            r.n_blockers = len(blockers) - r.n_waived
            r.n_warnings = len(r.item_ids.filtered(lambda i: i.status == 'warning'))

    def write(self, vals):
        if not self.env.context.get('ei_system') and any(r.state == 'signed' for r in self) and set(vals) - {'message_follower_ids', 'message_main_attachment_id'}:
            raise UserError(_("A signed-off close is final."))
        return super().write(vals)

    def unlink(self):
        if any(r.state == 'signed' for r in self):
            raise UserError(_("A signed-off close is kept as evidence."))
        return super().unlink()

    # ------------------------------------------------------------------ the checklist
    def _checks(self):
        """-> list of dicts: code, label, status, count, detail, res_model, domain. Counted with sudo: the numbers are shown to whoever
        prepares the close; opening the records still follows each person's own rights."""
        self.ensure_one()
        env, c, d0, d1, month = self.env, self.company_id, self.date_from, self.date_to, self.kind == 'month'
        out = []

        def add(code, label, n, detail_bad, detail_ok, model=None, domain=None, bad='blocker'):
            out.append({'code': code, 'label': label, 'count': n, 'status': bad if n else 'ok',
                        'detail': detail_bad if n else detail_ok, 'res_model': model, 'domain': repr(domain or [])})

        def S(model):
            return env[model].sudo() if model in env else None

        banks = env['account.journal'].sudo().search([('company_id', '=', c.id), ('type', '=', 'bank')])
        cashes = env['account.journal'].sudo().search([('company_id', '=', c.id), ('type', '=', 'cash')])
        if S('ei.bank.balance.check') is not None:
            Chk = S('ei.bank.balance.check')
            missing = banks.filtered(lambda j: not Chk.search_count([('journal_id', '=', j.id), ('date', '=', d1), ('state', '=', 'signed')]))
            add('bank_balance', _("Bank balance confirmed with proof and signed off on %s", d1), len(missing),
                _("No signed-off confirmation for: %s", ', '.join(missing.mapped('name'))),
                _("Every bank account has a signed-off confirmation."),
                'ei.bank.balance.check', [('date', '=', d1), ('journal_id', 'in', banks.ids)])
            Line = S('ei.bank.import.line')
            dom = [('company_id', '=', c.id), ('date', '<=', d1), ('state', 'in', BANK_OPEN)]
            n = Line.search_count(dom)
            add('bank_lines', _("Bank lines up to %s are in the books", d1), n,
                _("%s bank lines are still to check, suggested or waiting to post.", n), _("No bank line is waiting."), 'ei.bank.import.line', dom)
            dom = [('company_id', '=', c.id), ('date', '<=', d1), ('state', 'in', BANK_ASIDE)]
            n = Line.search_count(dom)
            add('bank_aside', _("Unidentified or duplicate bank lines"), n,
                _("%s bank lines are unidentified or marked duplicate: someone must decide them.", n), _("None."), 'ei.bank.import.line', dom, bad='warning')
        if S('ei.cash.count') is not None:
            Cnt = S('ei.cash.count')
            missing = cashes.filtered(lambda j: not Cnt.search_count([('journal_id', '=', j.id), ('date', '=', d1), ('state', '=', 'closed')]))
            add('cash_count', _("Cash counted and closed on %s", d1), len(missing),
                _("No closed cash count for: %s", ', '.join(missing.mapped('name'))), _("Every cash box was counted and closed."),
                'ei.cash.count', [('date', '=', d1)])
            dom = [('company_id', '=', c.id), ('date', '<=', d1), ('state', 'in', ('draft', 'submitted'))]
            n = S('ei.cash.voucher').search_count(dom)
            add('cash_vouchers', _("Cash vouchers decided"), n, _("%s cash vouchers are draft or waiting for approval.", n), _("None waiting."),
                'ei.cash.voucher', dom)
        if S('ei.lifting') is not None:
            dom = [('company_id', '=', c.id), ('date', '<=', d1), ('state', '=', 'draft')]
            n = S('ei.lifting').search_count(dom)
            add('liftings', _("Truck loadings verified"), n, _("%s loadings are not verified: their quantity is not counted as lifted.", n),
                _("Every loading is verified."), 'ei.lifting', dom)
        if S('ei.daily.order') is not None:
            dom = [('company_id', '=', c.id), ('date', '<=', d1), ('state', '=', 'draft')]
            n = S('ei.daily.order').search_count(dom)
            add('orders', _("Daily order requests approved"), n, _("%s order requests are still drafts.", n), _("None in draft."),
                'ei.daily.order', dom, bad='warning')
        if S('ei.supplier.intake') is not None:
            dom = [('company_id', '=', c.id), ('invoice_date', '<=', d1), ('state', '=', 'mismatch')]
            n = S('ei.supplier.intake').search_count(dom)
            add('intake', _("Supplier invoices without a blocked mismatch"), n,
                _("%s supplier invoices are blocked on a mismatch.", n), _("None blocked."), 'ei.supplier.intake', dom)
        dom = [('company_id', '=', c.id), ('state', '=', 'draft'), ('date', '>=', d0), ('date', '<=', d1)]
        n = env['account.move'].sudo().search_count(dom)
        add('draft_moves', _("No draft accounting entries in the period"), n,
            _("%s invoices, bills or entries are still drafts in this period.", n), _("None."), 'account.move', dom,
            bad='blocker' if month else 'warning')
        if month:
            if S('ei.parent.statement') is not None and S('ei.contract') is not None:
                parents = S('ei.contract').search([('company_id', '=', c.id)]).parent_partner_id
                billed = env['account.move'].sudo().search([('company_id', '=', c.id), ('partner_id', 'in', parents.ids), ('state', '=', 'posted'),
                                                            ('move_type', 'in', ('in_invoice', 'in_refund')),
                                                            ('invoice_date', '>=', d0), ('invoice_date', '<=', d1)]).partner_id
                St = S('ei.parent.statement')
                missing = billed.filtered(lambda p: not St.search_count([('company_id', '=', c.id), ('partner_id', '=', p.id), ('state', '=', 'signed'),
                                                                        ('date_from', '<=', d0), ('date_to', '>=', d1)]))
                add('parent_statements', _("Parent statements for the month signed off"), len(missing),
                    _("No signed-off statement covering the month for: %s", ', '.join(missing.mapped('name'))),
                    _("Every parent company billed this month has a signed-off statement."), 'ei.parent.statement',
                    [('company_id', '=', c.id), ('date_to', '>=', d0), ('date_from', '<=', d1)])
            Sub = env['ei.subledger.check'].sudo()
            missing = [k for k in ('receivable', 'payable')
                       if not Sub.search_count([('company_id', '=', c.id), ('kind', '=', k), ('date', '=', d1), ('state', '=', 'signed')])]
            add('subledger', _("Party balances agree with the control accounts on %s", d1), len(missing),
                _("Not signed off for: %s", ', '.join(dict(Sub._fields['kind'].selection)[k] for k in missing)),
                _("Customers and suppliers both signed off."), 'ei.subledger.check', [('company_id', '=', c.id), ('date', '=', d1)])
        return out

    def action_refresh(self):
        for r in self:
            if r.state == 'signed':
                raise UserError(_("A signed-off close is final."))
            old = {i.code: i for i in r.item_ids}
            vals = []
            for seq, ch in enumerate(r._checks()):
                prev = old.get(ch['code'])
                keep = prev and prev.waived_by and ch['status'] == 'blocker' and prev.count == ch['count']   # a waiver covers what was waived, no more
                vals.append({**ch, 'sequence': seq, 'waiver_reason': prev.waiver_reason if keep else False,
                             'waived_by': prev.waived_by.id if keep else False})
            r.check_access('write')
            r.item_ids.sudo().unlink()                       # items are worked out, never typed: nobody edits them directly
            self.env['ei.close.item'].sudo().create([dict(v, close_id=r.id) for v in vals])
            r.with_context(ei_system=True).write({'refreshed_by': self.env.user.id, 'refreshed_at': fields.Datetime.now()})
        return True

    def action_sign(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only an accounting manager can sign off a close."))
        for r in self:
            if r.state == 'signed':
                continue
            r.action_refresh()                    # sign what is true now, not what was true at the last refresh
            if r.create_uid == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: the person who prepared the close cannot sign it off."))
            n_open = self.env['ei.close.item'].sudo().search_count([('close_id', '=', r.id), ('status', '=', 'blocker'), ('waived_by', '=', False)])
            if n_open:
                raise UserError(_("%s blockers are open. Clear them, or waive each one with a written reason.", n_open))
            snap = [{k: i[k] for k in ('code', 'label', 'status', 'count', 'detail', 'waiver_reason')} | {'waived_by': i.waived_by.name or ''}
                    for i in r.item_ids]
            r.with_context(ei_system=True).write({'state': 'signed', 'signed_by': self.env.user.id, 'signed_at': fields.Datetime.now(), 'snapshot': snap})

    def action_lock_books(self):
        """Odoo's own lock date: nobody can post into the closed month afterwards. Only for a signed-off month."""
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only an accounting manager can lock the books."))
        for r in self:
            if r.kind != 'month' or r.state != 'signed':
                raise UserError(_("Only a signed-off month-end close can lock the books."))
            co = r.company_id
            if co.fiscalyear_lock_date and co.fiscalyear_lock_date >= r.date_to:
                r.with_context(ei_system=True).books_locked_to = co.fiscalyear_lock_date
                continue
            co.sudo().write({'fiscalyear_lock_date': r.date_to})       # accounting manager checked above; only ever moves the lock forward
            r.with_context(ei_system=True).books_locked_to = r.date_to
            r.message_post(body=_("Books locked up to %s.", r.date_to))


class EiCloseItem(models.Model):
    _name = 'ei.close.item'
    _description = 'Close checklist item'
    _order = 'close_id, sequence, id'

    close_id = fields.Many2one('ei.close', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer()
    code = fields.Char(required=True)
    label = fields.Char('Check', required=True)
    status = fields.Selection([('ok', 'OK'), ('warning', 'Warning'), ('blocker', 'Blocker')], required=True)
    count = fields.Integer('How many')
    detail = fields.Char('What it found')
    res_model = fields.Char()
    domain = fields.Char()
    waiver_reason = fields.Char('Why waived', readonly=True)
    waived_by = fields.Many2one('res.users', readonly=True)

    def action_open(self):
        self.ensure_one()
        if not self.res_model or self.res_model not in self.env:
            return False
        from ast import literal_eval
        return {'type': 'ir.actions.act_window', 'name': self.label, 'res_model': self.res_model,
                'views': [(False, 'list'), (False, 'form')], 'domain': literal_eval(self.domain or '[]')}

    def action_waive(self, reason):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_("Only an accounting manager can waive a blocker."))
        if not (reason or '').strip():
            raise UserError(_("Write why this blocker may be waived."))
        for i in self:
            if i.close_id.state == 'signed':
                raise UserError(_("The close is signed off."))
            if i.status != 'blocker':
                raise UserError(_("Only a blocker can be waived."))
            i.sudo().write({'waiver_reason': reason.strip(), 'waived_by': self.env.user.id})
            i.close_id.message_post(body=_("Blocker waived: %(l)s. Reason: %(r)s", l=i.label, r=reason.strip()))


class EiCloseWaiveWizard(models.TransientModel):
    _name = 'ei.close.waive.wizard'
    _description = 'Waive a close blocker'

    item_id = fields.Many2one('ei.close.item', required=True)
    reason = fields.Char(required=True)

    def action_waive(self):
        self.item_id.action_waive(self.reason)
        return {'type': 'ir.actions.act_window_close'}
