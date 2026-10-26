"""Trade reports: the contract register with its expected GROSS spread (before commission, costs and taxes; not profit) and the material
lifted against it, and every verified truck loading. Same formulas as the dashboard: spread = ordered MTL x (sale rate - purchase rate);
lifted = verified loadings only."""
from odoo import fields, models, _
from odoo.tools import SQL

CONTRACT_STATE = [('draft', "Draft"), ('reviewed', "Reviewed"), ('approved', "Approved"), ('active', "Active"), ('fulfilled', "Fulfilled"), ('closed', "Closed"),
                  ('cancelled', "Cancelled")]


class EiReportContractSpread(models.Model):
    _name = 'ei.report.contract.spread'
    _inherit = 'ei.report.base'
    _description = "Contracts: ordered, promised, lifted and expected gross spread"
    _auto = False
    _order = 'contract_id, id'

    company_id = fields.Many2one('res.company', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    contract_id = fields.Many2one('ei.contract', "Contract", readonly=True)
    parent_partner_id = fields.Many2one('res.partner', "Parent company", readonly=True)
    state = fields.Selection(CONTRACT_STATE, "Contract state", readonly=True)
    product_id = fields.Many2one('product.product', "Material", readonly=True)
    grade = fields.Char("Grade / spec", readonly=True)
    ordered_mtl = fields.Float("Ordered (MTL)", readonly=True, digits=(16, 3))
    allocated_mtl = fields.Float("Promised on delivery advices (MTL)", readonly=True, digits=(16, 3))
    lifted_mtl = fields.Float("Lifted, verified (MTL)", readonly=True, digits=(16, 3))
    not_lifted_mtl = fields.Float("Promised, not yet lifted (MTL)", readonly=True, digits=(16, 3), help="Promised on delivery advices less lifted.")
    not_promised_mtl = fields.Float("Not yet promised (MTL)", readonly=True, digits=(16, 3), help="Ordered less promised.")
    purchase_rate = fields.Monetary("Buy rate / MTL", readonly=True, currency_field='currency_id', aggregator='avg')
    sale_rate = fields.Monetary("Sell rate / MTL", readonly=True, currency_field='currency_id', aggregator='avg')
    spread_per_mtl = fields.Monetary("Spread / MTL", readonly=True, currency_field='currency_id', aggregator='avg')
    gross_spread = fields.Monetary("Expected gross spread (provisional)", readonly=True, currency_field='currency_id',
                                   help="Ordered MTL x (sale rate - purchase rate). Before commission, costs and taxes. NOT profit; provisional until the tax and commission basis is approved.")

    def _select_sql(self):
        return SQL("""
            SELECT cl.id AS id, c.company_id AS company_id, c.currency_id AS currency_id, cl.contract_id AS contract_id, c.parent_partner_id AS parent_partner_id,
                   c.state AS state, cl.product_id AS product_id, cl.grade AS grade, cl.ordered_mtl AS ordered_mtl, cl.allocated_mtl AS allocated_mtl,
                   COALESCE(lf.mtl, 0) AS lifted_mtl, GREATEST(cl.allocated_mtl - COALESCE(lf.mtl, 0), 0) AS not_lifted_mtl,
                   cl.ordered_mtl - cl.allocated_mtl AS not_promised_mtl,
                   cl.purchase_rate AS purchase_rate, cl.sale_rate AS sale_rate, cl.sale_rate - cl.purchase_rate AS spread_per_mtl,
                   ROUND((cl.ordered_mtl * (cl.sale_rate - cl.purchase_rate))::numeric, COALESCE(cur.decimal_places, 2)) AS gross_spread
              FROM ei_contract_line cl
              JOIN ei_contract c ON c.id = cl.contract_id
              JOIN res_currency cur ON cur.id = c.currency_id
              LEFT JOIN (SELECT contract_line_id, SUM(verified_mtl) AS mtl FROM ei_lifting WHERE state = 'verified' GROUP BY contract_line_id) lf ON lf.contract_line_id = cl.id
        """)

    def action_open_source(self):
        self.ensure_one()
        return self._open_record(self.contract_id)


class EiReportLifting(models.Model):
    _name = 'ei.report.lifting'
    _inherit = 'ei.report.base'
    _description = "Material lifting: every truck loading"
    _auto = False
    _order = 'date desc, id desc'

    company_id = fields.Many2one('res.company', readonly=True)
    date = fields.Date("Dispatch date", readonly=True)
    month = fields.Char("Month", readonly=True)
    customer_id = fields.Many2one('res.partner', "Customer", readonly=True)
    contract_id = fields.Many2one('ei.contract', "Contract", readonly=True)
    da_id = fields.Many2one('ei.da', "Delivery advice", readonly=True)
    product_id = fields.Many2one('product.product', "Material", readonly=True)
    vehicle_no = fields.Char("Truck", readonly=True)
    state = fields.Selection([('draft', "Draft"), ('verified', "Verified"), ('reversed', "Reversed")], readonly=True)
    claimed_mtl = fields.Float("Gate-pass quantity (MTL)", readonly=True, digits=(16, 3))
    lifted_mtl = fields.Float("Lifted, verified (MTL)", readonly=True, digits=(16, 3), help="Verified loadings only; a draft or reversed loading counts as zero.")
    discrepancy_mtl = fields.Float("Weighed less gate pass (MTL)", readonly=True, digits=(16, 3))
    invoice_status = fields.Char("Invoice", readonly=True)

    def _select_sql(self):
        return SQL("""
            SELECT l.id AS id, l.company_id AS company_id, l.date AS date, TO_CHAR(l.date, 'YYYY-MM') AS month, l.customer_id AS customer_id,
                   cl.contract_id AS contract_id, l.da_id AS da_id, l.product_id AS product_id, l.vehicle_no AS vehicle_no, l.state AS state,
                   l.claimed_mtl AS claimed_mtl, CASE WHEN l.state = 'verified' THEN l.verified_mtl ELSE 0 END AS lifted_mtl,
                   l.discrepancy_mtl AS discrepancy_mtl, l.invoice_status AS invoice_status
              FROM ei_lifting l
              JOIN ei_contract_line cl ON cl.id = l.contract_line_id
        """)

    def action_open_source(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Truck loading"), 'res_model': 'ei.lifting', 'res_id': self.id, 'views': [[False, 'form']], 'target': 'current'}
