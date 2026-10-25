from collections import defaultdict

from odoo import Command, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiInvoiceWizard(models.TransientModel):
    _name = 'ei.invoice.wizard'
    _description = 'Create customer invoices from verified liftings'

    lifting_ids = fields.Many2many('ei.lifting', string='Verified liftings')
    line_ids = fields.One2many('ei.invoice.wizard.line', 'wizard_id')
    invoice_date = fields.Date(default=fields.Date.context_today)
    post = fields.Boolean('Post immediately', default=False)

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get('active_ids') if self.env.context.get('active_model') == 'ei.lifting' else []
        if ids:
            res['lifting_ids'] = [Command.set(ids)]
            res['line_ids'] = [Command.create({'lifting_id': l.id, 'unit_price': l.da_line_id.sale_rate})
                               for l in self.env['ei.lifting'].browse(ids)]
        return res

    def action_create(self):
        self.ensure_one()
        lifts = self.line_ids.lifting_id
        if not lifts:
            raise UserError(_("Select verified liftings to invoice."))
        lifts = lifts.sudo().filtered(lambda l: True)  # row lock below
        self.env.cr.execute("SELECT id FROM ei_lifting WHERE id IN %s FOR UPDATE", (tuple(lifts.ids),))
        lifts.invalidate_recordset(['invoice_move_id', 'invoice_status', 'state'])
        by_customer = defaultdict(list)
        for wl in self.line_ids:
            l = wl.lifting_id
            if l.state != 'verified':
                raise UserError(_("%s is not a verified lifting.", l.name))
            if l.invoice_status != 'to_invoice':
                raise UserError(_("%s is already invoiced (%s).", l.name, l.invoice_move_id.name or ''))
            if not l.customer_id:
                raise UserError(_("%s has no customer.", l.name))
            if l.company_id != self.env.company and l.company_id not in self.env.companies:
                raise UserError(_("%s belongs to another company.", l.name))
            if wl.unit_price <= 0:
                raise UserError(_("%s has no sale rate; fix the DA before invoicing.", l.name))
            if wl.unit_price != l.da_line_id.sale_rate:
                if not self.env.user.has_group('ei_invoice_extensions.group_ei_invoice_approver'):
                    raise AccessError(_("Only an invoice approver can adjust a price."))
                if not (wl.adjust_reason or '').strip():
                    raise UserError(_("Give the reason for adjusting the price of %s.", l.name))
            by_customer[(l.company_id.id, l.customer_id.id)].append(wl)
        moves = self.env['account.move']
        for (company_id, partner_id), wls in by_customer.items():
            partner = self.env['res.partner'].browse(partner_id)
            lines = []
            for wl in wls:
                l = wl.lifting_id
                name = l.product_id.display_name
                if partner.ei_show_dispatch_details:
                    name += _(" - DA %(d)s, gate pass %(g)s, vehicle %(v)s, %(dt)s", d=l.da_id.name, g=l.gate_pass_no,
                              v=l.vehicle_no, dt=l.date)
                lines.append(Command.create({'product_id': l.product_id.id, 'name': name, 'quantity': l.verified_mtl,
                                             'price_unit': wl.unit_price, 'product_uom_id': l.contract_line_id.uom_id.id}))
            move = self.env['account.move'].with_company(company_id).create({
                'move_type': 'out_invoice', 'partner_id': partner_id, 'company_id': company_id,
                'invoice_date': self.invoice_date, 'invoice_line_ids': lines, 'ref': ', '.join(w.lifting_id.name for w in wls)})
            for wl in wls:
                wl.lifting_id.sudo().with_context(ei_system=True).invoice_move_id = move.id
                if wl.unit_price != wl.lifting_id.da_line_id.sale_rate:
                    move.message_post(body=_("Price of %(l)s adjusted from %(o)s to %(n)s by %(u)s: %(r)s",
                                             l=wl.lifting_id.name, o=wl.lifting_id.da_line_id.sale_rate, n=wl.unit_price,
                                             u=self.env.user.name, r=wl.adjust_reason))
            if self.post:
                move.action_post()
            moves += move
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move', 'view_mode': 'list,form',
                'domain': [('id', 'in', moves.ids)], 'name': _('Customer invoices')}


class EiInvoiceWizardLine(models.TransientModel):
    _name = 'ei.invoice.wizard.line'
    _description = 'Invoice wizard line'

    wizard_id = fields.Many2one('ei.invoice.wizard', ondelete='cascade')
    lifting_id = fields.Many2one('ei.lifting', required=True)
    verified_mtl = fields.Float(related='lifting_id.verified_mtl')
    unit_price = fields.Float(digits=(16, 2))
    adjust_reason = fields.Char()
