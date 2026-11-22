"""Contract quantity (client, 22 Nov 2026): "the December contract is 500 MTL; 425 MTL is fed; 75 MTL remains".

A light record the operator sets from the feeding screen itself: a name (December 2026), the supplier, the buying entity and
the total MTL. DAs are linked to it; what is entered on them is counted against the total. Nothing is entered beyond the
total: a person with the right to exceed contract quantities raises the total first, with a reason that stays on the record.

The states are kept apart: entered (every coil on a live DA, drafts included), confirmed (approved DAs), sold (coils with a
Sold (OUT) customer), lifted (verified liftings). Only "entered" is limited by the total."""
from decimal import Decimal, ROUND_HALF_UP

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

LIVE_OUT = ('cancelled', 'amended')            # a cancelled DA, or one replaced by its amendment, no longer uses the quantity
CONFIRMED = ('approved', 'fulfilled', 'closed')


def q3(v):
    """MTL to 3 decimals, exactly (no floating-point dust in totals)."""
    return Decimal(str(v or 0)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


class EiFeedingQuota(models.Model):
    _name = 'ei.feeding.quota'
    _description = 'Contract quantity (total MTL to be fed)'
    _inherit = ['mail.thread']
    _order = 'state, id desc'

    name = fields.Char('Contract', required=True, tracking=True, help="As the client calls it, e.g. December 2026.")
    supplier_id = fields.Many2one('res.partner', string='Supplier', required=True, index=True, tracking=True)
    purchase_in_id = fields.Many2one('res.partner', string='Purchased By (IN)', index=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    total_mtl = fields.Float('Total (MTL)', digits=(16, 3), required=True, tracking=True)
    state = fields.Selection([('open', 'Open'), ('closed', 'Closed')], default='open', required=True, tracking=True)
    da_ids = fields.One2many('ei.da', 'quota_id', string='DAs')
    entered_mtl = fields.Float('Entered (MTL)', digits=(16, 3), compute='_compute_qty')
    remaining_mtl = fields.Float('Remaining to enter (MTL)', digits=(16, 3), compute='_compute_qty')
    confirmed_mtl = fields.Float('Confirmed (MTL)', digits=(16, 3), compute='_compute_qty')
    pending_mtl = fields.Float('Draft or waiting for approval (MTL)', digits=(16, 3), compute='_compute_qty')
    sold_mtl = fields.Float('Sold (MTL)', digits=(16, 3), compute='_compute_qty')
    lifted_mtl = fields.Float('Lifted (MTL)', digits=(16, 3), compute='_compute_qty')

    _total_positive = models.Constraint('CHECK(total_mtl > 0)', 'The total quantity must be more than zero.')

    def _live_das(self):
        das = self.da_ids.filtered(lambda d: d.state not in LIVE_OUT)
        return das - das.mapped('previous_id')            # an amendment counts once, not with the DA it replaces

    def figures(self):
        """Exact figures (Decimal, 3 decimals) of one contract quantity."""
        self.ensure_one()
        lines = self._live_das().mapped('line_ids')
        entered = sum((q3(l.mtl) for l in lines), Decimal(0))
        confirmed = sum((q3(l.mtl) for l in lines if l.da_id.state in CONFIRMED), Decimal(0))
        return {'total': q3(self.total_mtl), 'entered': entered, 'remaining': q3(self.total_mtl) - entered,
                'confirmed': confirmed, 'pending': entered - confirmed,
                'sold': sum((q3(l.mtl) for l in lines if l.customer_id), Decimal(0)),
                'lifted': sum((q3(l.lifted_mtl) for l in lines), Decimal(0))}

    @api.depends('total_mtl', 'da_ids.state', 'da_ids.line_ids.mtl', 'da_ids.line_ids.customer_id')
    def _compute_qty(self):
        for q in self:
            f = q.figures() if q.id else {k: Decimal(0) for k in ('entered', 'remaining', 'confirmed', 'pending', 'sold', 'lifted')}
            q.entered_mtl, q.remaining_mtl, q.confirmed_mtl = float(f['entered']), float(f['remaining']), float(f['confirmed'])
            q.pending_mtl, q.sold_mtl, q.lifted_mtl = float(f['pending']), float(f['sold']), float(f['lifted'])

    def _lock(self):
        """Take the record for this transaction. An UPDATE (not only a read lock): a second person saving against the same
        contract at the same moment waits, then gets a serialization error and Odoo retries the request with fresh totals,
        so the same quantity is never used twice."""
        if self.ids:
            self.env.cr.execute('UPDATE ei_feeding_quota SET write_date = write_date WHERE id IN %s', (tuple(self.ids),))

    def _check_room(self):
        """Called after coils change: the entered quantity may not exceed the total."""
        self._lock()
        for q in self:
            q.invalidate_recordset()
            f = q.figures()
            if f['entered'] > f['total']:
                raise UserError(_("Contract %(c)s is %(t)s MTL. With these coils %(e)s MTL would be entered: %(o)s MTL more than the "
                                  "total. Correct the weights, or a person with the right to exceed contract quantities raises the total "
                                  "first, with a reason.", c=q.name, t=f['total'], e=f['entered'], o=f['entered'] - f['total']))

    @api.model
    def can_adjust(self):
        u = self.env.user
        return u.has_group('ei_contract_da.group_ei_da_override') or u.has_group('ei_contract_da.group_ei_contract_approver')

    def write(self, vals):
        if 'total_mtl' in vals and not self.env.context.get('ei_quota_new'):
            reason = (self.env.context.get('ei_quota_reason') or '').strip()
            for q in self:
                if q.da_ids and q3(vals['total_mtl']) != q3(q.total_mtl):
                    if not self.can_adjust():
                        raise AccessError(_("Only a person with the right to exceed contract quantities (or a contract approver) changes "
                                            "the total of a contract that already has entries."))
                    if not reason:
                        raise UserError(_("Write why the total of %s changes.", q.name))
            self._lock()
        res = super().write(vals)
        if 'total_mtl' in vals:
            for q in self:
                f = q.figures()
                if f['total'] < f['entered']:
                    raise UserError(_("%(c)s already has %(e)s MTL entered; the total cannot be less.", c=q.name, e=f['entered']))
                if self.env.context.get('ei_quota_reason'):
                    q.message_post(body=_("Total changed to %(t)s MTL by %(u)s. Reason: %(r)s",
                                          t=f['total'], u=self.env.user.name, r=self.env.context['ei_quota_reason']))
        return res

    def unlink(self):
        if self.mapped('da_ids'):
            raise UserError(_("A contract quantity with DAs is closed, not deleted."))
        return super().unlink()

    def summary(self):
        self.ensure_one()
        f = self.figures()
        return {'id': self.id, 'name': self.name, 'state': self.state, 'supplier': self.supplier_id.display_name,
                'purchase_in': self.purchase_in_id.display_name or '', 'can_adjust': self.can_adjust(),
                **{k: str(v) for k, v in f.items()}}


class EiDa(models.Model):
    _inherit = 'ei.da'

    quota_id = fields.Many2one('ei.feeding.quota', string='Contract quantity', index=True, tracking=True, ondelete='restrict',
                               help="The contract total this DA counts against (e.g. December 2026, 500 MTL).")

    @api.constrains('quota_id', 'state')
    def _check_quota_room(self):
        self.mapped('quota_id')._check_room()


class EiDaLine(models.Model):
    _inherit = 'ei.da.line'

    @api.constrains('mtl', 'da_id')
    def _check_quota_room(self):
        self.mapped('da_id.quota_id')._check_room()
