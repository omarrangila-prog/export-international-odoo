from odoo.tools.misc import format_amount
from odoo import api, fields, models, _, Command
from odoo.exceptions import AccessError, UserError


class EiSupplierIntake(models.Model):
    _name = 'ei.supplier.intake'
    _description = 'Supplier invoice intake (checked before any bill exists)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(readonly=True, copy=False, default='New')
    kind = fields.Selection([('in_invoice', 'Supplier invoice'), ('in_refund', 'Supplier credit note')],
                            required=True, default='in_invoice')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda s: s.env.company.currency_id)
    partner_id = fields.Many2one('res.partner', string='Supplier (parent company)', required=True, tracking=True)
    invoice_number = fields.Char('Supplier invoice no.', required=True, tracking=True)
    invoice_date = fields.Date(required=True)
    original_id = fields.Many2one('ei.supplier.intake', string='Invoice credited',
                                  domain="[('kind', '=', 'in_invoice'), ('partner_id', '=', partner_id), ('state', '!=', 'cancelled')]")
    tax_ids = fields.Many2many('account.tax', domain="[('type_tax_use', '=', 'purchase')]",
                               help="Taxes the reviewer applies according to the contract. Odoo's own tax configuration computes the expected tax.")
    stated_tax = fields.Monetary('Tax stated on the invoice', currency_field='currency_id')
    stated_total = fields.Monetary('Total stated on the invoice', currency_field='currency_id', required=True)
    line_ids = fields.One2many('ei.supplier.intake.line', 'intake_id')
    untaxed = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    expected_tax = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    expected_total = fields.Monetary(compute='_compute_amounts', store=True, currency_field='currency_id')
    state = fields.Selection([
        ('draft', 'Draft'), ('mismatch', 'Mismatch - blocked'), ('matched', 'Matched'),
        ('reviewed', 'Reviewed with approval'), ('billed', 'Bill created'), ('cancelled', 'Cancelled'),
    ], default='draft', readonly=True, tracking=True, index=True)
    issue_text = fields.Text(readonly=True)
    review_note = fields.Text()
    reviewed_by = fields.Many2one('res.users', readonly=True)
    maker_id = fields.Many2one('res.users', readonly=True, default=lambda s: s.env.user)
    bill_id = fields.Many2one('account.move', readonly=True, copy=False)
    ocr_status = fields.Char(compute='_compute_ocr_status')
    attachment_count = fields.Integer('Papers attached', compute='_compute_attachment_count')

    _dup = models.UniqueIndex("(company_id, partner_id, invoice_number, kind) WHERE state != 'cancelled'",
                              "This supplier invoice number was already taken in.")

    def _compute_ocr_status(self):
        for r in self:
            r.ocr_status = _("OCR provider not configured - enter the invoice manually")

    def _compute_attachment_count(self):
        data = dict(self.env['ir.attachment']._read_group(
            [('res_model', '=', self._name), ('res_id', 'in', self.ids)], ['res_id'], ['__count']))
        for r in self:
            r.attachment_count = data.get(r.id, 0)

    @api.depends('line_ids.amount', 'tax_ids', 'currency_id', 'kind')
    def _compute_amounts(self):
        for r in self:
            untaxed = sum(r.line_ids.mapped('amount'))
            tax = 0.0
            if r.tax_ids and untaxed:
                tax = r.tax_ids.compute_all(untaxed, r.currency_id, 1.0, partner=r.partner_id)['total_included'] - untaxed
            r.untaxed, r.expected_tax = untaxed, r.currency_id.round(tax)
            r.expected_total = r.untaxed + r.expected_tax

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            if v.get('name', 'New') == 'New':
                v['name'] = self.env['ir.sequence'].next_by_code('ei.supplier.intake') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('ei_system') and set(vals) - {'review_note', 'message_follower_ids'} \
                and any(r.state in ('billed', 'cancelled') for r in self):
            raise UserError(_("A billed or cancelled intake cannot be changed."))
        res = super().write(vals)
        if not self.env.context.get('ei_system') and set(vals) - {'review_note', 'message_follower_ids'}:
            for r in self.filtered(lambda x: x.state in ('mismatch', 'matched', 'reviewed')):
                r.with_context(ei_system=True).write({'state': 'draft', 'issue_text': False, 'reviewed_by': False})
        return res

    # ----------------------------------------------------------------- checks
    def _run_checks(self):
        self.ensure_one()
        issues = []
        cur = self.currency_id
        if not self.line_ids:
            issues.append(_("No lines."))
        if not self.attachment_count:
            issues.append(_("The supplier's invoice document is not attached."))
        dup = self.env['account.move'].sudo().search_count([
            ('company_id', '=', self.company_id.id), ('partner_id', '=', self.partner_id.id),
            ('ref', '=', self.invoice_number), ('move_type', '=', self.kind), ('state', '!=', 'cancel'),
            ('id', '!=', self.bill_id.id)])
        if dup:
            issues.append(_("A bill with this supplier and invoice number already exists in accounting."))
        if self.kind == 'in_refund':
            if not self.original_id:
                issues.append(_("A credit note must reference the invoice it credits."))
            else:
                credited = sum(l.received_mtl for l in self.original_id.line_ids)
                already = sum(l.received_mtl for c in self.search([('original_id', '=', self.original_id.id), ('state', '!=', 'cancelled'), ('id', '!=', self.id)]) for l in c.line_ids)
                mine = sum(l.received_mtl for l in self.line_ids)
                if already + mine > credited + 1e-9:
                    issues.append(_("Credit quantity %(q)s exceeds the invoiced %(c)s MTL.", q=already + mine, c=credited))
        for l in self.line_ids:
            issues += l._issues()
        if not cur.is_zero(self.stated_tax - self.expected_tax):
            issues.append(_("Stated tax %(s)s differs from the tax computed from the selected taxes %(e)s.",
                            s=self.stated_tax, e=self.expected_tax))
        if not cur.is_zero(self.stated_total - self.expected_total):
            issues.append(_("Stated total %(s)s differs from lines + tax %(e)s.", s=self.stated_total, e=self.expected_total))
        return issues

    def action_check(self):
        for r in self:
            if r.state not in ('draft', 'mismatch'):
                continue
            issues = r._run_checks()
            r.with_context(ei_system=True).write({
                'issue_text': '\n'.join(issues) or False, 'state': 'mismatch' if issues else 'matched'})

    def action_override(self):
        if not self.env.user.has_group('ei_invoice_extensions.group_ei_invoice_approver'):
            raise AccessError(_("Only an invoice approver can accept a mismatch."))
        for r in self:
            if r.state != 'mismatch':
                raise UserError(_("Only a mismatched intake needs an override."))
            if not (r.review_note or '').strip():
                raise UserError(_("Write the reason for accepting the mismatch in the review note."))
            if r.maker_id == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: you cannot accept the mismatch of an intake you entered."))
            r.with_context(ei_system=True).write({'state': 'reviewed', 'reviewed_by': self.env.user.id})

    def action_create_bill(self):
        """Creates a DRAFT vendor bill. Posting stays an accountant decision."""
        for r in self:
            if r.state not in ('matched', 'reviewed'):
                raise UserError(_("Only a matched or reviewed intake can create a bill."))
            lines = [Command.create({
                'product_id': l.product_id.id, 'name': '%s - %s' % (l.da_id.name, l.product_id.display_name),
                'quantity': l.received_mtl, 'price_unit': l.unit_rate, 'tax_ids': [Command.set(r.tax_ids.ids)],
            }) for l in r.line_ids]
            bill = self.env['account.move'].create({
                'move_type': r.kind, 'partner_id': r.partner_id.id, 'ref': r.invoice_number,
                'invoice_date': r.invoice_date, 'currency_id': r.currency_id.id, 'company_id': r.company_id.id,
                'invoice_line_ids': lines})
            if not r.currency_id.is_zero(bill.amount_total - r.stated_total):
                raise UserError(_("The created bill total %(b)s differs from the stated total %(s)s; check the taxes.",
                                  b=bill.amount_total, s=r.stated_total))
            r.with_context(ei_system=True).write({'bill_id': bill.id, 'state': 'billed'})
            if r.kind == 'in_invoice':
                for l in r.line_ids.filtered('order_line_id'):
                    ref = l.order_line_id.invoice_ref
                    refs = {x for x in (ref or '').split(', ') if x} | {r.invoice_number}
                    l.order_line_id.with_context(ei_system=True).invoice_ref = ', '.join(sorted(refs))

    def action_cancel(self):
        for r in self:
            if r.state == 'billed':
                raise UserError(_("Cancel or reverse the bill in accounting first."))
            r.with_context(ei_system=True).state = 'cancelled'

    def action_ocr(self):
        raise UserError(_("No OCR provider is configured. Enter the invoice manually; "
                          "nothing is guessed from the attachment."))


