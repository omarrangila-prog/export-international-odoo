from odoo import models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _ei_ledger_balance(self, date, inclusive=True):
        """Posted ledger balance of the journal's liquidity account up to `date` (aggregate only)."""
        self.ensure_one()
        if not self.default_account_id:
            return 0.0
        op = '<=' if inclusive else '<'
        data = self.env['account.move.line'].sudo()._read_group(
            [('account_id', '=', self.default_account_id.id), ('company_id', '=', self.company_id.id),
             ('parent_state', '=', 'posted'), ('date', op, date)], [], ['balance:sum'])
        return data[0][0] or 0.0
