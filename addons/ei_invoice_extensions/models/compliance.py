import hashlib

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class EiComplianceAdapter(models.Model):
    _name = 'ei.compliance.adapter'
    _description = 'External service / compliance connector (availability badge)'
    _order = 'sequence, code'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    kind = fields.Selection([('fbr', 'FBR / PRAL e-invoicing'), ('bank', 'Bank feed'), ('ocr', 'OCR'),
                             ('messaging', 'WhatsApp / SMS'), ('parent_feed', 'Parent-company data feed'),
                             ('other', 'Other')], required=True)
    state = fields.Selection([('not_configured', 'Pending configuration'), ('sandbox', 'Sandbox'), ('live', 'Live')],
                             default='not_configured', required=True)
    implemented = fields.Boolean(readonly=True, help="True only if a connector is implemented AND tested against the provider.")
    last_success_at = fields.Datetime(readonly=True)
    last_error = fields.Char(readonly=True)
    notes = fields.Text()

    _code = models.Constraint('unique(code)', 'Adapter codes are unique.')

    def action_set_state(self, state):
        if not self.env.user.has_group('ei_invoice_extensions.group_ei_invoice_approver'):
            raise AccessError(_("Only an invoice approver can change a connector's environment."))
        self.write({'state': state})


class EiComplianceSubmission(models.Model):
    _name = 'ei.compliance.submission'
    _description = 'Idempotent submission of a document to an external authority'
    _inherit = ['mail.thread']
    _order = 'id desc'

    move_id = fields.Many2one('account.move', required=True, index=True, ondelete='restrict')
    adapter_id = fields.Many2one('ei.compliance.adapter', required=True)
    company_id = fields.Many2one(related='move_id.company_id', store=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    payload_hash = fields.Char(readonly=True)
    state = fields.Selection([('pending_configuration', 'Pending configuration'), ('failed', 'Failed - can retry'),
                              ('submitted', 'Submitted')], required=True, default='pending_configuration',
                             readonly=True, tracking=True)
    attempts = fields.Integer(readonly=True)
    last_error = fields.Char(readonly=True)
    external_ref = fields.Char(readonly=True)
    submitted_at = fields.Datetime(readonly=True)

    _key = models.Constraint('unique(idempotency_key)', 'A submission with this idempotency key already exists.')

    @api.model
    def submit(self, move, adapter_code):
        """Create-or-reuse the single submission for (move, adapter) and try to send it."""
        if move.state != 'posted':
            raise UserError(_("Only a posted invoice can be submitted."))
        adapter = self.env['ei.compliance.adapter'].search([('code', '=', adapter_code)], limit=1)
        if not adapter:
            raise UserError(_("Unknown connector %s.", adapter_code))
        key = '%s-%s-%s' % (move.company_id.id, move.id, adapter.code)
        sub = self.search([('idempotency_key', '=', key)])
        if not sub:
            sub = self.create({'move_id': move.id, 'adapter_id': adapter.id, 'idempotency_key': key,
                               'payload_hash': hashlib.sha256((move.name + str(move.amount_total)).encode()).hexdigest()})
        sub._send()
        return sub

    def _send(self):
        for s in self:
            if s.state == 'submitted':
                continue  # never send twice
            a = s.adapter_id
            if a.state == 'not_configured':
                s.write({'state': 'pending_configuration', 'last_error': _("Connector is not configured.")})
                continue
            sender = getattr(s, '_send_%s' % a.code, None)
            if sender is None:
                s.write({'state': 'failed', 'last_error': _("No connector is implemented for %s.", a.code),
                         'attempts': s.attempts + 1})
                a.sudo().write({'last_error': s.last_error})
                continue
            s.attempts += 1
            try:
                ref = sender()
            except Exception as e:  # recoverable: keep the record, record the reason, allow retry
                s.write({'state': 'failed', 'last_error': str(e)[:250]})
                a.sudo().write({'last_error': str(e)[:250]})
                continue
            s.write({'state': 'submitted', 'external_ref': ref, 'last_error': False,
                     'submitted_at': fields.Datetime.now()})
            a.sudo().write({'last_success_at': fields.Datetime.now(), 'last_error': False})

    def action_retry(self):
        self.filtered(lambda s: s.state != 'submitted')._send()


class AccountMove(models.Model):
    _inherit = 'account.move'

    ei_submission_ids = fields.One2many('ei.compliance.submission', 'move_id')

    def action_ei_submit_fbr(self):
        for m in self:
            self.env['ei.compliance.submission'].submit(m, 'fbr')
