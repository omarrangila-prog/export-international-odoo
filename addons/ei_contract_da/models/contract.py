import json
from decimal import Decimal

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from markupsafe import Markup, escape

from . import formula_engine as fe


class EiContract(models.Model):
    _name = 'ei.contract'
    _description = 'Parent-company contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(readonly=True, copy=False, default='New')
    parent_partner_id = fields.Many2one('res.partner', string='Parent company (supplier)', required=True, tracking=True)
    contract_ref = fields.Char('Parent contract reference', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Owner company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda s: s.env.company.currency_id)
    date = fields.Date(required=True, default=fields.Date.context_today)
    valid_from = fields.Date(tracking=True)
    valid_to = fields.Date(tracking=True)
    contract_type = fields.Selection([
        ('local_direct', 'Local purchase - direct buy/sell rates'),
        ('commission', 'Commission contract'),
        ('end_coils', 'End Coils - direct pricing'),
        ('other', 'Other'),
    ], required=True, default='local_direct', tracking=True,
        help="A label for reporting. It never selects a formula: each line carries its own approved formula.")
    state = fields.Selection([
        ('draft', 'Draft'), ('reviewed', 'Reviewed'), ('approved', 'Approved'), ('active', 'Active'),
        ('fulfilled', 'Fulfilled'), ('closed', 'Closed'), ('cancelled', 'Cancelled'), ('amended', 'Superseded by revision'),
    ], default='draft', readonly=True, tracking=True, index=True)
    revision = fields.Integer(default=0, readonly=True)
    previous_id = fields.Many2one('ei.contract', readonly=True, copy=False)
    maker_id = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    reviewed_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    cancel_reason = fields.Char(readonly=True, copy=False)
    line_ids = fields.One2many('ei.contract.line', 'contract_id', copy=True)
    da_ids = fields.One2many('ei.da', 'contract_id')
    notes = fields.Text()
    attachment_count = fields.Integer('Papers attached', compute='_compute_attachment_count')
    usage = fields.Selection([('unused', 'Nothing promised yet'), ('partial', 'Partially used'), ('full', 'Fully promised on DAs')],
                             compute='_compute_usage', help="How much of the ordered quantity is promised on approved delivery advices.")

    _uniq_ref = models.Constraint('unique(company_id, parent_partner_id, contract_ref, revision)',
                                  'This parent contract reference/revision already exists.')

    @api.depends('line_ids.allocated_mtl', 'line_ids.ordered_mtl')
    def _compute_usage(self):
        for r in self:
            ordered, used = sum(r.line_ids.mapped('ordered_mtl')), sum(r.line_ids.mapped('allocated_mtl'))
            r.usage = 'unused' if used <= 0 else 'full' if used >= ordered - 1e-9 else 'partial'

    def _compute_attachment_count(self):
        data = dict(self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.attachment_count = data.get(r.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'New') == 'New':
                v['name'] = self.env['ir.sequence'].next_by_code('ei.contract') or 'New'
        return super().create(vals_list)

    @api.constrains('valid_from', 'valid_to')
    def _check_dates(self):
        for r in self:
            if r.valid_from and r.valid_to and r.valid_to < r.valid_from:
                raise UserError(_("Valid-to is before valid-from."))

    def write(self, vals):
        if self.env.context.get('ei_system'):
            return super().write(vals)
        frozen = {'parent_partner_id', 'contract_ref', 'company_id', 'currency_id', 'date', 'valid_from', 'valid_to', 'contract_type'}
        if frozen & set(vals) and any(r.state != 'draft' for r in self):
            raise UserError(_("Only a draft contract can be edited; create a revision instead."))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_("Only draft contracts can be deleted; cancel them instead."))
        return super().unlink()

    def _sys(self, vals):
        return self.with_context(ei_system=True).write(vals)

    # -------------------------------------------------------------- workflow
    def action_review(self):
        for r in self:
            if r.state != 'draft':
                raise UserError(_("Only a draft can be sent for review."))
            if not r.line_ids:
                raise UserError(_("Add at least one contract line."))
            if not r.attachment_count:
                raise UserError(_("Attach the parent company's contract document first."))
            r.line_ids._check_ready()
            r._sys({'state': 'reviewed', 'reviewed_by': self.env.user.id})

    def action_approve(self):
        if not self.env.user.has_group('ei_contract_da.group_ei_contract_approver'):
            raise AccessError(_("Only a contract approver can approve."))
        for r in self:
            if r.state != 'reviewed':
                raise UserError(_("Only a reviewed contract can be approved."))
            if r.create_uid == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: you cannot approve a contract you created."))
            r.line_ids._check_ready()
            r.line_ids._take_snapshot()
            r._sys({'state': 'approved', 'approved_by': self.env.user.id, 'approved_at': fields.Datetime.now()})
            if r.previous_id:
                r.previous_id._sys({'state': 'amended'})
                r.previous_id.da_ids.filtered(lambda d: d.state in ('draft', 'under_review'))._cancel_for_revision(r)

    def action_activate(self):
        for r in self:
            if r.state != 'approved':
                raise UserError(_("Only an approved contract can be activated."))
            r._sys({'state': 'active'})

    def action_close(self):
        for r in self:
            if r.state not in ('active', 'fulfilled'):
                raise UserError(_("Only an active or fulfilled contract can be closed."))
            r._sys({'state': 'closed'})

    def action_cancel(self, reason=None):
        for r in self:
            if r.state not in ('draft', 'reviewed', 'approved', 'active'):
                raise UserError(_("A %s contract cannot be cancelled.", r.state))
            if r.state in ('approved', 'active') and not self.env.user.has_group('ei_contract_da.group_ei_contract_approver'):
                raise AccessError(_("Only an approver can cancel an approved contract."))
            if not (reason or '').strip():
                raise UserError(_("A cancellation reason is required."))
            if r.da_ids.filtered(lambda d: d.state in ('approved', 'fulfilled')):
                raise UserError(_("Approved delivery advices exist; cancel or close them first."))
            r._sys({'state': 'cancelled', 'cancel_reason': reason})

    def action_revise(self):
        self.ensure_one()
        if self.state not in ('approved', 'active'):
            raise UserError(_("Only an approved or active contract can be revised."))
        new = self.copy({'revision': self.revision + 1, 'previous_id': self.id, 'state': 'draft', 'name': 'New',
                         'maker_id': self.env.user.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id, 'views': [(False, 'form')]}

    def _refresh_fulfilment(self):
        for r in self.filtered(lambda c: c.state in ('active', 'fulfilled')):
            lines = r.line_ids
            done = bool(lines) and all(l.lifted_mtl >= l.ordered_mtl > 0 for l in lines)
            if done and r.state == 'active':
                r._sys({'state': 'fulfilled'})
            elif not done and r.state == 'fulfilled':
                r._sys({'state': 'active'})


class EiContractLine(models.Model):
    _name = 'ei.contract.line'
    _description = 'Contract line'
    _order = 'contract_id, sequence, id'

    contract_id = fields.Many2one('ei.contract', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    state = fields.Selection(related='contract_id.state', store=True)
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='contract_id.currency_id')
    product_id = fields.Many2one('product.product', string='Material', required=True)
    grade = fields.Char('Grade / spec')
    lot = fields.Char('Coil / batch / lot')
    uom_id = fields.Many2one('uom.uom', string='Unit', required=True,
                             default=lambda s: s.env.ref('uom.product_uom_ton', raise_if_not_found=False),
                             help="Quantities labelled MTL are metric tons unless the client confirms otherwise.")
    ordered_mtl = fields.Float('Ordered (MTL)', digits=(16, 3), required=True)
    purchase_rate = fields.Monetary('Purchase rate / MTL', currency_field='currency_id')
    sale_rate = fields.Monetary('Sale rate / MTL', currency_field='currency_id')
    basic_rate = fields.Monetary('Basic rate / MTL', currency_field='currency_id',
                                 help="Input of the line's formula (e.g. rate before a stated deduction).")
    shipping_charge = fields.Monetary('Shipping / handling / MTL', currency_field='currency_id')
    cost_class = fields.Selection([('direct', 'Direct buy/sell'), ('commission', 'Commission'), ('end_coils', 'End Coils'),
                                   ('other', 'Other')], string='Cost classification')
    target_customer_id = fields.Many2one('res.partner', string='Target customer')
    formula_id = fields.Many2one('ei.formula.definition', domain="[('state', '=', 'approved')]", string='Approved formula')
    cn_text = fields.Char('Credit note (CN) text', copy=True,
                          help="The CN wording for THIS coil, as written on the parent's paper. A CN is entered per coil, never once for a whole invoice.")
    formula_version = fields.Integer(related='formula_id.version', string='Formula version')
    param_ids = fields.One2many('ei.contract.line.param', 'line_id', copy=True)
    spread_per_mtl = fields.Monetary(compute='_compute_spread', currency_field='currency_id',
                                     help="Sale rate less purchase rate. Before commission, costs and taxes.")
    expected_gross_spread = fields.Monetary(compute='_compute_spread', currency_field='currency_id',
                                            help="Ordered MTL x spread. NOT audited net profit.")
    da_line_ids = fields.One2many('ei.da.line', 'contract_line_id')
    allocated_mtl = fields.Float(compute='_compute_allocation', store=True, digits=(16, 3))
    remaining_mtl = fields.Float('Unallocated (MTL)', compute='_compute_allocation', store=True, digits=(16, 3))
    lifted_mtl = fields.Float('Verified lifted (MTL)', compute='_compute_lifted', digits=(16, 3))
    snapshot = fields.Json(readonly=True, copy=False)
    calc_html = fields.Html(compute='_compute_calc_html', sanitize=False)

    @api.depends('purchase_rate', 'sale_rate', 'ordered_mtl')
    def _compute_spread(self):
        for l in self:
            l.spread_per_mtl = l.sale_rate - l.purchase_rate
            l.expected_gross_spread = l.currency_id.round(Decimal_to_float(
                fe.gross_spread(l.ordered_mtl, l.sale_rate, l.purchase_rate))) if l.currency_id else 0.0

    @api.depends('da_line_ids.mtl', 'da_line_ids.state', 'ordered_mtl')
    def _compute_allocation(self):
        for l in self:
            used = sum(d.mtl for d in l.da_line_ids if d.state in ('approved', 'fulfilled', 'closed'))
            l.allocated_mtl = used
            l.remaining_mtl = l.ordered_mtl - used

    @api.depends()
    def _compute_lifted(self):
        for l in self:
            l.lifted_mtl = 0.0  # overridden by ei_material_lifting with verified lifting records

    @api.constrains('ordered_mtl')
    def _check_qty(self):
        for l in self:
            if l.ordered_mtl <= 0:
                raise UserError(_("Ordered MTL must be positive."))

    def _params(self):
        self.ensure_one()
        return {p.key: p.value for p in self.param_ids}

    def _check_ready(self):
        for l in self:
            if l.formula_id:
                if l.formula_id.state != 'approved':
                    raise UserError(_("Formula %s is not approved.", l.formula_id.display_name))
                missing = l.formula_id._param_names() - set(l._params())
                if missing:
                    raise UserError(_("Line '%(l)s' lacks formula parameter(s): %(m)s", l=l.product_id.display_name, m=', '.join(sorted(missing))))
                if not l.basic_rate:
                    raise UserError(_("Line '%s' uses a formula and needs a basic rate.", l.product_id.display_name))
                entered = [s.param for s in l.formula_id.step_ids if s.kind == 'input_amount' and Decimal(l._params()[s.param] or 0)]
                if entered and not (l.cn_text or '').strip():
                    raise UserError(_("Line '%(l)s' has a credit-note amount (%(p)s); write the CN text for this coil too.",
                                      l=l.product_id.display_name, p=', '.join(entered)))
                try:
                    l.formula_id.compute(l.basic_rate, l.ordered_mtl, l._params(), l.currency_id.decimal_places)
                except (fe.FormulaError, ValueError) as e:
                    raise UserError(_("Formula cannot be evaluated on line '%(l)s': %(e)s", l=l.product_id.display_name, e=e))

    def _live_calc(self):
        self.ensure_one()
        rows, values = self.formula_id.compute(self.basic_rate, self.ordered_mtl, self._params(), self.currency_id.decimal_places)
        return {'formula': self.formula_id.code, 'version': self.formula_id.version, 'formula_id': self.formula_id.id,
                'rounding': self.formula_id.rounding_mode,
                'inputs': {'basic_rate': str(self.basic_rate), 'quantity': str(self.ordered_mtl), 'params': {k: str(v) for k, v in self._params().items()}},
                'rows': [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in r.items()} for r in rows],
                'values': {k: str(v) for k, v in values.items()}}

    def _take_snapshot(self):
        for l in self.filtered('formula_id'):
            l.with_context(ei_system=True).snapshot = l._live_calc()

    @api.depends('snapshot', 'formula_id', 'basic_rate', 'ordered_mtl', 'param_ids.value', 'param_ids.key', 'state')
    def _compute_calc_html(self):
        for l in self:
            if not l.formula_id and not l.snapshot:
                l.calc_html = False
                continue
            try:
                data = l.snapshot or l._live_calc()
            except (fe.FormulaError, ValueError, UserError) as e:
                l.calc_html = Markup('<p class="text-danger">%s</p>') % escape(str(e))
                continue
            head = Markup('<p><b>%s v%s</b> (%s) - %s. Inputs: basic rate %s, quantity %s MTL, parameters %s.</p>') % (
                data['formula'], data['version'], data['rounding'], _('frozen at approval') if l.snapshot else _('live preview, not yet frozen'),
                data['inputs']['basic_rate'], data['inputs']['quantity'], escape(json.dumps(data['inputs']['params'])))
            body = Markup('').join(
                Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td class="text-end">%s</td><td class="text-end">%s</td><td class="text-end">%s</td></tr>') % (
                    r['key'], r['kind'], r['base_ref'], r['base'], r['result'], r['total']) for r in data['rows'])
            l.calc_html = head + Markup('<table class="table table-sm"><thead><tr><th>Result</th><th>Rule</th><th>On</th><th>Base/MTL</th><th>Result/MTL</th><th>Total</th></tr></thead><tbody>') + body + Markup('</tbody></table>')

    def write(self, vals):
        if not self.env.context.get('ei_system'):
            if any(r.contract_id.state != 'draft' for r in self):
                raise UserError(_("The contract is not a draft; its lines are locked. Create a revision."))
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('ei_system'):
            for v in vals_list:
                c = self.env['ei.contract'].browse(v.get('contract_id'))
                if c and c.state != 'draft':
                    raise UserError(_("The contract is not a draft; its lines are locked. Create a revision."))
        return super().create(vals_list)

    def unlink(self):
        if any(r.contract_id.state != 'draft' for r in self):
            raise UserError(_("The contract is not a draft; its lines are locked."))
        return super().unlink()