class EiSupplierIntakeLine(models.Model):
    _name = 'ei.supplier.intake.line'
    _description = 'Supplier invoice intake line'

    intake_id = fields.Many2one('ei.supplier.intake', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='intake_id.currency_id')
    da_line_id = fields.Many2one('ei.da.line', required=True, domain="[('state', 'in', ('approved', 'fulfilled'))]")
    da_id = fields.Many2one(related='da_line_id.da_id', store=True)
    product_id = fields.Many2one(related='da_line_id.product_id', store=True)
    order_line_id = fields.Many2one('ei.daily.order.line', domain="[('da_line_id', '=', da_line_id), ('state', '=', 'approved')]")
    received_mtl = fields.Float('Invoiced MTL', digits=(16, 3), required=True)
    unit_rate = fields.Monetary('Rate / MTL', currency_field='currency_id', required=True)
    amount = fields.Monetary(compute='_compute_amount', store=True, currency_field='currency_id')
    expected_mtl = fields.Float(compute='_compute_expected', digits=(16, 3))
    expected_rate = fields.Monetary(related='da_line_id.purchase_rate', currency_field='currency_id')

    @api.depends('received_mtl', 'unit_rate', 'currency_id')
    def _compute_amount(self):
        for l in self:
            l.amount = l.currency_id.round(l.received_mtl * l.unit_rate) if l.currency_id else 0.0

    @api.depends('da_line_id', 'order_line_id', 'intake_id.state')
    def _compute_expected(self):
        for l in self:
            invoiced = sum(x.received_mtl for x in self.search([
                ('da_line_id', '=', l.da_line_id.id), ('id', '!=', l._origin.id),
                ('intake_id.kind', '=', 'in_invoice'), ('intake_id.state', 'in', ('matched', 'reviewed', 'billed'))]))
            cap = l.order_line_id.requested_mtl if l.order_line_id else l.da_line_id.mtl
            l.expected_mtl = max(cap - invoiced, 0.0) if l.intake_id.kind == 'in_invoice' else l.received_mtl

    def _issues(self):
        self.ensure_one()
        out = []
        pa = self.intake_id.partner_id
        if self.da_line_id.da_id.parent_partner_id != pa:
            out.append(_("DA %(d)s belongs to %(p)s, not to the invoicing supplier.", d=self.da_id.name,
                         p=self.da_line_id.da_id.parent_partner_id.name))
        if self.received_mtl <= 0:
            out.append(_("%s: quantity must be positive.", self.da_id.name))
        if self.intake_id.kind == 'in_invoice' and self.received_mtl > self.expected_mtl + 1e-9:
            out.append(_("%(d)s: invoiced %(q)s MTL, only %(e)s MTL expected.", d=self.da_id.name, q=self.received_mtl, e=self.expected_mtl))
        if self.currency_id.compare_amounts(self.unit_rate, self.expected_rate):
            fmt = lambda v: format_amount(self.env, v, self.currency_id)
            diff = self.unit_rate - self.expected_rate
            out.append(_("%(d)s: the supplier's rate %(r)s per MTL differs from the delivery advice's buy rate %(e)s per MTL: %(v)s per MTL %(w)s agreed, "
                         "%(i)s on the %(q)s MTL invoiced.", d=self.da_id.name, r=fmt(self.unit_rate), e=fmt(self.expected_rate), v=fmt(abs(diff)),
                         w=_("more than") if diff > 0 else _("less than"), i=fmt(abs(diff) * self.received_mtl), q=self.received_mtl))
        return out

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            i = self.env['ei.supplier.intake'].browse(v.get('intake_id'))
            if i.state in ('billed', 'cancelled'):
                raise UserError(_("A billed or cancelled intake cannot be changed."))
        recs = super().create(vals_list)
        recs.intake_id._reset_after_edit()
        return recs

    def write(self, vals):
        if any(r.intake_id.state in ('billed', 'cancelled') for r in self):
            raise UserError(_("A billed or cancelled intake cannot be changed."))
        res = super().write(vals)
        self.intake_id._reset_after_edit()
        return res

    def unlink(self):
        if any(r.intake_id.state in ('billed', 'cancelled') for r in self):
            raise UserError(_("A billed or cancelled intake cannot be changed."))
        intakes = self.intake_id
        res = super().unlink()
        intakes._reset_after_edit()
        return res


class EiSupplierIntakeReset(models.Model):
    _inherit = 'ei.supplier.intake'

    def _reset_after_edit(self):
        for r in self.filtered(lambda x: x.state in ('mismatch', 'matched', 'reviewed')):
            r.with_context(ei_system=True).write({'state': 'draft', 'issue_text': False, 'reviewed_by': False})
