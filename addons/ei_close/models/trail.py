"""R5: the quantity trail of each delivery-advice line, from what was promised to what the customer was invoiced. Each step is counted
from its own records, so an invoice number never stands in for a truck, and a truck never stands in for an invoice."""
from odoo import fields, models

Q = dict(digits=(16, 3), compute='_compute_trail')


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    trail_requested = fields.Float('On order requests', **Q)
    trail_supplier_invoiced = fields.Float('Supplier invoiced', **Q)
    trail_lifted = fields.Float('Lifted (verified)', **Q)
    trail_customer_invoiced = fields.Float('Customer invoiced', **Q)
    trail_unlifted = fields.Float('Not yet lifted', **Q)
    trail_invoiced_not_lifted = fields.Float('Supplier invoiced, not lifted', **Q)
    trail_lifted_not_invoiced = fields.Float('Lifted, no supplier invoice', **Q)
    trail_unbilled = fields.Float('Lifted, customer not invoiced', **Q)
    trail_over_lifted = fields.Float('Lifted beyond the DA', **Q)
    trail_flag = fields.Selection([('ok', 'In step'), ('watch', 'Something to follow up')], compute='_compute_trail')

    def _compute_trail(self):
        IL = self.env['ei.supplier.intake.line'].sudo()
        Lift = self.env['ei.lifting'].sudo()
        inv = dict(IL._read_group([('da_line_id', 'in', self.ids), ('intake_id.kind', '=', 'in_invoice'),
                                   ('intake_id.state', 'in', ('matched', 'reviewed', 'billed'))], ['da_line_id'], ['received_mtl:sum']))
        cust = dict(Lift._read_group([('da_line_id', 'in', self.ids), ('state', '=', 'verified'), ('invoice_status', '=', 'invoiced')],
                                     ['da_line_id'], ['verified_mtl:sum']))
        for l in self:
            lifted = l.lifted_mtl
            si = inv.get(l, 0.0)
            ci = cust.get(l, 0.0)
            l.trail_requested = l.requested_mtl
            l.trail_supplier_invoiced = si
            l.trail_lifted = lifted
            l.trail_customer_invoiced = ci
            l.trail_unlifted = max(l.mtl - lifted, 0.0)
            l.trail_invoiced_not_lifted = max(si - lifted, 0.0)
            l.trail_lifted_not_invoiced = max(lifted - si, 0.0)
            l.trail_unbilled = max(lifted - ci, 0.0)
            l.trail_over_lifted = max(lifted - l.mtl, 0.0)
            l.trail_flag = 'watch' if any(v > 1e-9 for v in (l.trail_invoiced_not_lifted, l.trail_lifted_not_invoiced,
                                                              l.trail_unbilled, l.trail_over_lifted)) else 'ok'