def Decimal_to_float(d):
    return float(d)


class EiContractLineParam(models.Model):
    _name = 'ei.contract.line.param'
    _description = 'Formula parameter value of a contract line'

    line_id = fields.Many2one('ei.contract.line', required=True, ondelete='cascade', index=True)
    key = fields.Char(required=True)
    value = fields.Char(required=True, help="Exact decimal, e.g. 1.32")

    _uniq = models.Constraint('unique(line_id, key)', 'A parameter can be given once per line.')

    @api.constrains('value')
    def _check_value(self):
        for p in self:
            try:
                Decimal(p.value)
            except Exception:
                raise UserError(_("Parameter %(k)s: %(v)r is not a number.", k=p.key, v=p.value))

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            l = self.env['ei.contract.line'].browse(v.get('line_id'))
            if l and l.contract_id.state != 'draft':
                raise UserError(_("The contract is not a draft; parameters are locked."))
        return super().create(vals_list)

    def write(self, vals):
        if any(r.line_id.contract_id.state != 'draft' for r in self):
            raise UserError(_("The contract is not a draft; parameters are locked."))
        return super().write(vals)

    def unlink(self):
        if any(r.line_id.contract_id.state != 'draft' for r in self):
            raise UserError(_("The contract is not a draft; parameters are locked."))
        return super().unlink()
