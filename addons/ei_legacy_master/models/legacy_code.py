from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

TARGET_TYPES = [
    ('res_partner', 'Customer / supplier contact'),
    ('gl_account', 'Accounting account'),
    ('bank_journal', 'Bank account'),
    ('cash_journal', 'Cash box'),
    ('suspense_account', 'Holding account (suspense)'),
    ('analytic', 'Cost centre'),
    ('trade_lc', 'LC / import record'),
    ('legacy_ref_only', 'Just keep as a reference'),
]

# Heuristic first guess per legacy sheet. It is only a PROPOSAL; nothing is created from it.
SHEET_PROPOSAL = {
    'CUSTOMER': 'res_partner',
    'BANK': 'bank_journal',
    'FOR PURCHASE': 'gl_account',
    'PROFIT & LOSS': 'gl_account',
    'EXPENSES': 'gl_account',
    'IMPORT PUR SALE': 'trade_lc',
}
# Name keywords that mean "a human must classify this, it is probably not what its sheet implies".
EXCEPTION_KEYWORDS = ('SUSPENSE', 'SUSPECTED', 'FRAUD')
CASH_KEYWORDS = ('SAFE',)
REVIEW_KEYWORDS = ('EXPENSES', 'INVESMENT', 'INV A/C', 'INV. A/C', 'GST', 'SERVICE CHARGES', 'DOWN PAYMENT',
                   'SECURITY', 'EXCH AC')

RAW_FIELDS = ('legacy_code', 'source_sheet', 'source_sheet_key', 'source_row', 'original_name', 'nickname',
              'batch_id', 'company_id')


