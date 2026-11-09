import re
from decimal import Decimal

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from . import feeding_engine as fe

METHOD_SELECTION = [(k, v[0]) for k, v in fe.METHODS.items()]
STOP = {'M', 'S', 'MS', 'THE', 'AND', 'CO', 'LTD', 'LIMITED', 'PVT', 'PRIVATE', 'A', 'C', 'AC', 'OF'}


def name_tokens(text):
    words = re.split(r'[^A-Z0-9]+', (text or '').upper().replace('M/S', ' '))
    return {w for w in words if len(w) >= 3 and w not in STOP}


class EiDa(models.Model):
    _inherit = 'ei.da'

    printed_customer = fields.Char('Customer name printed on the DA', tracking=True,
                                   help="Exactly as on the parent's paper. It is compared with the customer code chosen on each coil.")
    order_datetime = fields.Datetime('Order date and time (printed)', tracking=True,
                                     help="The parent's own order time. Kept apart from the DA date, the day it was entered and any invoice date.")
    ship_date = fields.Date('Ship date (printed)', tracking=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', string='Currency')
    company_currency_id = fields.Many2one(related='company_id.currency_id', string='Company currency')
    fx_text = fields.Char('Exchange rate', compute='_compute_fx')

    def _fx(self):
        """None when the DA is in the company currency; else (rate record or False). The rate is Odoo's own (res.currency.rate)."""
        self.ensure_one()
        cur, comp = self.currency_id, self.company_id
        if not cur or not comp or cur == comp.currency_id:
            return None
        rate = self.env['res.currency.rate'].search([('currency_id', '=', cur.id), ('name', '<=', self.date),
                                                     ('company_id', 'in', [comp.id, False])], order='name desc', limit=1)
        return rate or False            # an empty recordset is not False: callers test `is False`

    @api.depends('currency_id', 'date', 'company_id')
    def _compute_fx(self):
        for d in self:
            fx = d._fx()
            if fx is None:
                d.fx_text = False
            elif not fx:
                d.fx_text = _("No %(c)s rate on or before %(d)s: it cannot be approved until the accountant enters one.",
                              c=d.currency_id.name, d=d.date)
            else:
                d.fx_text = _("1 %(c)s = %(r)s %(b)s (rate of %(d)s)", c=d.currency_id.name,
                              r=round(1 / fx.rate, 4) if fx.rate else '?', b=d.company_id.currency_id.name, d=fx.name)

    def _check_before_approval(self):
        res = super()._check_before_approval()
        for d in self:
            problems = []
            fed = d.line_ids.filtered('feeding_method')
            if fed and d._fx() is False:
                problems.append(d.fx_text)
            for l in fed:
                problems += ['%s: %s' % (l.coil_no or l.product_id.display_name, p) for p in l._approval_problems()]
            if problems:
                raise UserError(_("DA %(n)s cannot be approved yet:\n- %(p)s", n=d.name, p='\n- '.join(problems)))
        return res


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    coil_no = fields.Char('Coil number', index=True)
    coil_grade = fields.Char('Grade')
    weight_kg = fields.Float('Weight (kg)', digits=(16, 2), help="As printed. MTL = kg / 1,000.")
    feeding_method = fields.Selection(METHOD_SELECTION, string='Feeding method')
    basic_rate = fields.Monetary('Basic rate / MTL', currency_field='currency_id')
    sale_offset = fields.Monetary('Sale = mill rate +/-', currency_field='currency_id')
    sale_typed = fields.Boolean('Sale rate typed', help="The sale rate was typed instead of mill rate +/- an amount.")
    cn_amount = fields.Monetary('Credit note on this coil', currency_field='currency_id')
    cn_text = fields.Char('Credit note text (this coil)')
    feeding_calc = fields.Json('Calculation', readonly=True, copy=False)
    currency_id = fields.Many2one(related='da_id.contract_id.currency_id', store=True)
    spread_per_mtl = fields.Monetary('Spread / MTL', compute='_compute_spread', store=True, currency_field='currency_id', aggregator='avg')
    gross_spread = fields.Monetary('Gross spread (coil)', compute='_compute_spread', store=True, currency_field='currency_id',
                                   help="MTL x spread. Before costs and taxes; not booked profit.")
    result = fields.Selection([('profit', 'Profit'), ('even', 'Break-even'), ('loss', 'Loss')], compute='_compute_spread', store=True)
    cn_commission = fields.Monetary('Taken off the CN', compute='_compute_cn', store=True, currency_field='currency_id',
                                    help="From the saved calculation (the formula's own percentage).")
    net_cn = fields.Monetary('Net CN / MTL', compute='_compute_cn', store=True, currency_field='currency_id')
    cn_total = fields.Monetary('Net CN for the coil', compute='_compute_cn', store=True, currency_field='currency_id',
                               help="Net CN per MTL x the coil's MTL, as the examples treat a CN per ton (to be confirmed by the client).")
    da_date = fields.Date(related='da_id.date', store=True, string='DA date')
    da_parent_id = fields.Many2one(related='da_id.parent_partner_id', store=True, string='Parent company')
    formula_text = fields.Char('Formula used', compute='_compute_cn', store=True)
    loss_reason = fields.Char('Why sold below cost')
    customer_code_id = fields.Many2one('ei.legacy.code', string='Customer code', domain="[('source_sheet_key', '=', 'CUSTOMER')]")
    trade_code_id = fields.Many2one('ei.legacy.code', string='Purchase / sale code', domain="[('source_sheet_key', '=', 'FOR PURCHASE')]")
    pl_code_id = fields.Many2one('ei.legacy.code', string='P&L code', domain="[('source_sheet_key', '=', 'PROFIT & LOSS')]")
    code_override_reason = fields.Char('Why the printed name may differ', readonly=True)
    code_override_by = fields.Many2one('res.users', readonly=True)
    code_issue = fields.Char(compute='_compute_code_issue')

    _coil_uniq = models.Constraint('unique(da_id, coil_no)', 'This coil number is already on this DA.')

    @api.depends('purchase_rate', 'sale_rate', 'mtl')
    def _compute_spread(self):
        for l in self:
            spread = fe.money(Decimal(str(l.sale_rate or 0)) - Decimal(str(l.purchase_rate or 0)))
            l.spread_per_mtl = float(spread)
            l.gross_spread = float(fe.money(spread * Decimal(str(l.mtl or 0))))
            l.result = 'profit' if spread > 0 else 'loss' if spread < 0 else 'even'

    @api.depends('feeding_calc', 'mtl')
    def _compute_cn(self):
        for l in self:
            calc = l.feeding_calc or {}
            rows = {r.get('key'): r.get('value') for r in calc.get('rows') or []}
            l.cn_commission = float(rows.get('cn_commission') or 0)
            l.net_cn = float(rows.get('net_cn') or 0)
            l.cn_total = float(fe.money(Decimal(str(rows.get('net_cn') or 0)) * Decimal(str(l.mtl or 0))))
            f = calc.get('formula')
            l.formula_text = f and '%s v%s' % (f.get('code'), f.get('version')) or (_("Typed rates") if calc else False)

    @api.constrains('customer_code_id', 'trade_code_id', 'pl_code_id')
    def _check_code_sheets(self):
        for l in self:
            for f, sheet in (('customer_code_id', 'CUSTOMER'), ('trade_code_id', 'FOR PURCHASE'), ('pl_code_id', 'PROFIT & LOSS')):
                c = l[f]
                if c and c.source_sheet_key != sheet:
                    raise UserError(_("%(code)s %(name)s is a %(s)s code, not a %(w)s code.", code=c.legacy_code,
                                      name=c.original_name, s=c.source_sheet_key, w=sheet))

    @api.constrains('weight_kg', 'mtl')
    def _check_weight(self):
        for l in self:
            if l.weight_kg and Decimal(str(l.mtl)).quantize(fe.TON) != fe.tons_from_kg(Decimal(str(l.weight_kg))):
                raise UserError(_("%(kg)s kg is %(t)s MTL, not %(m)s.", kg=l.weight_kg, t=fe.tons_from_kg(Decimal(str(l.weight_kg))), m=l.mtl))

    @api.depends('customer_code_id', 'customer_id', 'da_id.printed_customer', 'code_override_reason')
    def _compute_code_issue(self):
        for l in self:
            l.code_issue = l._code_problem() or False

    def _code_problem(self, hard_only=False):
        """Plain-words reason the customer code cannot be trusted for this coil, or ''."""
        self.ensure_one()
        return self._code_problem_for(self.customer_code_id, self.customer_id, self.da_id.printed_customer,
                                      self.code_override_reason, hard_only)

    @api.model
    def _code_problem_for(self, c, customer, printed, override=False, hard_only=False):
        """The same check for values not saved yet (the desk warns while the coil is being typed)."""
        if not c:
            return _("Choose the customer's code from the code list.")
        if c.verification_status != 'approved' or c.linked_model != 'res.partner' or not c.linked_res_id:
            return _("Code %(c)s (%(n)s) is not yet verified against a customer. Leave it for the accountant to verify; do not guess.",
                     c=c.legacy_code, n=c.original_name)
        partner = self.env['res.partner'].browse(c.linked_res_id)
        if customer and partner != customer:
            return _("Code %(c)s belongs to %(p)s, not to %(x)s.", c=c.legacy_code, p=partner.display_name, x=customer.display_name)
        if hard_only:
            return ''
        if printed and not override and not (name_tokens(printed) & (name_tokens(c.original_name) | name_tokens(partner.name))):
            return _("The DA prints '%(p)s' but code %(c)s is '%(n)s'. Check the paper; an approver must record why before it can be used.",
                     p=printed, c=c.legacy_code, n=c.original_name)
        return ''

    def action_authorise_code(self, reason):
        """The printed customer differs from the code's name but the relationship is real (a dealer account, a group): recorded, never assumed."""
        if not self.env.user.has_group('ei_contract_da.group_ei_da_override'):
            raise AccessError(_("Only someone allowed to authorise exceptions can accept a different printed name."))
        if not (reason or '').strip():
            raise UserError(_("Write why this code is right for the printed customer."))
        for l in self:
            hard = l._code_problem(hard_only=True)
            if hard:
                raise UserError(hard)
            l.with_context(ei_system=True).write({'code_override_reason': reason.strip(), 'code_override_by': self.env.user.id})
            l.da_id.message_post(body=_("Customer code %(c)s accepted for printed name '%(p)s' by %(u)s: %(r)s",
                                        c=l.customer_code_id.legacy_code, p=l.da_id.printed_customer, u=self.env.user.name, r=reason.strip()))

    # ---------------------------------------------------------------- calculation
    def _formula_for(self, cl, lab=False):
        f = cl.formula_id
        if not f:
            raise fe.FeedingError(_("Contract line '%s' has no rate formula. Use the direct method, or ask for the contract to be corrected.",
                                    cl.product_id.display_name))
        if f.state != 'approved' and not lab:
            raise fe.FeedingError(_("Formula %(c)s v%(v)s is not approved by the accountant; real entries cannot use it.", c=f.code, v=f.version))
        return f

    @api.model
    def _feed(self, cl, vals):
        """Work out one coil from what the operator typed. The server always recomputes: numbers from the screen are never trusted."""
        method = vals.get('feeding_method')
        basis = fe.METHODS.get(method, (None, None))[1]
        kw = {}
        if basis in ('dealer_net', 'with_cn'):
            f = self._formula_for(cl)
            params = {k: v for k, v in cl._params().items() if k != 'cn_amount'}
            kw = dict(steps=f._steps(), rounding_mode=f.rounding_mode, basic_rate=vals.get('basic_rate') or cl.basic_rate, params=params,
                      sale_offset=vals.get('sale_offset') or 0, sale_rate=vals.get('sale_rate') if vals.get('sale_typed') else None,
                      cn_amount=vals.get('cn_amount'))
            formula = {'code': f.code, 'version': f.version, 'id': f.id, 'rounding': f.rounding_mode, 'params': {k: str(v) for k, v in params.items()}}
        else:
            kw = dict(purchase_rate=vals.get('purchase_rate'), sale_rate=vals.get('sale_rate'))
            formula = None
        mtl = fe.tons_from_kg(vals['weight_kg']) if vals.get('weight_kg') else Decimal(str(vals.get('mtl') or 0))
        r = fe.feed(method, mtl, **kw)
        r['formula'] = formula
        return r

    def _approval_problems(self):
        self.ensure_one()
        out = []
        if self.feeding_method == 'purchase_without_commission':
            return [_("'Purchase without commission' is waiting for the client's example and the accountant's rule.")]
        try:
            r = self._feed(self.contract_line_id, self._feed_vals())
        except fe.FeedingError as e:
            return [str(e)]
        if (fe.money(r['purchase_rate']), fe.money(r['sale_rate'])) != (fe.money(self.purchase_rate), fe.money(self.sale_rate)):
            out.append(_("its rates were changed by hand after the calculation; open it in the feeding desk and save it again."))
        if r['spread_per_mtl'] < 0 and not (self.loss_reason or '').strip():
            out.append(_("it is sold below cost (%s per MTL); write why.", r['spread_per_mtl']))
        if self.feeding_method == 'purchase_with_cn' and not (self.cn_text or '').strip():
            out.append(_("write the credit note text for this coil."))
        if (fe.money(self.basic_rate or 0) != fe.money(self.contract_line_id.basic_rate or 0)) and r['formula'] and not (self.rate_note or '').strip():
            out.append(_("its basic rate differs from the contract (%s); explain in the rate note.", self.contract_line_id.basic_rate))
        code = self._code_problem()
        if code:
            out.append(code)
        return out

    def _feed_vals(self):
        return {'feeding_method': self.feeding_method, 'basic_rate': self.basic_rate, 'sale_offset': self.sale_offset,
                'sale_typed': self.sale_typed, 'sale_rate': self.sale_rate, 'purchase_rate': self.purchase_rate,
                'cn_amount': self.cn_amount, 'weight_kg': self.weight_kg, 'mtl': self.mtl}

    def _needs_rate_note(self):
        """A coil worked out in the feeding desk proves its own rates (checked in _approval_problems)."""
        if self.feeding_method:
            return False
        return super()._needs_rate_note()

    def write(self, vals):
        locked = {'coil_no', 'weight_kg', 'feeding_method', 'basic_rate', 'sale_offset', 'cn_amount', 'cn_text', 'customer_code_id',
                  'trade_code_id', 'pl_code_id', 'loss_reason', 'feeding_calc', 'sale_typed'}
        if locked & set(vals) and any(r.da_id.state != 'draft' for r in self) and not self.env.context.get('ei_system'):
            raise UserError(_("The DA is not a draft; amend it instead."))
        if {'customer_code_id', 'customer_id'} & set(vals) and not self.env.context.get('ei_system'):
            vals = dict(vals, code_override_reason=False, code_override_by=False)
        return super().write(vals)


class EiReasonWizard(models.TransientModel):
    _inherit = 'ei.reason.wizard'

    def _allowed(self):
        return super()._allowed() | {('ei.da.line', 'action_authorise_code')}
