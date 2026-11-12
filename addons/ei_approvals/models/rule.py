"""Who checks what. A rule says, for one kind of document (and optionally one company and an amount from which it applies), which
people may check it, whether a named person should get it first, how long it may wait, and who hears about it when it waits too long.

The rule never widens anybody's rights: a checker must ALSO hold the role the document itself demands (a DA is only ever approved by
someone with the contract-approver role), and is never the person who entered it."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError

FLOW_SELECTION = [('contract', "Contract"), ('da', "Delivery advice (DA)"), ('order', "Daily order request"),
                  ('cash', "Cash voucher"), ('lifting', "Truck loading"),
                  ('bank', "Bank statement"), ('intake', "Supplier invoice mismatch"), ('recon', "Parent statement sign-off"),
                  ('cashcount', "Daily cash count"), ('formula', "Rate formula"), ('close', "Day / month-end close"),
                  ('daybook', "Online / cash book entry")]


class EiApprovalRule(models.Model):
    _name = 'ei.approval.rule'
    _description = 'Approval rule'
    _order = 'flow, company_id, min_amount desc, sequence, id'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)
    flow = fields.Selection(FLOW_SELECTION, string='Document', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', tracking=True,
                                 help="Leave empty to use this rule in every company.")
    maker_group_id = fields.Many2one('res.groups', string='Maker role', tracking=True,
                                     help="Only for entries made by people with this role. Empty: anyone who may enter the document.")
    approver_group_id = fields.Many2one('res.groups', string='Checker role', tracking=True,
                                        help="People with this role may check. They must also hold the role the document itself needs.")
    approver_user_ids = fields.Many2many('res.users', 'ei_approval_rule_user_rel', 'rule_id', 'user_id', string='Named checkers',
                                         domain=[('share', '=', False)], tracking=True,
                                         help="When filled, only these people check (in this order of preference, the least busy first). "
                                              "They still need the document's own role.")
    min_amount = fields.Monetary('Applies from amount', currency_field='currency_id', tracking=True,
                                 help="0 = every amount. The rule with the highest starting amount that the document reaches is used.")
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    approvals_needed = fields.Selection([('1', "One checker")], default='1', required=True, string='Checkers needed',
                                        help="One checker, as the client asked. More than one needs the client's written policy first.")
    due_hours = fields.Integer('Overdue after (hours)', default=48, tracking=True)
    escalate_group_id = fields.Many2one('res.groups', string='Tell when overdue', tracking=True,
                                        default=lambda s: s.env.ref('ei_management_dashboard.group_ei_management', raise_if_not_found=False))
    note = fields.Text()

    @api.constrains('due_hours', 'min_amount')
    def _check_numbers(self):
        for r in self:
            if r.due_hours < 1:
                raise UserError(_("A request needs at least one hour before it counts as overdue."))
            if r.min_amount < 0:
                raise UserError(_("The starting amount cannot be negative."))

    @api.model
    def _for(self, flow, company, amount, maker):
        """The rule for one document: same kind, this company or every company, maker role if set, highest starting amount reached."""
        rules = self.sudo().search([('flow', '=', flow), ('company_id', 'in', [company.id, False])])
        rules = rules.filtered(lambda r: (not r.maker_group_id or r.maker_group_id in maker.sudo().all_group_ids)
                                         and (amount or 0) + 1e-9 >= r.min_amount)
        if not rules:
            return self.browse()
        return rules.sorted(lambda r: (bool(r.company_id), r.min_amount, -r.sequence), reverse=True)[0]
