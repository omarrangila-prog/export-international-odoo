from odoo import models, _


class EiReportCatalog(models.AbstractModel):
    _inherit = 'ei.report.catalog'

    def _entries(self):
        out = [e for e in super()._entries() if e['key'] != 'month_end']
        ctl, trade, fin = _("Management and controls"), _("Trade and invoicing"), _("Money")
        R = lambda key, area, title, question, definition, source, status, action=None, model=None, note='': dict(
            key=key, area=area, title=title, question=question, definition=definition, source=source, status=status, action=action, model=model, note=note)
        for e in out:
            if e['key'] == 'parent_recon':
                e['note'] = _("Each statement shows where the parent's total goes (agrees, differs, only theirs, listed twice, only ours) and "
                              "cannot be signed until the printed total equals the imported rows. Aging of differences across months is not built.")
        return out + [
            R('month_end', ctl, _("Day and month close"), _("What is left to close the day or the month?"),
              _("A checklist worked out from the records: bank confirmations with proof, bank lines waiting, cash counts, vouchers, unverified "
                "loadings, blocked supplier invoices, draft entries, parent statements and party balances. Blockers are cleared or waived with a reason; "
                "a second person signs; a signed month can lock the books."),
              _("Bank, cash, trade and accounting records"), 'delivered', 'ei_close.ei_close_action', 'ei.close'),
            R('recon_centre', ctl, _("Reconciliation centre"), _("Does everything agree, and what is open since when?"),
              _("Every reconciliation (bank book to bank, receipts to invoices, party balances to the ledger, contracts to DAs, orders to invoices to "
                "lifting, supplier invoices, parent statements, cash, old system, FBR) with its open items, oldest age and last sign-off."),
              _("The reconciliation records themselves"), 'delivered', 'ei_close.ei_recon_centre_action', 'ei.close'),
            R('subledger', fin, _("Party balances against the control accounts"), _("Do customers' and suppliers' balances add up to the ledger?"),
              _("Posted items on receivable or payable accounts up to a date: the control total, the sum of party balances, items with no party, "
                "entries typed by hand on a control account, and parties whose balance runs the wrong way. Signed off by a second person."),
              _("Posted journal items"), 'delivered', 'ei_close.ei_subledger_action', 'ei.subledger.check'),
            R('quantity_trail', trade, _("Quantity trail"), _("For each DA line: promised, requested, supplier-invoiced, lifted, customer-invoiced?"),
              _("Each step counted from its own records: order requests, checked supplier invoices, verified loadings, invoiced loadings. "
                "Flags supplier-invoiced but not lifted, lifted without a supplier invoice, lifted but not invoiced to the customer, and lifted beyond the DA."),
              _("DA lines, supplier invoices, truck loadings"), 'delivered', 'ei_close.ei_trail_action', 'ei.da.line'),
        ]
