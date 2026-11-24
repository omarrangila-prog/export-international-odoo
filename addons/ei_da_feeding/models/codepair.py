"""Purchase code + P&L code compatibility (client, 24 Nov 2026).

The client asked for a warning when a coil carries a purchase code and a P&L code that do not belong together, e.g.
a purchase code of one mill's family with the P&L code of another. Which codes belong together is an ACCOUNTING decision, so it is
kept in an accountant-approved list (ei.code.pair), never guessed:

- a pair becomes a rule only when an accountant approves it (state 'approved');
- pairs can be SUGGESTED from the code list names (same family, e.g. ALPHA EXPORT PUR & SLS / ALPHA EXPORT P&L) to save typing,
  but a suggestion changes nothing until it is approved;
- a pair used on a real coil that is not in the list yet is recorded as 'proposed' for the accountant to confirm;
- a coil whose codes contradict approved pairs is flagged; it can be saved as a draft but not submitted, unless a person with
  the right allows it on that coil with a reason (kept on the coil)."""
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

FAMILY = re.compile(r'\s*(PUR\s*&\s*SLS|P\s*&\s*L)\s*$', re.I)


def family(name):
    """'ALPHA EXPORT PUR & SLS' -> 'ALPHA EXPORT'; 'ALPHA EXPORT P&L' -> 'ALPHA EXPORT'; anything else -> ''."""
    name = (name or '').strip().upper()
    return FAMILY.sub('', name).strip() if FAMILY.search(name) else ''


