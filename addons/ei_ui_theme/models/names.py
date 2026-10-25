"""Readable names for records that are shown inside other records (instead of 'ei.da.line,7')."""
from odoo import api, models


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    @api.depends('da_id.name', 'product_id', 'mtl')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s - %s (%g MTL)' % (r.da_id.name or '', r.product_id.display_name or '', r.mtl)


class EiContractLine(models.Model):
    _inherit = 'ei.contract.line'

    @api.depends('contract_id.name', 'product_id', 'ordered_mtl')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s - %s (%g MTL)' % (r.contract_id.name or '', r.product_id.display_name or '', r.ordered_mtl)


class EiDailyOrderLine(models.Model):
    _inherit = 'ei.daily.order.line'

    @api.depends('order_id.name', 'da_id.name', 'product_id')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s - DA %s - %s' % (r.order_id.name or '', r.da_id.name or '', r.product_id.display_name or '')


class EiBankImportLine(models.Model):
    _inherit = 'ei.bank.import.line'

    @api.depends('date', 'amount', 'narration')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s  %s  %s' % (r.date or '', '{:,.2f}'.format(r.amount or 0), (r.narration or '')[:30])


class EiParentStatementLine(models.Model):
    _inherit = 'ei.parent.statement.line'

    @api.depends('invoice_no', 'status')
    def _compute_display_name(self):
        for r in self:
            r.display_name = r.invoice_no or ''


class EiSupplierIntakeLine(models.Model):
    _inherit = 'ei.supplier.intake.line'

    @api.depends('da_id.name', 'received_mtl')
    def _compute_display_name(self):
        for r in self:
            r.display_name = 'DA %s - %g MTL' % (r.da_id.name or '', r.received_mtl)


class EiBankAllocation(models.Model):
    _inherit = 'ei.bank.allocation'

    @api.depends('invoice_id', 'amount')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s - %s' % (r.invoice_id.display_name or '', '{:,.2f}'.format(r.amount or 0))
