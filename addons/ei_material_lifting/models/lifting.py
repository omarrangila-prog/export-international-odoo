from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

OWNERSHIP = [('owned', 'Owned stock'), ('consignment', 'Supplier-owned consignment'),
             ('direct_dispatch', 'Direct supplier-to-customer dispatch')]


class EiLifting(models.Model):
    _name = 'ei.lifting'
    _description = 'Material lifting (gate pass / weighbridge)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(readonly=True, copy=False, default='New')
    da_line_id = fields.Many2one('ei.da.line', required=True, index=True, tracking=True,
                                 domain="[('state', 'in', ('approved', 'fulfilled'))]")
    da_id = fields.Many2one(related='da_line_id.da_id', store=True)
    contract_line_id = fields.Many2one(related='da_line_id.contract_line_id', store=True)
    company_id = fields.Many2one(related='da_line_id.company_id', store=True, index=True)
    product_id = fields.Many2one(related='da_line_id.product_id', store=True)
    order_line_id = fields.Many2one('ei.daily.order.line', domain="[('da_line_id', '=', da_line_id), ('state', '=', 'approved')]")
    customer_id = fields.Many2one('res.partner', compute='_compute_customer', store=True, readonly=False)
    date = fields.Date('Dispatch date', required=True, default=fields.Date.context_today, tracking=True)
    vehicle_no = fields.Char('Truck / vehicle', required=True)
    gate_pass_no = fields.Char(required=True, tracking=True)
    weighbridge_no = fields.Char('Weighbridge ticket')
    lot = fields.Char('Batch / coil')
    claimed_mtl = fields.Float('Gate-pass quantity (MTL)', digits=(16, 3))
    gross_kg = fields.Float(digits=(16, 1))
    tare_kg = fields.Float(digits=(16, 1))
    net_kg = fields.Float(compute='_compute_weights', store=True, digits=(16, 1))
    weighed_mtl = fields.Float('Weighed quantity (MTL)', compute='_compute_weights', store=True, digits=(16, 3))
    verified_mtl = fields.Float('Verified lifted (MTL)', readonly=True, digits=(16, 3), tracking=True)
    discrepancy_mtl = fields.Float(compute='_compute_weights', store=True, digits=(16, 3))
    discrepancy_note = fields.Text()
    state = fields.Selection([('draft', 'Draft'), ('verified', 'Verified'), ('reversed', 'Reversed'),
                              ('cancelled', 'Cancelled')], default='draft', readonly=True, tracking=True, index=True)
    maker_id = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    verified_by = fields.Many2one('res.users', readonly=True)
    verified_at = fields.Datetime(readonly=True)
    reverse_reason = fields.Char(readonly=True)
    received_on = fields.Date('Receipt confirmed by customer on')
    received_note = fields.Char()
    ownership = fields.Selection(related='contract_line_id.stock_ownership', string='Stock ownership')
    stock_treatment = fields.Char(compute='_compute_stock_treatment')
    attachment_count = fields.Integer('Papers attached', compute='_compute_attachment_count')

    _gate = models.Constraint('unique(company_id, gate_pass_no)', 'This gate pass number was already recorded.')

    @api.depends('da_line_id')
    def _compute_customer(self):
        for r in self:
            if not r.customer_id:
                r.customer_id = r.da_line_id.customer_id

    @api.depends('gross_kg', 'tare_kg', 'claimed_mtl', 'da_line_id')
    def _compute_weights(self):
        kg = self.env.ref('uom.product_uom_kgm', raise_if_not_found=False)
        for r in self:
            r.net_kg = r.gross_kg - r.tare_kg if r.gross_kg else 0.0
            unit = r.da_line_id.contract_line_id.uom_id
            r.weighed_mtl = 0.0
            if r.net_kg and kg and unit:
                try:
                    r.weighed_mtl = kg._compute_quantity(r.net_kg, unit, round=False)
                except UserError:
                    r.weighed_mtl = 0.0  # reported at verification
            r.discrepancy_mtl = (r.weighed_mtl - r.claimed_mtl) if (r.weighed_mtl and r.claimed_mtl) else 0.0

    @api.depends('ownership')
    def _compute_stock_treatment(self):
        for r in self:
            r.stock_treatment = {
                'owned': _("Owned stock: inventory valuation treatment awaits the accountant's decision - no stock move is created."),
                'consignment': _("Supplier-owned: no inventory is recognised."),
                'direct_dispatch': _("Direct dispatch: no inventory is recognised."),
            }.get(r.ownership, _("Ownership not classified yet."))

    def _compute_attachment_count(self):
        data = dict(self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.attachment_count = data.get(r.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'New') == 'New':
                v['name'] = self.env['ir.sequence'].next_by_code('ei.lifting') or 'New'
            if not v.get('order_line_id') and v.get('da_line_id'):
                ols = self.env['ei.daily.order.line'].search([('da_line_id', '=', v['da_line_id']), ('state', '=', 'approved')])
                if len(ols) == 1:
                    v['order_line_id'] = ols.id
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('ei_system') and any(r.state != 'draft' for r in self):
            allowed = {'received_on', 'received_note', 'message_follower_ids'}
            if set(vals) - allowed:
                raise UserError(_("A verified lifting is a record; reverse it and enter a new one."))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_("Only draft liftings can be deleted."))
        return super().unlink()

    @api.constrains('claimed_mtl', 'gross_kg', 'tare_kg')
    def _check_numbers(self):
        for r in self:
            if r.claimed_mtl < 0 or r.gross_kg < 0 or r.tare_kg < 0:
                raise UserError(_("Quantities cannot be negative."))
            if r.gross_kg and r.tare_kg >= r.gross_kg:
                raise UserError(_("Tare weight must be below gross weight."))

    def _tolerance(self):
        return self.env['ir.config_parameter'].sudo().get_float('ei_material_lifting.tolerance_mtl', 0.0)

    # -------------------------------------------------------------- workflow
    def action_verify(self):
        if not self.env.user.has_group('ei_material_lifting.group_ei_lifting_reviewer'):
            raise AccessError(_("Only a lifting reviewer can verify."))
        for r in self:
            if r.state != 'draft':
                raise UserError(_("Only a draft lifting can be verified."))
            if r.maker_id == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: you cannot verify a lifting you entered."))
            if not r.attachment_count:
                raise UserError(_("Attach the gate pass / weighbridge / dispatch proof first."))
            if not r.contract_line_id.stock_ownership:
                raise UserError(_("Classify the stock ownership of this contract line first (owned / consignment / direct dispatch)."))
            if r.net_kg and not r.weighed_mtl:
                raise UserError(_("Cannot convert kg to the contract unit '%s'; fix the unit configuration.", r.contract_line_id.uom_id.name))
            if not (r.weighed_mtl or r.claimed_mtl):
                raise UserError(_("Enter the gate-pass quantity or the weighbridge weights."))
            if r.weighed_mtl and not r.weighbridge_no:
                raise UserError(_("Weights were entered without a weighbridge ticket number."))
            qty = r.weighed_mtl or r.claimed_mtl
            if r.weighed_mtl and r.claimed_mtl and abs(r.discrepancy_mtl) > self._tolerance() + 1e-9 \
                    and not (r.discrepancy_note or '').strip():
                raise UserError(_("Weighbridge %(w)s MTL differs from the gate pass %(c)s MTL; the discrepancy needs an approved note.",
                                  w=r.weighed_mtl, c=r.claimed_mtl))
            dl = r.da_line_id
            if dl.state not in ('approved', 'fulfilled'):
                raise UserError(_("The DA is %s.", dl.state))
            already = sum(x.verified_mtl for x in dl.lifting_ids if x.state == 'verified' and x != r)
            if already + qty > dl.mtl + 1e-9:
                raise UserError(_("Over-lifting: %(q)s MTL would bring the DA line to %(t)s MTL, above the approved %(m)s MTL.",
                                  q=qty, t=already + qty, m=dl.mtl))
            r.with_context(ei_system=True).write({'state': 'verified', 'verified_mtl': qty, 'verified_by': self.env.user.id,
                                                   'verified_at': fields.Datetime.now()})
            r.da_id._update_fulfilment()

    def action_reverse(self, reason=None):
        if not self.env.user.has_group('ei_material_lifting.group_ei_lifting_reviewer'):
            raise AccessError(_("Only a lifting reviewer can reverse."))
        for r in self:
            if r.state != 'verified':
                raise UserError(_("Only a verified lifting can be reversed."))
            if not (reason or '').strip():
                raise UserError(_("A reason is required."))
            r.with_context(ei_system=True).write({'state': 'reversed', 'reverse_reason': reason})
            r.da_id._update_fulfilment()

    def action_cancel(self, reason=None):
        for r in self:
            if r.state != 'draft':
                raise UserError(_("Only a draft can be cancelled; reverse a verified lifting instead."))
            r.with_context(ei_system=True).write({'state': 'cancelled'})


