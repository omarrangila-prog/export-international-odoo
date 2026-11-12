"""The client's three parties, and feeding without a contract first (11 Nov 2026).

    SUPPLIER (Purchase From)  ->  Purchase (IN)  ->  Sold (OUT)
    the mill                      the buying entity   the final customer (per coil; may come later)

The operator types one DA on one screen. Behind it the system keeps a "feeding account" per supplier and buying entity: an
ei.contract of type 'feeding', opened by the system, clearly labelled as NOT a signed contract. It only gives the DA its
place in the existing chain (orders, lifting, invoices, reports); it carries no agreed quantity and no agreed rate."""
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError

NO_CAP = 1e12


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ei_is_supplier_mill = fields.Boolean('Supplier (Purchase From)', help="A mill the material is bought from. Offered on the feeding screen.")
    ei_is_purchase_in = fields.Boolean('Purchase (IN) entity', help="A buying entity of the group. Offered on the feeding screen.")
    ei_feeding_formula_id = fields.Many2one('ei.formula.definition', string='Rate formula for feeding', domain="[('state', '=', 'approved')]",
                                            help="The approved formula used for this mill's coils. Its parameters come from the formula's first "
                                                 "signed test case. Without one, only the direct method (typed rates) can be used.")


class EiContract(models.Model):
    _inherit = 'ei.contract'

    contract_type = fields.Selection(selection_add=[('feeding', 'Feeding account (opened from the feeding screen; not a signed contract)')],
                                     ondelete={'feeding': 'set default'})
    purchase_in_id = fields.Many2one('res.partner', string='Purchase (IN)', tracking=True)

    @api.model
    def _feeding_account(self, supplier, purchase_in):
        """The running feeding account of one supplier and one buying entity (found, or opened by the system)."""
        company = self.env.company
        dom = [('contract_type', '=', 'feeding'), ('parent_partner_id', '=', supplier.id), ('purchase_in_id', '=', purchase_in.id),
               ('company_id', '=', company.id), ('state', '=', 'active')]
        acc = self.sudo().search(dom, limit=1)
        if not acc:
            pkr = self.env.ref('base.PKR')
            acc = self.sudo().with_context(ei_system=True).create({
                'parent_partner_id': supplier.id, 'purchase_in_id': purchase_in.id, 'contract_type': 'feeding', 'company_id': company.id,
                'currency_id': pkr.id, 'contract_ref': 'FEEDING/%s/%s' % (supplier.id, purchase_in.id),
                'notes': _("Opened by the system from the feeding screen. Not a signed contract: it has no agreed quantity or rate.")})
            acc._sys({'state': 'active'})
            acc.message_post(body=_("Feeding account opened for %(s)s -> %(p)s by %(u)s's first entry.", s=supplier.display_name,
                                    p=purchase_in.display_name, u=self.env.user.name))
        return self.browse(acc.id)

    def _feeding_line(self, product):
        """The account's line for one material (found, or opened). Its formula is the mill's approved feeding formula."""
        self.ensure_one()
        if self.contract_type != 'feeding':
            raise UserError(_("%s is a signed contract; its materials are fixed.", self.name))
        line = self.line_ids.filtered(lambda l: l.product_id == product)[:1]
        if line:
            return line
        f = self.parent_partner_id.sudo().ei_feeding_formula_id
        f = f if f and f.state == 'approved' else self.env['ei.formula.definition']
        params = {}
        if f:
            test = f.sudo().test_ids[:1]
            try:
                params = json.loads(test.params_json or '{}') if test else {}
            except ValueError:
                params = {}
            for k in f._param_names():
                params.setdefault(k, '0')
        return self.env['ei.contract.line'].sudo().with_context(ei_system=True).create({
            'contract_id': self.id, 'product_id': product.id, 'ordered_mtl': 0.001, 'formula_id': f.id or False,
            'cost_class': 'commission' if f else 'direct',
            'param_ids': [(0, 0, {'key': k, 'value': str(v)}) for k, v in params.items()]})


class EiDa(models.Model):
    _inherit = 'ei.da'

    purchase_in_id = fields.Many2one('res.partner', string='Purchase (IN)', tracking=True,
                                     help="The buying entity. Not the final customer: that is Sold (OUT), on each coil.")
    sold_out_id = fields.Many2one('res.partner', string='Sold (OUT)', tracking=True,
                                  help="The final customer, offered on every new coil of this DA. Empty = not sold yet.")
    is_feeding_account = fields.Boolean('Entered without a signed contract', compute='_compute_is_feeding_account')

    @api.depends('contract_id.contract_type')
    def _compute_is_feeding_account(self):
        for d in self:
            d.is_feeding_account = d.contract_id.contract_type == 'feeding'

    def _available(self, cline):
        if cline.contract_id.contract_type == 'feeding':
            return NO_CAP                      # a feeding account has no agreed quantity to exceed
        return super()._available(cline)

    def action_approve(self):
        res = super().action_approve()
        for line in self.filtered(lambda d: d.state == 'approved' and d.contract_id.contract_type == 'feeding').line_ids.contract_line_id:
            fed = sum(l.mtl for l in line.da_line_ids if l.state in ('approved', 'fulfilled', 'closed'))
            line.sudo().with_context(ei_system=True).write({'ordered_mtl': max(fed, 0.001)})     # the account shows what was fed, nothing more
        return res


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    coil_thickness = fields.Char('Thickness')
    coil_width = fields.Char('Width')
    da_purchase_in_id = fields.Many2one(related='da_id.purchase_in_id', store=True, string='Purchase (IN)')
    sale_amount = fields.Monetary('Sale amount', compute='_compute_amounts', store=True, currency_field='currency_id')
    purchase_amount = fields.Monetary('Purchase amount', compute='_compute_amounts', store=True, currency_field='currency_id')
    sold_status = fields.Selection([('sold', 'Sold'), ('unsold', 'Not sold yet')], compute='_compute_sold_status', store=True, string='Sale')

    trace_invoice = fields.Char('Invoice No', compute='_compute_trace', help="Supplier invoice number(s) recorded on the daily order lines of this coil.")
    trace_hs = fields.Char('HS code', compute='_compute_trace')
    lifting_status = fields.Selection([('none', 'Not lifted'), ('part', 'Partly lifted'), ('done', 'Lifted')], compute='_compute_trace',
                                      string='Lifting')

    def _compute_trace(self):
        for l in self:
            orders = l.order_line_ids.filtered(lambda o: o.state != 'cancelled')
            l.trace_invoice = ', '.join(sorted(set(filter(None, orders.mapped('invoice_ref'))))) or False
            l.trace_hs = ', '.join(sorted(set(filter(None, orders.mapped('hs_code'))))) or False
            lifted = l.lifted_mtl or 0.0
            l.lifting_status = 'none' if lifted <= 1e-9 else ('done' if lifted + 1e-9 >= (l.mtl or 0.0) else 'part')

    @api.depends('mtl', 'sale_rate', 'purchase_rate')
    def _compute_amounts(self):
        for l in self:
            cur = l.currency_id or self.env.company.currency_id
            l.sale_amount = cur.round((l.mtl or 0.0) * (l.sale_rate or 0.0))
            l.purchase_amount = cur.round((l.mtl or 0.0) * (l.purchase_rate or 0.0))

    @api.depends('customer_id')
    def _compute_sold_status(self):
        for l in self:
            l.sold_status = 'sold' if l.customer_id else 'unsold'
