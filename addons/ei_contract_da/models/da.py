from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiDa(models.Model):
    _name = 'ei.da'
    _description = 'Delivery Advice (DA)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char('DA number (as issued by parent)', required=True, tracking=True)
    amendment_no = fields.Integer(default=0, readonly=True)
    parent_partner_id = fields.Many2one('res.partner', string='Parent company', required=True, tracking=True)
    contract_id = fields.Many2one('ei.contract', required=True, tracking=True, index=True,
                                  domain="[('state', 'in', ('active',)), ('parent_partner_id', '=', parent_partner_id)]")
    company_id = fields.Many2one(related='contract_id.company_id', store=True, index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    state = fields.Selection([
        ('draft', 'Draft'), ('under_review', 'Under review'), ('approved', 'Approved'),
        ('fulfilled', 'Fulfilled'), ('closed', 'Closed'), ('cancelled', 'Cancelled'), ('amended', 'Superseded by amendment'),
    ], default='draft', readonly=True, tracking=True, index=True)
    previous_id = fields.Many2one('ei.da', readonly=True, copy=False)
    maker_id = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    cancel_reason = fields.Char(readonly=True, copy=False)
    line_ids = fields.One2many('ei.da.line', 'da_id', copy=True)
    total_mtl = fields.Float(compute='_compute_total_mtl', store=True, digits=(16, 3))
    lifted_mtl = fields.Float(compute='_compute_lifted_totals', digits=(16, 3))
    remaining_to_lift = fields.Float(compute='_compute_lifted_totals', digits=(16, 3))
    attachment_count = fields.Integer('Papers attached', compute='_compute_attachment_count')

    _uniq = models.Constraint('unique(company_id, parent_partner_id, name, amendment_no)',
                              'This DA number/amendment already exists for the parent company.')

    def _compute_attachment_count(self):
        data = dict(self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.attachment_count = data.get(r.id, 0)

    @api.depends('line_ids.mtl', 'line_ids.state')
    def _compute_total_mtl(self):
        for d in self:
            d.total_mtl = sum(d.line_ids.mapped('mtl'))

    @api.depends('line_ids.mtl', 'line_ids.state')
    def _compute_lifted_totals(self):
        for d in self:
            d.lifted_mtl = sum(d.line_ids.mapped('lifted_mtl'))
            d.remaining_to_lift = sum(d.line_ids.mapped('mtl')) - d.lifted_mtl

    def write(self, vals):
        if not self.env.context.get('ei_system') and {'name', 'parent_partner_id', 'contract_id', 'date'} & set(vals) \
                and any(r.state != 'draft' for r in self):
            raise UserError(_("Only a draft DA can be edited; amend it instead."))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_("Only draft DAs can be deleted."))
        return super().unlink()

    def _sys(self, vals):
        return self.with_context(ei_system=True).write(vals)

    @api.constrains('parent_partner_id', 'contract_id')
    def _check_parent(self):
        for d in self:
            if d.contract_id.parent_partner_id != d.parent_partner_id:
                raise UserError(_("The DA's parent company differs from the contract's."))

    # -------------------------------------------------------------- workflow
    def action_review(self):
        for d in self:
            if d.state != 'draft':
                raise UserError(_("Only a draft DA can be sent for review."))
            if not d.line_ids:
                raise UserError(_("Add at least one DA line."))
            if not d.attachment_count:
                raise UserError(_("Attach the DA document received from the parent company."))
            d._sys({'state': 'under_review'})

    def _available(self, cline):
        """MTL of the contract line still free for this DA (excludes this DA and the one it amends)."""
        self.ensure_one()
        skip = self | self.previous_id
        used = sum(l.mtl for l in cline.da_line_ids if l.da_id not in skip and l.state in ('approved', 'fulfilled', 'closed'))
        return cline.ordered_mtl - used

    def action_approve(self):
        if not self.env.user.has_group('ei_contract_da.group_ei_contract_approver'):
            raise AccessError(_("Only a contract approver can approve a DA."))
        for d in self:
            if d.state != 'under_review':
                raise UserError(_("Only a DA under review can be approved."))
            if d.create_uid == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: you cannot approve a DA you created."))
            if d.contract_id.state != 'active':
                raise UserError(_("Contract %s is not active.", d.contract_id.name))
            c = d.contract_id
            if (c.valid_from and d.date < c.valid_from) or (c.valid_to and d.date > c.valid_to):
                raise UserError(_("DA date %s is outside the contract validity.", d.date))
            for l in d.line_ids:
                free = d._available(l.contract_line_id)
                if l.mtl > free + 1e-9:
                    if not l.override_reason:
                        raise UserError(_("Line '%(l)s' asks %(q)s MTL but only %(f)s MTL of the contract line is free. "
                                          "A special authorisation is needed.", l=l.contract_line_id.product_id.display_name,
                                          q=l.mtl, f=free))
                if (l.purchase_rate != l.contract_line_id.purchase_rate or l.sale_rate != l.contract_line_id.sale_rate) \
                        and not (l.rate_note or '').strip():
                    raise UserError(_("Line '%s' has rates different from the contract; explain in the rate note.",
                                      l.contract_line_id.product_id.display_name))
            d._sys({'state': 'approved', 'approved_by': self.env.user.id, 'approved_at': fields.Datetime.now()})
            if d.previous_id:
                d.previous_id._sys({'state': 'amended'})

    def action_cancel(self, reason=None):
        for d in self:
            if d.state not in ('draft', 'under_review', 'approved'):
                raise UserError(_("A %s DA cannot be cancelled.", d.state))
            if not (reason or '').strip():
                raise UserError(_("A cancellation reason is required."))
            if d.state == 'approved':
                if not self.env.user.has_group('ei_contract_da.group_ei_contract_approver'):
                    raise AccessError(_("Only an approver can cancel an approved DA."))
                if d.lifted_mtl:
                    raise UserError(_("%s MTL are already lifted; cancel is not possible, close the DA instead.", d.lifted_mtl))
            d._sys({'state': 'cancelled', 'cancel_reason': reason})

    def action_close(self):
        for d in self:
            if d.state not in ('approved', 'fulfilled'):
                raise UserError(_("Only an approved or fulfilled DA can be closed."))
            d._sys({'state': 'closed'})

    def action_amend(self):
        self.ensure_one()
        if self.state not in ('approved', 'fulfilled'):
            raise UserError(_("Only an approved DA can be amended."))
        top = max(self.search([('company_id', '=', self.company_id.id), ('parent_partner_id', '=', self.parent_partner_id.id),
                               ('name', '=', self.name)]).mapped('amendment_no'))
        new = self.copy({'name': self.name, 'amendment_no': top + 1, 'previous_id': self.id, 'state': 'draft',
                         'maker_id': self.env.user.id})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': new.id, 'views': [(False, 'form')]}

    def _cancel_for_revision(self, new_contract):
        self._sys({'state': 'cancelled', 'cancel_reason': _('Contract revised to %s; re-enter the DA against it.', new_contract.name)})

    def _update_fulfilment(self):
        for d in self.filtered(lambda x: x.state in ('approved', 'fulfilled')):
            done = bool(d.line_ids) and all(l.lifted_mtl >= l.mtl for l in d.line_ids)
            if done and d.state == 'approved':
                d._sys({'state': 'fulfilled'})
            elif not done and d.state == 'fulfilled':
                d._sys({'state': 'approved'})
        self.contract_id._refresh_fulfilment()


class EiDaLine(models.Model):
    _name = 'ei.da.line'
    _description = 'DA line'
    _order = 'da_id, sequence, id'

    da_id = fields.Many2one('ei.da', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    state = fields.Selection(related='da_id.state', store=True)
    company_id = fields.Many2one(related='da_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='da_id.contract_id.currency_id')
    contract_line_id = fields.Many2one('ei.contract.line', required=True, index=True,
                                       domain="[('contract_id', '=', parent.contract_id)]")
    product_id = fields.Many2one(related='contract_line_id.product_id', store=True)
    mtl = fields.Float('MTL', digits=(16, 3), required=True)
    customer_id = fields.Many2one('res.partner', string='Customer')
    purchase_rate = fields.Monetary(currency_field='currency_id')
    sale_rate = fields.Monetary(currency_field='currency_id')
    rate_note = fields.Char()
    override_reason = fields.Char(readonly=True, help="Special authorisation to exceed the free contract quantity.")
    override_by = fields.Many2one('res.users', readonly=True)
    lifted_mtl = fields.Float('Verified lifted (MTL)', compute='_compute_lifted', digits=(16, 3))
    remaining_to_lift = fields.Float(compute='_compute_lifted', digits=(16, 3))
    remarks = fields.Char()

    @api.depends()
    def _compute_lifted(self):
        for l in self:
            l.lifted_mtl = 0.0  # overridden by ei_material_lifting
            l.remaining_to_lift = l.mtl - l.lifted_mtl

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            cl = self.env['ei.contract.line'].browse(v.get('contract_line_id'))
            if cl:
                v.setdefault('purchase_rate', cl.purchase_rate)
                v.setdefault('sale_rate', cl.sale_rate)
            d = self.env['ei.da'].browse(v.get('da_id'))
            if d and d.state not in ('draft',) and not self.env.context.get('ei_system'):
                raise UserError(_("The DA is not a draft; amend it instead."))
        return super().create(vals_list)

    def write(self, vals):
        locked = {'mtl', 'contract_line_id', 'customer_id', 'purchase_rate', 'sale_rate'}
        if locked & set(vals) and any(r.da_id.state != 'draft' for r in self) and not self.env.context.get('ei_system'):
            raise UserError(_("The DA is not a draft; amend it instead."))
        return super().write(vals)

    def unlink(self):
        if any(r.da_id.state != 'draft' for r in self):
            raise UserError(_("The DA is not a draft; its lines are locked."))
        return super().unlink()

    @api.constrains('mtl', 'contract_line_id')
    def _check(self):
        for l in self:
            if l.mtl <= 0:
                raise UserError(_("MTL must be positive."))
            if l.contract_line_id.contract_id != l.da_id.contract_id:
                raise UserError(_("The contract line belongs to another contract."))

    def action_authorise_over_quantity(self, reason=None):
        """Special authorisation to exceed the free contract quantity (explicit, logged)."""
        if not self.env.user.has_group('ei_contract_da.group_ei_da_override'):
            raise AccessError(_("You are not allowed to authorise quantities above the contract."))
        if not (reason or '').strip():
            raise UserError(_("A reason is required."))
        for l in self:
            l.with_context(ei_system=True).write({'override_reason': reason, 'override_by': self.env.user.id})
            l.da_id.message_post(body=_("Over-quantity authorised for %(p)s by %(u)s: %(r)s",
                                        p=l.contract_line_id.product_id.display_name, u=self.env.user.name, r=reason))
