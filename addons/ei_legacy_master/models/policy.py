"""Two client decisions shared by every Export International workflow (final handoff, 9 Nov 2026):

1. Routine business approval is OFF by default. An administrator can switch on "Require approval" per workflow; a person
   may also tick "Send for review" on one record. Neither replaces security: access rights, record rules, posting rights,
   duplicate checks, the customer-code check and lock dates apply whatever the policy says.
2. New business entries use only PKR (11 Nov 2026). Other currencies already on old records are left untouched."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError

FLOWS = {
    'contract': "Contracts",
    'da': "Delivery advices (DA)",
    'order': "Daily order requests",
    'cash': "Cash vouchers",
    'lifting': "Truck loadings (lifting)",
    'daybook': "Online feeding and cash book entries",
}
ALLOWED_CURRENCIES = ('PKR',)          # PKR only (client, 11 Nov 2026; USD was allowed 9-10 Nov)


class EiApprovalPolicy(models.AbstractModel):
    _name = 'ei.approval.policy'
    _description = 'Optional approval policy'

    @api.model
    def flow_on(self, flow):
        return self.env['ir.config_parameter'].sudo().get_bool('ei_approval.%s' % flow, False)

    @api.model
    def set_all(self, value):
        """For administrators and tests: switch every workflow's approval on or off."""
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only an administrator can change the approval policy."))
        for flow in FLOWS:
            self.env['ir.config_parameter'].sudo().set_bool('ei_approval.%s' % flow, bool(value))
        return True

    @api.model
    def summary(self):
        return [{'flow': f, 'label': l, 'on': self.flow_on(f)} for f, l in FLOWS.items()]


class EiReviewOptionMixin(models.AbstractModel):
    _name = 'ei.review.option.mixin'
    _description = 'Optional "Send for review" on one record'
    _ei_flow = None

    review_requested = fields.Boolean('Send for review', copy=False,
                                      help="Tick to have someone else check this record before it is confirmed. "
                                           "Off by default; routine entries are confirmed by the person who enters them.")
    approval_mode = fields.Selection([('direct', 'Confirmed by the person entering it'), ('review', 'Checked by a second person')],
                                     compute='_compute_approval_mode', string='Approval')

    def _approval_required(self):
        """True when this record must wait for a second person: the workflow's policy is on, or the record asks for it."""
        policy = self.env['ei.approval.policy'].flow_on(self._ei_flow)
        return policy or any(self.mapped('review_requested'))

    @api.depends('review_requested')
    def _compute_approval_mode(self):
        policy = self.env['ei.approval.policy'].flow_on(self._ei_flow)
        for r in self:
            r.approval_mode = 'review' if policy or r.review_requested else 'direct'


class EiTwoCurrencyMixin(models.AbstractModel):
    _name = 'ei.two.currency.mixin'
    _description = 'New entries in PKR only'

    @api.model
    def _ei_currency_domain(self):
        return [('name', 'in', ALLOWED_CURRENCIES)]

    def _ei_check_new_currency(self, vals):
        if self.env.context.get('ei_keep_currency'):          # a revision of an older record keeps that record's currency
            return
        cid = vals.get('currency_id')
        if cid:
            cur = self.env['res.currency'].browse(cid)
            if cur.name not in ALLOWED_CURRENCIES:
                raise UserError(_("New entries are in PKR only (got %s).", cur.name))

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            self._ei_check_new_currency(v)
        return super().create(vals_list)

    def write(self, vals):
        self._ei_check_new_currency(vals)
        return super().write(vals)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ei_approval_contract = fields.Boolean("Require approval: contracts", config_parameter='ei_approval.contract')
    ei_approval_da = fields.Boolean("Require approval: delivery advices", config_parameter='ei_approval.da')
    ei_approval_order = fields.Boolean("Require approval: daily order requests", config_parameter='ei_approval.order')
    ei_approval_cash = fields.Boolean("Require approval: cash vouchers", config_parameter='ei_approval.cash')
    ei_approval_lifting = fields.Boolean("Require approval: truck loadings", config_parameter='ei_approval.lifting')