class EiCodePair(models.Model):
    _name = 'ei.code.pair'
    _description = 'Purchase code and P&L code that belong together'
    _inherit = ['mail.thread']
    _order = 'state, trade_code_id, pl_code_id'

    trade_code_id = fields.Many2one('ei.legacy.code', string='Purchase code', required=True, index=True,
                                    domain="[('source_sheet_key', '=', 'FOR PURCHASE')]", tracking=True)
    pl_code_id = fields.Many2one('ei.legacy.code', string='P&L code', required=True, index=True,
                                 domain="[('source_sheet_key', '=', 'PROFIT & LOSS')]", tracking=True)
    supplier_id = fields.Many2one('res.partner', string='Only for supplier', index=True,
                                  help="Empty: the pair holds for every supplier.")
    purchase_in_id = fields.Many2one('res.partner', string='Only for Purchased By (IN)', index=True,
                                     help="Empty: the pair holds for every buying entity.")
    state = fields.Selection([('suggested', 'Suggested from the code names'), ('proposed', 'Used on a coil, to confirm'),
                              ('approved', 'Approved'), ('rejected', 'Rejected')], default='proposed', required=True, tracking=True, index=True)
    uses = fields.Integer('Coils using it', default=0, readonly=True)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    note = fields.Char()
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)

    _uniq = models.Constraint('unique(company_id, trade_code_id, pl_code_id, supplier_id, purchase_in_id)',
                              'This pair is already in the list.')

    @api.depends('trade_code_id', 'pl_code_id')
    def _compute_display_name(self):
        for p in self:
            p.display_name = '%s %s + %s %s' % (p.trade_code_id.legacy_code or '', p.trade_code_id.original_name or '',
                                                p.pl_code_id.legacy_code or '', p.pl_code_id.original_name or '')

    # ------------------------------------------------------------------ who decides
    @api.model
    def can_decide(self):
        u = self.env.user
        return u.has_group('ei_legacy_master.group_ei_mapping_approver') or u.has_group('ei_contract_da.group_ei_formula_approver') \
            or u.has_group('base.group_system')

    def _decide(self, state):
        if not self.can_decide():
            raise AccessError(_("Only the accountant (code mapping approver) approves or rejects code pairs."))
        vals = {'state': state}
        if state == 'approved':
            vals.update(approved_by=self.env.user.id, approved_at=fields.Datetime.now())
        self.write(vals)
        for p in self:
            p.message_post(body=_("%(s)s by %(u)s.", s=dict(self._fields['state'].selection)[state], u=self.env.user.name))
        return True

    def action_approve(self):
        return self._decide('approved')

    def action_reject(self):
        return self._decide('rejected')

    @api.model
    def action_suggest(self):
        """Suggest pairs whose names are the same family (X PUR & SLS / X P&L). Suggestions are NOT rules until approved."""
        Code = self.env['ei.legacy.code'].sudo()
        pls = {}
        for c in Code.search([('source_sheet_key', '=', 'PROFIT & LOSS'), ('verification_status', '!=', 'rejected')]):
            f = family(c.original_name)
            if f:
                pls.setdefault(f, []).append(c)
        made = 0
        for t in Code.search([('source_sheet_key', '=', 'FOR PURCHASE'), ('verification_status', '!=', 'rejected')]):
            for pl in pls.get(family(t.original_name), []) if family(t.original_name) else []:
                if not self.sudo().search_count([('trade_code_id', '=', t.id), ('pl_code_id', '=', pl.id), ('supplier_id', '=', False),
                                                  ('purchase_in_id', '=', False)]):
                    self.sudo().create({'trade_code_id': t.id, 'pl_code_id': pl.id, 'state': 'suggested',
                                        'note': _("Same name family: %s", family(t.original_name))})
                    made += 1
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'message': _("%s pair(s) suggested from the code names. Check each one and approve it.", made), 'type': 'info',
                           'next': {'type': 'ir.actions.act_window_close'}}}

    # ------------------------------------------------------------------ the check
    def _scope(self, supplier, pin):
        return ['&', '|', ('supplier_id', '=', False), ('supplier_id', '=', supplier.id or 0),
                '|', ('purchase_in_id', '=', False), ('purchase_in_id', '=', pin.id or 0)]

    @api.model
    def check(self, supplier, pin, trade, pl):
        """{'status': ok | mismatch | unverified | incomplete, 'message', 'pl': [eligible P&L codes], 'trade': [eligible purchase codes]}"""
        P = self.sudo()
        if not trade or not pl:
            return {'status': 'incomplete', 'message': '', 'pl': [], 'trade': []}
        base = [('state', '=', 'approved')] + self._scope(supplier, pin)
        exact = P.search(base + [('trade_code_id', '=', trade.id), ('pl_code_id', '=', pl.id)], limit=1)
        if exact:
            return {'status': 'ok', 'message': _("These codes belong together (approved by the accountant)."), 'pl': [], 'trade': []}
        with_trade = P.search(base + [('trade_code_id', '=', trade.id)])
        with_pl = P.search(base + [('pl_code_id', '=', pl.id)])
        if with_trade or with_pl:
            parts = []
            if with_trade:
                parts.append(_("purchase code %(t)s goes with P&L %(p)s", t=self._label(trade),
                               p=_(' or ').join(self._label(x) for x in with_trade.mapped('pl_code_id'))))
            if with_pl:
                parts.append(_("P&L %(p)s goes with purchase code %(t)s", p=self._label(pl),
                               t=_(' or ').join(self._label(x) for x in with_pl.mapped('trade_code_id'))))
            return {'status': 'mismatch',
                    'message': _("Please check these codes: %s. Choose the matching code, or a person with the right allows this "
                                 "pair on this coil with a reason.", '; '.join(parts)),
                    'pl': [self._out(c) for c in with_trade.mapped('pl_code_id')], 'trade': [self._out(c) for c in with_pl.mapped('trade_code_id')]}
        return {'status': 'unverified', 'pl': [], 'trade': [],
                'message': _("This purchase code and P&L code are not in the accountant's list yet; they are sent to the accountant to confirm.")}

    def _label(self, c):
        return '%s %s' % (c.legacy_code, c.original_name)

    def _out(self, c):
        return {'id': c.id, 'code': c.legacy_code, 'name': c.original_name, 'nick': c.nickname or '', 'verified': c.verification_status == 'approved'}

    @api.model
    def record_use(self, supplier, pin, trade, pl):
        """A pair used on a saved coil: counted, and when it is not in the list at all, put there for the accountant to confirm."""
        if not trade or not pl:
            return
        P = self.sudo()
        p = P.search([('trade_code_id', '=', trade.id), ('pl_code_id', '=', pl.id)] + self._scope(supplier, pin), limit=1)
        if p:
            p.uses += 1
        else:
            P.create({'trade_code_id': trade.id, 'pl_code_id': pl.id, 'supplier_id': supplier.id or False,
                      'purchase_in_id': pin.id or False, 'state': 'proposed', 'uses': 1})

    @api.model
    def single_for(self, supplier, pin):
        """The one approved pair for this supplier / buying entity, when there is exactly one (to fill the codes by themselves)."""
        ps = self.sudo().search([('state', '=', 'approved'), ('supplier_id', '=', supplier.id or 0)]
                                + (['|', ('purchase_in_id', '=', False), ('purchase_in_id', '=', pin.id)] if pin else []))
        return ps if len(ps) == 1 else self.browse()


class EiDaLinePair(models.Model):
    _inherit = 'ei.da.line'

    pair_override_reason = fields.Char('Why these codes are allowed together', readonly=True, copy=False)
    pair_override_by = fields.Many2one('res.users', readonly=True, copy=False)

    def _pair_problem(self):
        self.ensure_one()
        if not (self.trade_code_id and self.pl_code_id) or self.pair_override_reason:
            return ''
        r = self.env['ei.code.pair'].check(self.da_id.parent_partner_id, self.da_id.purchase_in_id, self.trade_code_id, self.pl_code_id)
        return r['message'] if r['status'] == 'mismatch' else ''

    def _approval_problems(self):
        out = super()._approval_problems()
        for l in self:
            p = l._pair_problem()
            if p:
                out.append(p)
        return out
