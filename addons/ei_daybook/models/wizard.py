"""Print the day book of a date (or a range): the balances brought forward first, apart, then the day's entries with their Dr and Cr
codes, then the totals. Counted from the saved entries only; approved entries by default (drafts can be included, marked)."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .entry import KINDS


class EiDaybookPrint(models.TransientModel):
    _name = 'ei.daybook.print'
    _description = 'Print the day book'

    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    kind = fields.Selection([('all', 'Online feeding and cash book')] + [k for k in KINDS if k[0] != 'opening'], default='all', required=True,
                            string='Which book')
    include_waiting = fields.Boolean('Include drafts and entries waiting for approval', help="They are marked as not approved.")

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for w in self:
            if w.date_to < w.date_from:
                raise UserError(_("The end date is before the start date."))

    def _entries(self):
        self.ensure_one()
        states = ['approved', 'reversed'] + (['draft', 'submitted'] if self.include_waiting else [])
        dom = [('date', '>=', self.date_from), ('date', '<=', self.date_to), ('state', 'in', states)]
        if self.kind == 'online':
            dom.append(('kind', '=', 'online'))
        elif self.kind == 'cash':
            dom.append(('kind', 'in', ('cash', 'opening')))
        return self.env['ei.daybook.entry'].search(dom, order='date, kind desc, id')

    def report_data(self):
        """Everything the printed page shows, also used by the tests (the page and the numbers come from one place)."""
        self.ensure_one()
        es = self._entries()
        opening = es.filtered(lambda e: e.kind == 'opening')
        moves = es - opening
        return {
            'opening': opening, 'moves': moves,
            'opening_total': sum(opening.mapped('amount')),
            'debit_total': sum(moves.filtered('debit_code_id').mapped('amount')),
            'credit_total': sum(moves.filtered('credit_code_id').mapped('amount')),
            'title': _("Day book %(f)s%(t)s", f=self.date_from.strftime('%d/%m/%Y'),
                       t='' if self.date_to == self.date_from else ' - ' + self.date_to.strftime('%d/%m/%Y')),
            'book': dict(self._fields['kind'].selection)[self.kind],
        }

    def action_print(self):
        self.ensure_one()
        return self.env.ref('ei_daybook.action_report_daybook').report_action(self)