class EiLegacyCode(models.Model):
    _name = 'ei.legacy.code'
    _description = 'Legacy code (raw reference + mapping)'
    _inherit = ['mail.thread']
    _order = 'source_sheet_key, source_row'
    _rec_name = 'display_name'

    _legacy_uniq = models.Constraint(
        'unique(company_id, source_sheet_key, legacy_code)',
        'This legacy code already exists for this company and source sheet.')

    # ---- raw, immutable provenance
    legacy_code = fields.Char(required=True, readonly=True, index=True,
                              help="Displayed two-decimal text exactly as in the source (4.20, never 4.2).")
    source_sheet = fields.Char(readonly=True, help="Original sheet name, trailing spaces preserved.")
    source_sheet_key = fields.Char('Source sheet', readonly=True, index=True)
    source_row = fields.Integer('Excel row', readonly=True)
    original_name = fields.Char('Original NAME', required=True, readonly=True, index=True)
    nickname = fields.Char('Original NICK', readonly=True, index=True,
                           help="Not unique and may be empty; never used as an identifier.")
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True,
                                 default=lambda s: s.env.company)
    batch_id = fields.Many2one('ei.import.batch', 'First imported in', required=True, readonly=True,
                               ondelete='restrict', index=True)
    last_batch_id = fields.Many2one('ei.import.batch', 'Last seen in', readonly=True)
    last_sync = fields.Datetime(readonly=True)
    file_sha256 = fields.Char('Source file SHA-256', related='batch_id.file_sha256')
    batch_signed = fields.Boolean(compute='_compute_batch_signed', store=True)

    # ---- mapping (editable only through the controlled actions)
    proposed_target_type = fields.Selection(TARGET_TYPES, readonly=True, tracking=True)
    proposal_reason = fields.Char(readonly=True)
    approved_target_type = fields.Selection(TARGET_TYPES, readonly=True, tracking=True)
    verification_status = fields.Selection([
        ('unverified', 'Unverified'),
        ('proposed', 'Proposed'),
        ('needs_review', 'A person must decide'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], required=True, default='unverified', readonly=True, index=True, tracking=True)
    is_exception = fields.Boolean('Exception reference', readonly=True,
                                  help="Suspense, cash or suspected account: must never be imported blindly as a live bank.")
    approval_note = fields.Text(readonly=True)
    linked_model = fields.Char('Linked Odoo model', readonly=True)
    linked_res_id = fields.Integer('Linked record id', readonly=True)
    verified_by = fields.Many2one('res.users', readonly=True)
    verified_at = fields.Datetime(readonly=True)
    notes = fields.Text()

    @api.depends('batch_id.state')
    def _compute_batch_signed(self):
        for r in self:
            r.batch_signed = r.batch_id.state == 'signed'

    @api.depends('legacy_code', 'original_name')
    def _compute_display_name(self):
        for r in self:
            r.display_name = '%s %s' % (r.legacy_code, r.original_name)

    # --------------------------------------------------------------- creation
    @api.model
    def _classify(self, sheet_key, name):
        up = name.upper()
        if any(k in up for k in EXCEPTION_KEYWORDS):
            return 'suspense_account', 'needs_review', True, 'Name indicates a suspense/suspected account'
        if any(k == up.strip() for k in CASH_KEYWORDS):
            return 'cash_journal', 'needs_review', True, 'Looks like cash/safe, not a bank'
        proposal = SHEET_PROPOSAL.get(sheet_key, 'legacy_ref_only')
        if any(k in up for k in REVIEW_KEYWORDS):
            return proposal, 'needs_review', False, 'Name suggests this is not a plain %s' % sheet_key.title()
        return proposal, 'proposed', False, 'Default for sheet %s' % sheet_key

    @api.model
    def _values_from_row(self, row, batch):
        proposal, status, exc, reason = self._classify(row['sheet_key'], row['name'])
        return {
            'legacy_code': row['code'], 'source_sheet': row['sheet'], 'source_sheet_key': row['sheet_key'],
            'source_row': row['row'], 'original_name': row['name'], 'nickname': row['nick'] or False,
            'company_id': batch.company_id.id, 'batch_id': batch.id, 'last_batch_id': batch.id,
            'last_sync': fields.Datetime.now(),
            'proposed_target_type': proposal, 'verification_status': status,
            'is_exception': exc, 'proposal_reason': reason,
        }

    # ---------------------------------------------------------- immutability
    def write(self, vals):
        if not self.env.context.get('ei_system_write'):
            locked = set(vals) & set(RAW_FIELDS)
            if locked:
                raise UserError(_("Raw imported fields are read-only (%s). Re-import to log a diff, "
                                  "or remap through the approval workflow.", ', '.join(sorted(locked))))
            # mapping fields may only change through the actions below
            if set(vals) & {'approved_target_type', 'verification_status', 'verified_by', 'verified_at',
                            'linked_model', 'linked_res_id', 'approval_note', 'proposed_target_type'}:
                raise UserError(_("Mappings are changed only with Approve / Reject / Reopen."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise UserError(_("Legacy codes are an audit record and cannot be deleted."))
        return super().unlink()

    # -------------------------------------------------------------- workflow
    def _check_approver(self):
        if not self.env.user.has_group('ei_legacy_master.group_ei_mapping_approver'):
            raise AccessError(_("Only a mapping approver can change a mapping decision."))
        enforce = self.env['ir.config_parameter'].sudo().get_bool('ei_legacy_master.enforce_maker_checker', True)
        if enforce and not self.env.su:
            own = self.filtered(lambda r: r.batch_id.imported_by == self.env.user)
            if own:
                raise AccessError(_("Maker-checker: you imported batch %s and cannot approve its mappings.",
                                    own[0].batch_id.name))

    def action_approve(self, target_type=None, note=None):
        """Record an accountant decision. Creates NO Odoo master record; it only records intent."""
        self._check_approver()
        for r in self:
            target = target_type or r.env.context.get('ei_target_type') or r.approved_target_type or r.proposed_target_type
            if not target:
                raise UserError(_("Choose the approved target type for %s.", r.legacy_code))
            if r.is_exception and target in ('bank_journal', 'res_partner'):
                raise UserError(_("%(code)s %(name)s is an exception reference (suspense/cash/suspected) and cannot "
                                  "be approved as a live %(t)s.", code=r.legacy_code, name=r.original_name, t=target))
            if r.is_exception and not (note or r.approval_note):
                raise UserError(_("Exception reference %s needs an explanatory approval note.", r.legacy_code))
            r.with_context(ei_system_write=True).write({
                'approved_target_type': target, 'verification_status': 'approved',
                'verified_by': self.env.user.id, 'verified_at': fields.Datetime.now(),
                'approval_note': note or r.approval_note,
            })

    def action_reject(self, note=None):
        self._check_approver()
        for r in self:
            r.with_context(ei_system_write=True).write({
                'verification_status': 'rejected', 'approved_target_type': False,
                'verified_by': self.env.user.id, 'verified_at': fields.Datetime.now(),
                'approval_note': note or r.approval_note,
            })

    def action_reopen(self):
        self._check_approver()
        for r in self:
            r.with_context(ei_system_write=True).write({
                'verification_status': 'needs_review' if r.is_exception else 'proposed',
                'approved_target_type': False, 'verified_by': False, 'verified_at': False,
            })