class EiContractLine(models.Model):
    _inherit = 'ei.contract.line'

    stock_ownership = fields.Selection(OWNERSHIP, string='Stock ownership', copy=True,
                                       help="Determines the legally correct treatment. Never inferred from a DA or an invoice.")

    @api.depends('da_line_ids.lifted_mtl', 'da_line_ids.state')
    def _compute_lifted(self):
        for l in self:
            l.lifted_mtl = sum(d.lifted_mtl for d in l.da_line_ids if d.state in ('approved', 'fulfilled', 'closed'))

    def action_set_ownership(self, value, reason=None):
        """Classification can be set once after approval, by an approver, with a logged reason."""
        if not self.env.user.has_group('ei_contract_da.group_ei_contract_approver'):
            raise AccessError(_("Only a contract approver can classify stock ownership."))
        if value not in dict(OWNERSHIP):
            raise UserError(_("Unknown ownership type."))
        for l in self:
            if l.stock_ownership and l.stock_ownership != value and any(
                    x.state == 'verified' for d in l.da_line_ids for x in d.lifting_ids):
                raise UserError(_("Liftings were already verified under '%s'; it cannot be changed.", l.stock_ownership))
            if not (reason or '').strip():
                raise UserError(_("A reason is required."))
            l.with_context(ei_system=True).stock_ownership = value
            l.contract_id.message_post(body=_("Stock ownership of %(p)s set to %(v)s by %(u)s: %(r)s",
                                              p=l.product_id.display_name, v=value, u=self.env.user.name, r=reason))


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    lifting_ids = fields.One2many('ei.lifting', 'da_line_id')

    @api.depends('lifting_ids.verified_mtl', 'lifting_ids.state', 'mtl')
    def _compute_lifted(self):
        for l in self:
            l.lifted_mtl = sum(x.verified_mtl for x in l.lifting_ids if x.state == 'verified')
            l.remaining_to_lift = l.mtl - l.lifted_mtl


