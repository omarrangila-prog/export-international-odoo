from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiDailyOrder(models.Model):
    _name = 'ei.daily.order'
    _description = 'Daily Order Request'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(readonly=True, copy=False, default='New')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    parent_partner_id = fields.Many2one('res.partner', string='Supplier (parent company)', required=True, index=True)
    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('cancelled', 'Cancelled')],
                             default='draft', readonly=True, tracking=True, index=True)
    maker_id = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_at = fields.Datetime(readonly=True)
    cancel_reason = fields.Char(readonly=True)
    line_ids = fields.One2many('ei.daily.order.line', 'order_id')
    total_requested = fields.Float(compute='_compute_totals', digits=(16, 3))
    total_remaining = fields.Float(compute='_compute_totals', digits=(16, 3))
    print_count = fields.Integer(readonly=True)

    _uniq = models.Constraint('unique(company_id, parent_partner_id, date)',
                              'A Daily Order Request already exists for this supplier and date.')

    @api.depends('line_ids.requested_mtl', 'line_ids.remaining_mtl', 'line_ids.state')
    def _compute_totals(self):
        for o in self:
            live = o.line_ids.filtered(lambda l: l.state != 'cancelled')
            o.total_requested = sum(live.mapped('requested_mtl'))
            o.total_remaining = sum(live.mapped('remaining_mtl'))

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'New') == 'New':
                v['name'] = self.env['ir.sequence'].next_by_code('ei.daily.order') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('ei_system') and {'parent_partner_id', 'date', 'company_id'} & set(vals) \
                and any(r.state != 'draft' for r in self):
            raise UserError(_("Only a draft order request can be edited."))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_("Only draft order requests can be deleted; cancel them instead."))
        return super().unlink()

    # -------------------------------------------------------------- generate
    @api.model
    def generate_from_da(self, da, date=None):
        """Idempotent: one request per (company, supplier, date); each DA line is added at most once per
        request; quantities never exceed what the DA still has unrequested. Repeating the action is a no-op."""
        if da.state not in ('approved',):
            raise UserError(_("DA %(d)s is %(s)s; only approved DAs generate order requests.", d=da.name, s=da.state))
        date = date or fields.Date.context_today(self)
        order = self.search([('company_id', '=', da.company_id.id), ('parent_partner_id', '=', da.parent_partner_id.id),
                             ('date', '=', date)], limit=1)
        if order and order.state != 'draft':
            raise UserError(_("%(o)s for %(d)s is already %(s)s; new DA quantities need a new day or a cancelled order.",
                              o=order.name, d=date, s=order.state))
        if not order:
            order = self.create({'company_id': da.company_id.id, 'parent_partner_id': da.parent_partner_id.id, 'date': date})
        added = self.env['ei.daily.order.line']
        for dl in da.line_ids:
            if dl in order.line_ids.da_line_id:
                continue
            free = dl._requestable_mtl()
            if free <= 0:
                continue
            added += self.env['ei.daily.order.line'].create({
                'order_id': order.id, 'da_line_id': dl.id, 'requested_mtl': free})
        return order

    # -------------------------------------------------------------- workflow
    def action_approve(self):
        if not self.env.user.has_group('ei_daily_orders.group_ei_order_approver'):
            raise AccessError(_("Only an order approver can approve."))
        for o in self:
            if o.state != 'draft':
                raise UserError(_("Only a draft can be approved."))
            if not o.line_ids:
                raise UserError(_("An order request without lines cannot be approved."))
            if o.create_uid == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: you cannot approve a request you created."))
            for l in o.line_ids:
                l._check_quantity()
            o.with_context(ei_system=True).write({'state': 'approved', 'approved_by': self.env.user.id,
                                                   'approved_at': fields.Datetime.now()})

    def action_cancel(self, reason=None):
        for o in self:
            if o.state == 'cancelled':
                continue
            if not (reason or '').strip():
                raise UserError(_("A cancellation reason is required."))
            if o.state == 'approved' and not self.env.user.has_group('ei_daily_orders.group_ei_order_approver'):
                raise AccessError(_("Only an approver can cancel an approved request."))
            if o.line_ids.filtered('invoice_ref'):
                raise UserError(_("A supplier invoice is already recorded against this request."))
            o.with_context(ei_system=True).write({'state': 'cancelled', 'cancel_reason': reason})

    def action_print(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Print only approved requests."))
        self.with_context(ei_system=True).print_count += 1
        return self.env.ref('ei_daily_orders.action_report_daily_order').report_action(self)

    def action_send_email(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Send only approved requests."))
        tmpl = self.env.ref('ei_daily_orders.mail_template_daily_order')
        ctx = {'default_model': self._name, 'default_res_ids': self.ids, 'default_template_id': tmpl.id,
               'default_composition_mode': 'comment', 'force_email': True}
        return {'type': 'ir.actions.act_window', 'res_model': 'mail.compose.message', 'views': [(False, 'form')],
                'target': 'new', 'context': ctx}


class EiDailyOrderLine(models.Model):
    _name = 'ei.daily.order.line'
    _description = 'Daily Order Request line'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one('ei.daily.order', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    currency_id = fields.Many2one(related='da_line_id.currency_id')
    da_line_id = fields.Many2one('ei.da.line', required=True, index=True, domain="[('state', '=', 'approved')]")
    da_id = fields.Many2one(related='da_line_id.da_id', store=True)
    product_id = fields.Many2one(related='da_line_id.product_id', store=True)
    customer_id = fields.Many2one(related='da_line_id.customer_id', store=True)
    state = fields.Selection(related='order_id.state', store=True)
    requested_mtl = fields.Float('Requested MTL', digits=(16, 3), required=True)
    sale_rate = fields.Monetary(related='da_line_id.sale_rate', currency_field='currency_id')
    purchase_rate = fields.Monetary(related='da_line_id.purchase_rate', currency_field='currency_id')
    lifted_mtl = fields.Float('Verified lifted', compute='_compute_lifted', digits=(16, 3))
    remaining_mtl = fields.Float('Remaining to lift', compute='_compute_lifted', digits=(16, 3))
    invoice_ref = fields.Char('Supplier invoice no.', copy=False,
                              help="Recorded when the supplier invoice arrives. It does NOT mean the material was lifted.")

    _uniq = models.Constraint('unique(order_id, da_line_id)', 'This DA line is already on the order request.')

    @api.depends('requested_mtl', 'da_line_id.lifted_mtl')
    def _compute_lifted(self):
        for l in self:
            l.lifted_mtl = l._lifted_for_line()
            l.remaining_mtl = l.requested_mtl - l.lifted_mtl

    def _lifted_for_line(self):
        return 0.0  # overridden by ei_material_lifting (verified lifting records only)

    def _check_quantity(self):
        for l in self:
            others = sum(x.requested_mtl for x in l.da_line_id.order_line_ids
                         if x != l and x.state in ('draft', 'approved'))
            if l.requested_mtl <= 0:
                raise UserError(_("Requested MTL must be positive."))
            if l.requested_mtl + others > l.da_line_id.mtl + 1e-9:
                raise UserError(_("Requests for DA %(d)s total %(t)s MTL, above the DA quantity %(q)s.",
                                  d=l.da_id.name, t=l.requested_mtl + others, q=l.da_line_id.mtl))

    @api.constrains('requested_mtl')
    def _check_positive(self):
        for l in self:
            if l.requested_mtl <= 0:
                raise UserError(_("Requested MTL must be positive."))

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            o = self.env['ei.daily.order'].browse(v.get('order_id'))
            if o and o.state != 'draft' and not self.env.context.get('ei_system'):
                raise UserError(_("The request is %s; its lines are locked.", o.state))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('ei_system'):
            return super().write(vals)
        if set(vals) - {'invoice_ref', 'sequence'} and any(r.order_id.state != 'draft' for r in self):
            raise UserError(_("The request is not a draft; its lines are locked."))
        if 'invoice_ref' in vals and any(r.order_id.state != 'approved' for r in self):
            raise UserError(_("Record the invoice number only on an approved request."))
        return super().write(vals)

    def unlink(self):
        if any(r.order_id.state != 'draft' for r in self):
            raise UserError(_("The request is not a draft; its lines are locked."))
        return super().unlink()


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    order_line_ids = fields.One2many('ei.daily.order.line', 'da_line_id')
    requested_mtl = fields.Float(compute='_compute_requested', digits=(16, 3))

    @api.depends('order_line_ids.requested_mtl', 'order_line_ids.state')
    def _compute_requested(self):
        for l in self:
            l.requested_mtl = sum(x.requested_mtl for x in l.order_line_ids if x.state in ('draft', 'approved'))

    def _requestable_mtl(self):
        self.ensure_one()
        return self.mtl - sum(x.requested_mtl for x in self.order_line_ids if x.state in ('draft', 'approved'))


class EiDa(models.Model):
    _inherit = 'ei.da'

    def action_generate_order(self):
        self.ensure_one()
        order = self.env['ei.daily.order'].generate_from_da(self)
        return {'type': 'ir.actions.act_window', 'res_model': 'ei.daily.order', 'res_id': order.id, 'views': [(False, 'form')]}
