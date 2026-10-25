from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

LC_SHEET = 'IMPORT PUR SALE'


class EiTradeLc(models.Model):
    _name = 'ei.trade.lc'
    _description = 'LC / import trade record'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char('LC / trade name', required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    legacy_code_ids = fields.Many2many('ei.legacy.code', string='Legacy codes (16.xx)',
                                       domain="[('source_sheet_key', '=', 'IMPORT PUR SALE')]")
    lc_reference = fields.Char('LC number', tracking=True, help="From the bank's LC advice - never guessed from the legacy name.")
    purchase_code_id = fields.Many2one('ei.legacy.code', string='Purchase-side code')
    sale_code_ids = fields.Many2many('ei.legacy.code', 'ei_trade_lc_sale_code_rel', 'lc_id', 'code_id', string='Sale-side codes')
    bank_journal_id = fields.Many2one('account.journal', domain="[('type', '=', 'bank')]")
    supplier_id = fields.Many2one('res.partner')
    shipment_ref = fields.Char()
    expiry_date = fields.Date(tracking=True)
    quantity_mtl = fields.Float(digits=(16, 3))
    lc_amount = fields.Monetary(currency_field='currency_id')
    cost_ids = fields.One2many('ei.trade.lc.cost', 'lc_id')
    total_costs = fields.Monetary(compute='_compute_costs', currency_field='currency_id')
    outstanding_liability = fields.Monetary(tracking=True, currency_field='currency_id',
                                            help="Entered from the bank's confirmation; not computed or posted by this module.")
    state = fields.Selection([('unverified', 'Unverified (legacy reference only)'), ('verified', 'Verified against source records'),
                              ('closed', 'Closed')], default='unverified', readonly=True, tracking=True, index=True)
    verified_by = fields.Many2one('res.users', readonly=True)
    verified_at = fields.Datetime(readonly=True)
    settlement_enabled = fields.Boolean(compute='_compute_settlement_enabled')
    notes = fields.Text()

    @api.depends('cost_ids.amount')
    def _compute_costs(self):
        for r in self:
            r.total_costs = sum(r.cost_ids.mapped('amount'))

    def _compute_settlement_enabled(self):
        flag = self.env['ir.config_parameter'].sudo().get_bool('ei_trade_lc.settlement_signed_off', False)
        for r in self:
            r.settlement_enabled = flag

    @api.constrains('legacy_code_ids')
    def _check_sheet(self):
        for r in self:
            bad = r.legacy_code_ids.filtered(lambda c: c.source_sheet_key != LC_SHEET)
            if bad:
                raise UserError(_("Code %s is not an LC / import reference.", bad[0].legacy_code))

    # ---------------------------------------------------------------- seeding
    @api.model
    def seed_from_legacy(self):
        """One record per legacy 16.xx code that is not yet on any LC record. Idempotent; nothing is merged or inferred."""
        if not self.env.user.has_group('ei_trade_lc.group_ei_trade_manager'):
            raise AccessError(_("Only a trade manager can seed the register."))
        codes = self.env['ei.legacy.code'].search([('source_sheet_key', '=', LC_SHEET), ('company_id', '=', self.env.company.id)])
        taken = self.search([('company_id', '=', self.env.company.id)]).legacy_code_ids
        todo = codes - taken
        for c in todo:
            self.create({'name': '%s %s' % (c.legacy_code, c.original_name), 'legacy_code_ids': [(6, 0, c.ids)]})
        return len(todo)

    def action_group(self):
        """Merge selected unverified records into the first (e.g. an LC and its sales codes)."""
        if not self.env.user.has_group('ei_trade_lc.group_ei_trade_manager'):
            raise AccessError(_("Only a trade manager can group LC records."))
        if len(self) < 2 or any(r.state != 'unverified' for r in self):
            raise UserError(_("Select two or more unverified records."))
        main = self[0]
        main.legacy_code_ids |= self[1:].legacy_code_ids
        self[1:].unlink()
        return main

    def action_verify(self):
        if not self.env.user.has_group('ei_trade_lc.group_ei_trade_manager'):
            raise AccessError(_("Only a trade manager can verify."))
        for r in self:
            if not (r.lc_reference and r.bank_journal_id and r.lc_amount and r.currency_id):
                raise UserError(_("Verification needs the LC number, bank, currency and amount from the bank's records."))
            if r.create_uid == self.env.user and not self.env.su:
                raise AccessError(_("Maker-checker: you cannot verify a record you created."))
            r.write({'state': 'verified', 'verified_by': self.env.user.id, 'verified_at': fields.Datetime.now()})

    def action_settle(self):
        """Gated: LC settlement accounting is not defined by the source documents."""
        raise UserError(_("LC settlement is disabled until the trade-finance accounting treatment is signed off by the "
                          "accountant. The register only records facts; it posts nothing."))

    def unlink(self):
        if any(r.state != 'unverified' for r in self):
            raise UserError(_("Only unverified records can be deleted."))
        return super().unlink()


class EiTradeLcCost(models.Model):
    _name = 'ei.trade.lc.cost'
    _description = 'LC cost line (information only)'

    lc_id = fields.Many2one('ei.trade.lc', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='lc_id.currency_id')
    name = fields.Char(required=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')


class EiLegacyCode(models.Model):
    _inherit = 'ei.legacy.code'

    trade_lc_ids = fields.Many2many('ei.trade.lc', string='LC records')