class EiDailyOrderLine(models.Model):
    _inherit = 'ei.daily.order.line'

    lifting_ids = fields.One2many('ei.lifting', 'order_line_id')

    @api.depends('requested_mtl', 'lifting_ids.verified_mtl', 'lifting_ids.state')
    def _compute_lifted(self):
        for l in self:
            l.lifted_mtl = sum(x.verified_mtl for x in l.lifting_ids if x.state == 'verified')
            l.remaining_mtl = l.requested_mtl - l.lifted_mtl


class EiDa(models.Model):
    _inherit = 'ei.da'

    def action_approve(self):
        for d in self.filtered('previous_id'):
            for nl in d.line_ids:
                prev = d.previous_id.line_ids.filtered(lambda p: p.contract_line_id == nl.contract_line_id and p.customer_id == nl.customer_id)[:1]
                if prev and nl.mtl + 1e-9 < prev.lifted_mtl:
                    raise UserError(_("The amendment cuts a line to %(n)s MTL but %(l)s MTL are already lifted.",
                                      n=nl.mtl, l=prev.lifted_mtl))
        res = super().action_approve()
        for d in self.filtered('previous_id'):
            for nl in d.line_ids:
                prev = d.previous_id.line_ids.filtered(lambda p: p.contract_line_id == nl.contract_line_id and p.customer_id == nl.customer_id)[:1]
                if prev:
                    prev.lifting_ids.with_context(ei_system=True).write({'da_line_id': nl.id})
        return res


class EiDaTotals(models.Model):
    _inherit = 'ei.da'

    @api.depends('line_ids.mtl', 'line_ids.state', 'line_ids.lifted_mtl')
    def _compute_lifted_totals(self):
        return super()._compute_lifted_totals()
