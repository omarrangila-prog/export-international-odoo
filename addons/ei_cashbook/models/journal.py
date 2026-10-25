from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    ei_custodian_id = fields.Many2one('res.users', string='Cash custodian',
                                      help="Person accountable for this cash box / safe.")
    ei_self_approve_limit = fields.Monetary(
        'Self-approval limit', currency_field='currency_id', default=0.0,
        help="Vouchers up to this amount may be approved by their own maker. 0 = a second person always approves.")
    ei_receipt_required_over = fields.Monetary(
        'Receipt attachment required over', currency_field='currency_id', default=0.0,
        help="Payment vouchers above this amount need an attached receipt. 0 = always required.")
