"""The DA Feeding Desk: one screen for practice (never posts) and for real entry (draft -> review -> approval).

Every number on the screen comes from here, worked out again on the server from what was typed. Practice writes
NOTHING to the database. Real entry writes only draft DA lines, through the DA's own rules and permissions."""
import base64
import re
from datetime import datetime

import pytz
from decimal import Decimal, InvalidOperation

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from . import feeding_engine as fe
from .da import name_tokens

LAB_FORMULA = 'ISL_ASML_DEALER_NET'
# Practice inputs: the numbers written on the client's sample DA (training only) and the rates of Daily Working Tasks pp.3-5
LAB_DEFAULTS = {'basic_rate': '229500', 'weight_kg': '4574.00', 'cn_amount': '1000', 'direct_purchase': '229500', 'direct_sale': '230500',
                'params': {'sales_tax_pct': '18', 'additional_pct': '0.1', 'commission_pct': '1.32', 'cn_commission_pct': '1.32'},
                'offsets': {k: str(v[2]) for k, v in fe.METHODS.items() if v[2] is not None}}
SMALL_KG = 100           # a coil lighter than this is almost always tons typed into kg (4.574 kg vs 4,574 kg): confirm first
SHEETS = {'customer': 'CUSTOMER', 'trade': 'FOR PURCHASE', 'pl': 'PROFIT & LOSS'}
DIMS = re.compile(r'(?<![0-9.])(\d*\.\d+|\d+)\s*[xX\u00d7]\s*(\d+(?:\.\d+)?)')


def item_dims(name):
    """'GI COIL 0.50X1219 PRIME' -> (Decimal('0.50'), Decimal('1219')); None when the name carries no size."""
    m = DIMS.search(name or '')
    return (Decimal(m.group(1)), Decimal(m.group(2))) if m else None


def dims_problem(item_name, thickness, width):
    """Plain words when the typed thickness / width disagree with the size in the item's name (old system: a stale size could stay
    on screen after the item was changed). Empty when they agree or the name carries no size."""
    d = item_dims(item_name)
    if not d:
        return ''
    bad = []
    for typed, want, label in ((thickness, d[0], _("thickness")), (width, d[1], _("width"))):
        if typed in (None, '', False):
            continue
        try:
            if Decimal(str(typed).strip()) != want:
                bad.append(_("%(l)s %(t)s", l=label, t=typed))
        except InvalidOperation:
            bad.append(_("%(l)s %(t)r is not a number", l=label, t=typed))
    if bad:
        return _("The item is %(i)s (%(a)s x %(b)s), but %(x)s is typed. Correct it, or choose the right item.",
                 i=item_name, a=d[0], b=d[1], x=_(" and ").join(bad))
    return ''


def num(v, what):
    if v in (None, ''):
        return None
    try:
        return Decimal(str(v).replace(',', '').strip())
    except InvalidOperation:
        raise UserError(_("%(w)s: %(v)r is not a number.", w=what, v=v))


def out(r):
    """Decimals -> strings for the screen (exact; the screen only formats)."""
    if isinstance(r, dict):
        return {k: out(v) for k, v in r.items()}
    if isinstance(r, list):
        return [out(v) for v in r]
    return str(r) if isinstance(r, Decimal) else r


def local_to_utc(env, text):
    """'2026-11-06 16:03' typed in the person's own time zone (Asia/Karachi) -> naive UTC for Odoo."""
    if not text:
        return False
    text = text.replace('T', ' ')[:16]
    try:
        naive = datetime.strptime(text, '%Y-%m-%d %H:%M')
    except ValueError:
        raise UserError(_("Order date and time: %r is not like 2026-11-06 16:03.", text))
    tz = pytz.timezone(env.user.tz or env.context.get('tz') or 'Asia/Karachi')
    return tz.localize(naive).astimezone(pytz.utc).replace(tzinfo=None)


class EiFeedingDesk(models.AbstractModel):
    _name = 'ei.feeding.desk'
    _description = 'DA feeding desk'

    # ------------------------------------------------------------------ catalogue
    @api.model
    def methods(self):
        return [{'key': k, 'label': v[0], 'basis': v[1], 'why': v[3], 'ready': v[1] != 'blocked'} for k, v in fe.METHODS.items()]

    # ------------------------------------------------------------------ practice (never writes)
    @api.model
    def lab(self, inputs=None):
        inputs = dict(LAB_DEFAULTS, **(inputs or {}))
        f = self.env['ei.formula.definition'].search([('code', '=', LAB_FORMULA)], order='version desc', limit=1)
        params = dict(LAB_DEFAULTS['params'], **(inputs.get('params') or {}))
        offsets = dict(LAB_DEFAULTS['offsets'], **(inputs.get('offsets') or {}))
        qty = fe.tons_from_kg(num(inputs['weight_kg'], _("Weight")) or 0)
        cards = []
        for key, (label, basis, _d, why) in fe.METHODS.items():
            card = {'key': key, 'label': label, 'why': why, 'basis': basis}
            try:
                if basis == 'blocked':
                    raise fe.FeedingError(why)
                if basis == 'direct':
                    r = fe.feed(key, qty, purchase_rate=num(inputs['direct_purchase'], _("Direct purchase")),
                                sale_rate=num(inputs['direct_sale'], _("Direct sale")))
                else:
                    if not f:
                        raise fe.FeedingError(_("The %s formula is not installed.") % LAB_FORMULA)
                    r = fe.feed(key, qty, f._steps(), f.rounding_mode, num(inputs['basic_rate'], _("Basic rate")),
                                {k: num(v, k) for k, v in params.items()}, num(offsets.get(key), label) or 0,
                                cn_amount=num(inputs['cn_amount'], _("CN")) if basis == 'with_cn' else None)
                card.update(out(r), ok=True)
            except fe.FeedingError as e:
                card.update(ok=False, error=str(e))
            cards.append(card)
        return {'inputs': inputs, 'quantity': str(qty), 'cards': cards,
                'formula': f and {'code': f.code, 'version': f.version, 'state': f.state,
                                  'state_label': dict(f._fields['state'].selection).get(f.state)},
                'note': _("Practice only. Nothing here is saved or posted: no invoice, no stock, no journal entry.")}

    # ------------------------------------------------------------------ real entry
    def _da(self, da_id, write=False):
        d = self.env['ei.da'].browse(int(da_id)).exists()
        if not d:
            raise UserError(_("This DA no longer exists."))
        d.check_access('write' if write else 'read')
        if write and d.state != 'draft':
            raise UserError(_("DA %s is no longer a draft; amend it instead.", d.name))
        return d

    @api.model
    def da_list(self):
        DA = self.env['ei.da']
        if not DA.has_access('read'):
            raise AccessError(_("Your role cannot see delivery advices."))
        rows = DA.search([('state', 'in', ('draft', 'under_review'))], order='write_date desc', limit=60)
        return {'rows': [{'id': d.id, 'name': d.name, 'parent': d.parent_partner_id.name, 'state': d.state,
                          'state_label': dict(d._fields['state'].selection).get(d.state), 'date': fields.Date.to_string(d.date),
                          'printed': d.printed_customer or '', 'coils': len(d.line_ids), 'mtl': d.total_mtl} for d in rows],
                'can_create': DA.has_access('create'),
                # new entries are in PKR only (client, 11 Nov 2026); signed contracts stay available under "More"
                'contracts': [{'id': c.id, 'name': '%s - %s (%s)' % (c.name, c.contract_ref, c.parent_partner_id.name),
                               'parent_id': c.parent_partner_id.id, 'currency': c.currency_id.name}
                              for c in self.env['ei.contract'].search([('state', '=', 'active'), ('contract_type', '!=', 'feeding'),
                                                                       ('currency_id.name', '=', 'PKR')], limit=200)],
                'suppliers': self._parties('ei_is_supplier_mill'), 'purchase_ins': self._parties('ei_is_purchase_in'),
                # practice (sample numbers, nothing saved) is for training copies only; the client's screens show the real entry alone
                'show_practice': self.env['ir.config_parameter'].sudo().get_bool('ei_da_feeding.show_practice', False),
                'can_delete': DA.has_access('unlink')}

    def _parties(self, flag):
        P = self.env['res.partner']
        return [{'id': p.id, 'name': p.display_name} for p in P.search([(flag, '=', True)], order='name')] if P.has_access('read') else []

    @api.model
    def da_find(self, name):
        """DAs already in the system with this number (any supplier), so the screen can offer to open one instead of
        making a second copy of the same paper."""
        name = (name or '').strip()
        if not name:
            return []
        rows = self.env['ei.da'].search([('name', '=ilike', name), ('state', '!=', 'cancelled')], order='id desc', limit=10)
        return [{'id': d.id, 'name': d.name, 'state': d.state, 'state_label': dict(d._fields['state'].selection).get(d.state),
                 'supplier': d.parent_partner_id.name, 'supplier_id': d.parent_partner_id.id, 'coils': len(d.line_ids),
                 'date': fields.Date.to_string(d.date)} for d in rows]

    @api.model
    def da_create(self, vals):
        if not (vals.get('name') or '').strip():
            raise UserError(_("Type the DO / DA number exactly as printed."))
        same = [x for x in self.da_find(vals['name']) if str(x['supplier_id']) == str(vals.get('supplier_id') or '')]
        if same and not vals.get('contract_id'):
            raise UserError(_("DA %(n)s from %(s)s is already in the system (%(st)s). Open it instead of entering it again.",
                              n=same[0]['name'], s=same[0]['supplier'], st=same[0]['state_label']))
        P = self.env['res.partner']
        c = self.env['ei.contract'].browse(int(vals.get('contract_id') or 0)).exists()
        pin = P.browse(int(vals.get('purchase_in_id') or 0)).exists()
        if not c:                                   # the usual way: no contract first, only the three parties
            supplier = P.browse(int(vals.get('supplier_id') or 0)).exists()
            if not supplier:
                raise UserError(_("Type the SUPPLIER (Purchase From) and pick it."))
            if not pin:
                raise UserError(_("Type the Purchase (IN) entity and pick it."))
            # whatever was picked is used: it is marked for its place, never refused for a missing tick
            if not supplier.ei_is_supplier_mill:
                supplier.sudo().write({'ei_is_supplier_mill': True})
            if not pin.ei_is_purchase_in:
                pin.sudo().write({'ei_is_purchase_in': True})
            if not self.env['ei.da'].has_access('create'):
                raise AccessError(_("Your role cannot enter delivery advices."))
            c = self.env['ei.contract']._feeding_account(supplier, pin)
        if c.currency_id.name != 'PKR':
            raise UserError(_("New entries are in PKR only. %s is an older %s contract.", c.name, c.currency_id.name))
        sold = P.browse(int(vals.get('sold_out_id') or 0)).exists()
        d = self.env['ei.da'].create({'name': vals['name'].strip(), 'parent_partner_id': c.parent_partner_id.id, 'contract_id': c.id,
                                      'purchase_in_id': pin.id or c.purchase_in_id.id or False, 'sold_out_id': sold.id or False,
                                      'date': vals.get('date') or fields.Date.context_today(self),
                                      'order_datetime': local_to_utc(self.env, vals.get('order_datetime')), 'ship_date': vals.get('ship_date') or False,
                                      'printed_customer': (vals.get('printed_customer') or '').strip() or False})
        opts = self._quota_options(d.parent_partner_id, d.purchase_in_id)
        if len(opts) == 1:                          # one open contract quantity for this supplier: the DA counts against it
            d.write({'quota_id': opts[0]['id']})
        return d.id

    @api.model
    def da_load(self, da_id):
        d = self._da(da_id)
        att = self.env['ir.attachment'].search([('res_model', '=', 'ei.da'), ('res_id', '=', d.id)], order='id desc')
        fx = d._fx()
        lines = []
        for l in d.line_ids:
            lines.append({'id': l.id, 'coil_no': l.coil_no or '', 'grade': l.coil_grade or '', 'weight_kg': l.weight_kg, 'mtl': l.mtl,
                          'contract_line_id': l.contract_line_id.id, 'product': l.product_id.display_name,
                          'customer': l.customer_id and {'id': l.customer_id.id, 'name': l.customer_id.display_name} or None,
                          'customer_code': self._code_out(l.customer_code_id), 'trade_code': self._code_out(l.trade_code_id),
                          'pl_code': self._code_out(l.pl_code_id), 'method': l.feeding_method or '',
                          'method_label': dict(l._fields['feeding_method'].selection).get(l.feeding_method, _("Not worked out")),
                          'basic_rate': l.basic_rate, 'sale_offset': l.sale_offset, 'sale_typed': l.sale_typed, 'cn_amount': l.cn_amount,
                          'cn_text': l.cn_text or '', 'purchase_rate': l.purchase_rate, 'sale_rate': l.sale_rate, 'loss_reason': l.loss_reason or '',
                          'rate_note': l.rate_note or '', 'spread': l.spread_per_mtl, 'gross': l.gross_spread, 'code_issue': l.code_issue or '',
                          'thickness': l.coil_thickness or '', 'width': l.coil_width or '', 'sale_amount': l.sale_amount,
                          'purchase_amount': l.purchase_amount,
                          'override': l.code_override_reason or ''})
        return {
            'id': d.id, 'name': d.name, 'state': d.state, 'state_label': dict(d._fields['state'].selection).get(d.state),
            'editable': d.state == 'draft' and d.has_access('write'), 'parent': d.parent_partner_id.name,
            'contract': '%s - %s' % (d.contract_id.name, d.contract_id.contract_ref), 'date': fields.Date.to_string(d.date),
            'order_datetime': d.order_datetime and fields.Datetime.context_timestamp(self.with_context(tz=self.env.user.tz or 'Asia/Karachi'), d.order_datetime).strftime('%Y-%m-%d %H:%M') or '',
            'ship_date': d.ship_date and fields.Date.to_string(d.ship_date) or '', 'printed_customer': d.printed_customer or '',
            'currency': d.currency_id.name, 'company_currency': d.company_id.currency_id.name, 'fx_text': d.fx_text or '',
            'fx_missing': fx is False, 'fx_rate': fx and fx.rate or None,
            'attachments': [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype, 'by': a.create_uid.name, 'can_remove': self._can_remove_doc(d, a)}
                            for a in att],
            'can_attach': d.has_access('write'),
            'quota': d.quota_id and d.quota_id.summary() or None,
            'quota_options': self._quota_options(d.parent_partner_id, d.purchase_in_id),
            'can_adjust_quota': self.env['ei.feeding.quota'].can_adjust(),
            'contract_lines': [{'id': cl.id, 'name': '%s%s' % (cl.product_id.display_name, ' (%s)' % cl.grade if cl.grade else ''),
                                'basic_rate': cl.basic_rate, 'formula': cl.formula_id and '%s v%s' % (cl.formula_id.code, cl.formula_id.version) or '',
                                'formula_state': cl.formula_id.state or '', 'free_mtl': d._available(cl),
                                'target_customer': cl.target_customer_id and {'id': cl.target_customer_id.id, 'name': cl.target_customer_id.display_name} or None}
                               for cl in d.contract_id.line_ids],
            'lines': lines, 'total_mtl': d.total_mtl, 'total_spread': sum(d.line_ids.mapped('gross_spread')),
            'review_requested': d.review_requested, 'approval_on': self.env['ei.approval.policy'].flow_on('da'),
            'supplier': d.parent_partner_id.display_name, 'purchase_in': d.purchase_in_id.display_name or '',
            'sold_out': d.sold_out_id and {'id': d.sold_out_id.id, 'name': d.sold_out_id.display_name} or None,
            'is_feeding': d.is_feeding_account, 'total_sale': sum(d.line_ids.mapped('sale_amount')),
            'total_purchase': sum(d.line_ids.mapped('purchase_amount')),
            'approved_by': d.approved_by.name or '',
        }

    def _code_out(self, c):
        return c and {'id': c.id, 'code': c.legacy_code, 'name': c.original_name, 'nick': c.nickname or '',
                      'verified': c.verification_status == 'approved'} or None

    @api.model
    def da_save_header(self, da_id, vals):
        d = self._da(da_id, write=True)
        allowed = {k: vals[k] or False for k in ('printed_customer', 'ship_date', 'date') if k in vals}
        if 'sold_out_id' in vals:
            allowed['sold_out_id'] = int(vals['sold_out_id']) if vals['sold_out_id'] else False
        if 'order_datetime' in vals:
            allowed['order_datetime'] = local_to_utc(self.env, vals['order_datetime'])
        d.write(allowed)
        return self.da_load(d.id)

    @api.model
    def preview(self, da_id, vals):
        """What this coil would give, without saving."""
        d = self._da(da_id)
        cl = d.contract_id.line_ids.filtered(lambda x: x.id == int(vals.get('contract_line_id') or 0))
        if not cl:
            return {'ok': False, 'error': _("Choose the contract line (material) first.")}
        try:
            r = self.env['ei.da.line']._feed(cl, self._clean(vals))
        except fe.FeedingError as e:
            return {'ok': False, 'error': str(e)}
        res = out(r)
        res.update(sale_total=str(fe.money(r['sale_rate'] * r['quantity'])), purchase_total=str(fe.money(r['purchase_rate'] * r['quantity'])))
        code = self.env['ei.legacy.code'].browse(int(vals['customer_code_id'])) if vals.get('customer_code_id') else self.env['ei.legacy.code']
        customer = self.env['res.partner'].browse(int(vals['customer_id'])) if vals.get('customer_id') else self.env['res.partner']
        res.update(ok=True, currency=d.currency_id.name, base=self._base(d, r),
                   code_issue=self.env['ei.da.line']._code_problem_for(code.exists(), customer.exists(), d.printed_customer))
        return res

    def _base(self, d, r):
        fx = d._fx()
        if not fx:
            return None
        rate = Decimal(str(fx.rate))
        return {'currency': d.company_id.currency_id.name, 'rate_date': fields.Date.to_string(fx.name),
                'purchase_rate': str(fe.money(r['purchase_rate'] / rate)), 'sale_rate': str(fe.money(r['sale_rate'] / rate)),
                'total_spread': str(fe.money(r['total_spread'] / rate))}

    def _clean(self, vals):
        v = {'feeding_method': vals.get('method') or False, 'sale_typed': bool(vals.get('sale_typed'))}
        for k, label in (('basic_rate', _("Basic rate")), ('sale_offset', _("Mill rate +/-")), ('sale_rate', _("Sale rate")),
                         ('purchase_rate', _("Purchase rate")), ('cn_amount', _("Credit note")), ('weight_kg', _("Weight"))):
            v[k] = num(vals.get(k), label)
        return v

    def _lock_da(self, d):
        """One person's save at a time per DA: two saves of the same coil number never both pass (the second waits, then retries)."""
        self.env.cr.execute('UPDATE ei_da SET write_date = write_date WHERE id = %s', (d.id,))

    @api.model
    def save_line(self, da_id, line_id, vals):
        d = self._da(da_id, write=True)
        self._lock_da(d)
        line = self._write_line(d, line_id, vals)
        return {'line_id': line.id, 'da': self.da_load(d.id)}

    def _write_line(self, d, line_id, vals):
        cl = d.contract_id.line_ids.filtered(lambda x: x.id == int(vals.get('contract_line_id') or 0))
        if not cl:
            raise UserError(_("Choose the contract line (material) first."))
        if not (vals.get('coil_no') or '').strip():
            raise UserError(_("Type the coil number exactly as printed."))
        if d.line_ids.filtered(lambda x: x.coil_no == vals['coil_no'].strip() and x.id != int(line_id or 0)):
            raise UserError(_("Coil %s is already on this DA.", vals['coil_no'].strip()))
        clean = self._clean(vals)
        size = dims_problem(cl.product_id.display_name, vals.get('thickness'), vals.get('width'))
        if size:
            raise UserError(size)
        if not clean['weight_kg'] or clean['weight_kg'] <= 0:
            raise UserError(_("Type the coil's weight (in MTL, or in kg) as printed."))
        if clean['weight_kg'] < SMALL_KG and not vals.get('small_weight_ok'):
            raise UserError(_("%(kg)s kg is only %(t)s MTL. If the paper says %(kg)s MTL, choose MTL. If it really is %(kg)s kg, "
                              "tick 'Yes, the weight is in kg' and save again.", kg=clean['weight_kg'], t=clean['weight_kg'] / 1000))
        if clean['feeding_method'] == 'purchase_without_commission':
            raise UserError(fe.METHODS['purchase_without_commission'][3])
        try:
            r = self.env['ei.da.line']._feed(cl, clean)
        except fe.FeedingError as e:
            raise UserError(str(e))
        if clean['feeding_method'] == 'purchase_with_cn' and not (vals.get('cn_text') or '').strip():
            raise UserError(_("Write the credit note text for this coil, as on the parent's paper."))
        if r['spread_per_mtl'] < 0 and not (vals.get('loss_reason') or '').strip():
            raise UserError(_("This coil is sold below cost (%s per MTL). Write why; an approver will check it.", r['spread_per_mtl']))
        write = {
            'contract_line_id': cl.id, 'coil_no': vals['coil_no'].strip(), 'coil_grade': (vals.get('grade') or '').strip() or False,
            'weight_kg': float(clean['weight_kg']), 'mtl': float(r['quantity']), 'feeding_method': clean['feeding_method'],
            'basic_rate': float(clean['basic_rate'] or cl.basic_rate or 0) if r['formula'] else 0.0,
            'sale_offset': float(r['sale_offset'] or 0), 'sale_typed': clean['sale_typed'] if r['formula'] else True,
            'cn_amount': float(clean['cn_amount'] or 0) if clean['feeding_method'] == 'purchase_with_cn' else 0.0,
            'cn_text': (vals.get('cn_text') or '').strip() if clean['feeding_method'] == 'purchase_with_cn' else False,
            'purchase_rate': float(r['purchase_rate']), 'sale_rate': float(r['sale_rate']),
            'coil_thickness': (vals.get('thickness') or '').strip() or False, 'coil_width': (vals.get('width') or '').strip() or False,
            'loss_reason': (vals.get('loss_reason') or '').strip() or False, 'rate_note': (vals.get('rate_note') or '').strip() or False,
            'customer_id': int(vals['customer_id']) if vals.get('customer_id') else False,
            'customer_code_id': int(vals['customer_code_id']) if vals.get('customer_code_id') else False,
            'trade_code_id': int(vals['trade_code_id']) if vals.get('trade_code_id') else False,
            'pl_code_id': int(vals['pl_code_id']) if vals.get('pl_code_id') else False,
            'feeding_calc': out(dict(r, saved_by=self.env.user.name, saved_at=fields.Datetime.to_string(fields.Datetime.now()))),
        }
        if write['customer_code_id'] and write['customer_id'] and self.env['ir.config_parameter'].sudo().get_bool('ei_da_feeding.link_codes_on_entry', False):
            self._link_code(self.env['ei.legacy.code'].browse(write['customer_code_id']), self.env['res.partner'].browse(write['customer_id']))
        Line = self.env['ei.da.line']
        if line_id:
            line = d.line_ids.filtered(lambda x: x.id == int(line_id))
            if not line:
                raise UserError(_("This coil is not on DA %s.", d.name))
            keep = line.customer_code_id.id == write['customer_code_id'] and line.customer_id.id == write['customer_id']
            line.write(write)
            if not keep:
                line.with_context(ei_system=True).write({'code_override_reason': False, 'code_override_by': False})
        else:
            line = Line.create(dict(write, da_id=d.id))
        return line

    # ------------------------------------------------------------------ many coils at once (client, 22 Nov 2026)
    SHARED = ('contract_line_id', 'grade', 'thickness', 'width', 'method', 'basic_rate', 'sale_offset', 'sale_typed', 'sale_rate',
              'purchase_rate', 'loss_reason', 'rate_note', 'customer_id', 'customer_code_id', 'trade_code_id', 'pl_code_id')

    @api.model
    def save_lines(self, da_id, shared, rows):
        """Add Multiple Coils: the shared details (item, codes, method, rates) once, then each coil's own number and weight (and its
        own credit note, never copied unless typed). All coils are saved together or none: one wrong row stops the whole batch."""
        d = self._da(da_id, write=True)
        self._lock_da(d)
        rows = [r for r in (rows or []) if (r.get('coil_no') or '').strip() or (r.get('weight_kg') or '') not in ('', None)]
        if not rows:
            raise UserError(_("Type the coil numbers and weights first."))
        seen, twice = set(), []
        for r in rows:
            c = (r.get('coil_no') or '').strip()
            if c in seen:
                twice.append(c)
            seen.add(c)
        if twice:
            raise UserError(_("Coil number typed twice in these rows: %s.", ', '.join(sorted(set(twice)))))
        lines = self.env['ei.da.line']
        for i, r in enumerate(rows, 1):
            vals = {k: shared.get(k) for k in self.SHARED}
            vals.update({k: r.get(k) for k in ('coil_no', 'weight_kg', 'cn_amount', 'cn_text', 'small_weight_ok') if k in r})
            for k in ('basic_rate', 'sale_offset', 'sale_rate', 'purchase_rate'):
                if r.get(k) not in (None, ''):
                    vals[k] = r[k]
            try:
                lines |= self._write_line(d, False, vals)
            except UserError as e:
                raise UserError(_("Row %(i)s (coil %(c)s): %(e)s", i=i, c=(r.get('coil_no') or '?').strip(), e=e.args[0]))
        return {'created': len(lines), 'da': self.da_load(d.id)}

    def _vals_of(self, l):
        """A saved coil as the screen would send it (to work it out again with one rate changed)."""
        return {'contract_line_id': l.contract_line_id.id, 'coil_no': l.coil_no, 'grade': l.coil_grade or '', 'thickness': l.coil_thickness or '',
                'width': l.coil_width or '', 'weight_kg': l.weight_kg, 'method': l.feeding_method, 'basic_rate': l.basic_rate or '',
                'sale_offset': l.sale_offset, 'sale_typed': l.sale_typed, 'sale_rate': l.sale_rate, 'purchase_rate': l.purchase_rate,
                'cn_amount': l.cn_amount, 'cn_text': l.cn_text or '', 'loss_reason': l.loss_reason or '', 'rate_note': l.rate_note or '',
                'customer_id': l.customer_id.id, 'customer_code_id': l.customer_code_id.id, 'trade_code_id': l.trade_code_id.id,
                'pl_code_id': l.pl_code_id.id, 'small_weight_ok': True}

    @api.model
    def apply_rates(self, da_id, line_ids, rates, confirm=False):
        """Apply Rate to Selected. Only the rates typed are changed, and only on coils of the matching kind: a basic rate and
        mill +/- on formula coils, purchase and sale rates on direct coils. A coil of another kind is left as it is and listed.
        Credit notes, weights, codes and customers are never touched. Without confirm nothing is saved: the screen shows the
        coils and totals before and after and asks first."""
        d = self._da(da_id, write=True)
        rates = {k: v for k, v in (rates or {}).items() if v not in (None, '')}
        method = rates.pop('method', None)
        if method and method not in fe.METHODS:
            raise UserError(_("Unknown feeding method."))
        lines = d.line_ids.filtered(lambda l: l.id in [int(x) for x in line_ids or []])
        if not lines:
            raise UserError(_("Select the coils first."))
        changed, skipped, tot = [], [], {'purchase_before': Decimal(0), 'purchase_after': Decimal(0), 'sale_before': Decimal(0),
                                         'sale_after': Decimal(0), 'spread_before': Decimal(0), 'spread_after': Decimal(0)}
        plans = []
        for l in lines:
            vals = self._vals_of(l)
            m = method or l.feeding_method
            basis = fe.METHODS.get(m, (None, None))[1]
            use = {}
            if basis == 'direct':
                use = {k: rates[k] for k in ('purchase_rate', 'sale_rate') if k in rates}
            elif basis in ('dealer_net', 'with_cn'):
                use = {k: rates[k] for k in ('basic_rate', 'sale_offset') if k in rates}
                if vals['sale_typed'] and 'sale_rate' in rates:
                    use['sale_rate'] = rates['sale_rate']
            if rates and not use and not method:
                skipped.append({'id': l.id, 'coil_no': l.coil_no, 'why': _("%s: these rates are of another kind", dict(l._fields['feeding_method'].selection).get(l.feeding_method))})
                continue
            vals.update(use, method=m)
            if method and method != l.feeding_method and m in ('purchase_with_cn', 'sale_at_mill_rate'):
                vals['sale_offset'] = '0'
            try:
                r = self.env['ei.da.line']._feed(l.contract_line_id, self._clean(vals))
            except fe.FeedingError as e:
                raise UserError(_("Coil %(c)s: %(e)s", c=l.coil_no, e=str(e)))
            q = Decimal(str(l.mtl))
            before = (Decimal(str(l.purchase_rate)), Decimal(str(l.sale_rate)))
            row = {'id': l.id, 'coil_no': l.coil_no, 'mtl': str(l.mtl), 'purchase_before': str(before[0]), 'sale_before': str(before[1]),
                   'purchase_after': str(r['purchase_rate']), 'sale_after': str(r['sale_rate']), 'spread_after': str(r['spread_per_mtl'])}
            tot['purchase_before'] += fe.money(before[0] * q); tot['sale_before'] += fe.money(before[1] * q)
            tot['spread_before'] += Decimal(str(l.gross_spread))
            tot['purchase_after'] += fe.money(r['purchase_rate'] * q); tot['sale_after'] += fe.money(r['sale_rate'] * q)
            tot['spread_after'] += r['total_spread']
            changed.append(row); plans.append((l, vals, r))
        if not changed:
            raise UserError(_("None of the selected coils takes these rates (they are of another kind)."))
        if confirm:
            self._lock_da(d)
            for l, vals, r in plans:
                if r['spread_per_mtl'] < 0 and not vals.get('loss_reason'):
                    raise UserError(_("Coil %s would be sold below cost. Write why on that coil first (Edit), then apply.", l.coil_no))
                self._write_line(d, l.id, vals)
            d.message_post(body=_("Rates applied to %(n)s coil(s) by %(u)s: %(r)s%(m)s.", n=len(plans), u=self.env.user.name,
                                  r=', '.join('%s %s' % (k, v) for k, v in rates.items()) or _('recalculated'),
                                  m=method and _(', method %s', method) or ''))
        return {'count': len(changed), 'rows': changed, 'skipped': skipped, 'totals': {k: str(v) for k, v in tot.items()},
                'applied': bool(confirm), 'da': self.da_load(d.id) if confirm else None}

    @api.model
    def product_search(self, term=''):
        Pr = self.env['product.product']
        if not Pr.has_access('read'):
            return []
        term = (term or '').strip()
        dom = ['|', ('name', 'ilike', term), ('default_code', 'ilike', term)] if term else []
        rows = [{'id': p.id, 'key': 'p%d' % p.id, 'name': p.display_name} for p in Pr.search(dom, limit=20)]
        # an item that is not in the system yet is added as typed (17 Nov 2026: nothing to set up first)
        if term and not any(r['name'].strip().lower() == term.lower() for r in rows):
            rows.append({'id': 0, 'key': 'new', 'kind': 'new', 'name': term})
        return rows

    @api.model
    def product_take(self, name):
        """The typed item as a product in tons, without default taxes (sales tax follows the accountant's rules)."""
        name = (name or '').strip()
        if not name:
            raise UserError(_("Type the item name."))
        if not self.env['ei.da'].has_access('create'):
            raise AccessError(_("Your role cannot enter delivery advices."))
        Pr = self.env['product.product'].sudo()
        p = Pr.search([('name', '=ilike', name)], limit=1)
        if not p:
            uom = self.env.ref('uom.product_uom_ton', raise_if_not_found=False)
            vals = {'name': name, 'type': 'consu', 'taxes_id': [(5, 0, 0)], 'supplier_taxes_id': [(5, 0, 0)]}
            if uom:
                vals['uom_id'] = uom.id
            p = Pr.create(vals)
        return p.id

    @api.model
    def ensure_line(self, da_id, product_id):
        """A feeding-account DA takes any material: the account's line for it is found or opened, and the DA is reloaded."""
        d = self._da(da_id, write=True)
        product = self.env['product.product'].browse(int(product_id)).exists()
        if not product:
            raise UserError(_("Choose the item."))
        line = d.contract_id._feeding_line(product)
        size = item_dims(product.display_name)
        return {'contract_line_id': line.id, 'da': self.da_load(d.id),
                'dims': size and {'thickness': str(size[0]), 'width': str(size[1])} or None}

    @api.model
    def da_delete(self, da_id):
        """Delete Draft: a DA still in draft (never submitted in its current form) is deleted with its coils; anything later is
        cancelled or amended instead. The deletion is written on the supplier's record so it is never silent."""
        d = self._da(da_id, write=True)
        d.check_access('unlink')
        name, partner = d.name, d.parent_partner_id
        d.unlink()
        partner.sudo().message_post(body=_("Draft DA %(n)s deleted by %(u)s before it was submitted.", n=name, u=self.env.user.name))
        return self.da_list()

    @api.model
    def delete_line(self, da_id, line_id):
        d = self._da(da_id, write=True)
        d.line_ids.filtered(lambda x: x.id == int(line_id)).unlink()
        return self.da_load(d.id)

    @api.model
    def submit(self, da_id, review=False):
        """Save & Continue. Approval off (the default): the DA is confirmed now, by the person entering it, after every check
        (quantities, rates, codes, exchange rate). Approval on, or 'Send for review' ticked: it goes to the approver.
        When confirmed, the next task (today's daily order request) is prepared from it."""
        d = self._da(da_id, write=True)
        if not d.line_ids:
            raise UserError(_("Add at least one coil first."))
        unsold = d.line_ids.filtered(lambda l: l.feeding_method and not l.customer_id)
        if unsold:
            raise UserError(_("%(n)s coil(s) are not sold yet (%(c)s). Keep the DA as a draft, and choose Sold (OUT) on them before submitting.",
                              n=len(unsold), c=', '.join(unsold.mapped(lambda l: l.coil_no or '?'))))
        d.write({'review_requested': bool(review)})
        d.action_confirm()
        nxt = None
        if d.state == 'approved' and 'ei.daily.order' in self.env and self.env['ei.daily.order'].has_access('create'):
            try:
                with self.env.cr.savepoint():          # a problem with today's order never undoes the confirmed DA
                    order = self.env['ei.daily.order'].generate_from_da(d)
            except UserError as e:
                nxt = {'error': str(e)}
            else:
                if order:
                    nxt = {'model': 'ei.daily.order', 'id': order.id, 'name': order.display_name,
                           'state': dict(order._fields['state'].selection).get(order.state)}
        res = self.da_load(d.id)
        res['next'] = nxt
        return res

    def _da_docs(self, da_id):
        d = self.env['ei.da'].browse(int(da_id)).exists()
        if not d:
            raise UserError(_("This DA no longer exists."))
        d.check_access('write')
        return d

    @api.model
    def attach(self, da_id, name, data_b64, mimetype=None, replace_id=False):
        """Attach DA (Optional): never required to save, continue or submit. A paper can be added at any stage; replacing or
        removing one is for a draft, by the person who attached it or a person who may delete DAs, and is written on the DA."""
        d = self._da_docs(da_id)
        raw = base64.b64decode(data_b64 or '')
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise UserError(_("The file is empty or larger than 20 MB."))
        old = replace_id and self._doc(d, replace_id, remove=True)
        att = self.env['ir.attachment'].create({'name': name or 'DA.pdf', 'raw': raw, 'mimetype': mimetype or False,
                                                'res_model': 'ei.da', 'res_id': d.id})
        if old:
            d.message_post(body=_("DA paper %(o)s replaced by %(n)s (%(u)s).", o=old.name, n=att.name, u=self.env.user.name))
            old.unlink()
        else:
            d.message_post(body=_("DA paper %(n)s attached (%(u)s).", n=att.name, u=self.env.user.name))
        return self.da_load(d.id)

    def _doc(self, d, att_id, remove=False):
        att = self.env['ir.attachment'].search([('id', '=', int(att_id)), ('res_model', '=', 'ei.da'), ('res_id', '=', d.id)], limit=1)
        if not att:
            raise UserError(_("This paper is not on DA %s.", d.name))
        if remove and not self._can_remove_doc(d, att):
            raise AccessError(_("Only the person who attached this paper, or a person who may delete DAs, replaces or removes it, "
                                "and only while the DA is a draft."))
        return att

    def _can_remove_doc(self, d, att):
        return d.state == 'draft' and (att.create_uid == self.env.user or d.has_access('unlink'))

    @api.model
    def detach(self, da_id, att_id):
        d = self._da_docs(da_id)
        att = self._doc(d, att_id, remove=True)
        d.message_post(body=_("DA paper %(n)s removed (%(u)s).", n=att.name, u=self.env.user.name))
        att.unlink()
        return self.da_load(d.id)

    # ------------------------------------------------------------------ contract quantity (500 MTL, 425 entered, 75 remaining)
    def _quota_options(self, supplier, pin):
        Q = self.env['ei.feeding.quota']
        if not supplier or not Q.has_access('read'):
            return []
        qs = Q.search([('supplier_id', '=', supplier.id), ('state', '=', 'open'), '|', ('purchase_in_id', '=', False), ('purchase_in_id', '=', pin.id)])
        return [q.summary() for q in qs]

    @api.model
    def quota_link(self, da_id, quota_id):
        d = self._da(da_id, write=True)
        q = self.env['ei.feeding.quota'].browse(int(quota_id or 0)).exists()
        if q and q.supplier_id != d.parent_partner_id:
            raise UserError(_("%(c)s is a contract of %(s)s, not of this DA's supplier.", c=q.name, s=q.supplier_id.name))
        d.write({'quota_id': q.id or False})
        return self.da_load(d.id)

    @api.model
    def quota_create(self, da_id, name, total):
        d = self._da(da_id, write=True)
        name = (name or '').strip()
        if not name:
            raise UserError(_("Name the contract, e.g. December 2026."))
        t = num(total, _("Total quantity"))
        if not t or t <= 0:
            raise UserError(_("Type the contract's total quantity in MTL."))
        q = self.env['ei.feeding.quota'].with_context(ei_quota_new=True).create({
            'name': name, 'supplier_id': d.parent_partner_id.id, 'purchase_in_id': d.purchase_in_id.id or False, 'total_mtl': float(t)})
        d.write({'quota_id': q.id})
        return self.da_load(d.id)

    @api.model
    def quota_adjust(self, da_id, quota_id, total, reason):
        """The documented way past the total: a person with the right raises it, and the reason stays on the contract."""
        d = self._da(da_id)
        q = self.env['ei.feeding.quota'].browse(int(quota_id)).exists()
        if not q or q != d.quota_id:
            raise UserError(_("This DA is not on that contract."))
        t = num(total, _("Total quantity"))
        q.with_context(ei_quota_reason=(reason or '').strip()).write({'total_mtl': float(t or 0)})
        return self.da_load(d.id)

    # ------------------------------------------------------------------ look-ups
    @api.model
    def code_search(self, kind, term='', hint=''):
        """Codes of ONE list (customer, purchase/sale, P&L): by code, name or nickname. With no term, codes whose name shares a
        word with the printed customer are offered as SUGGESTIONS to check, never chosen automatically."""
        sheet = SHEETS.get(kind)
        Code = self.env['ei.legacy.code']
        if not sheet or not Code.has_access('read'):
            return []
        term = (term or '').strip()
        dom = [('source_sheet_key', '=', sheet), ('verification_status', '!=', 'rejected')]
        suggested = set()
        if term:
            found = Code.search(dom + ['|', '|', ('legacy_code', '=like', term + '%'), ('original_name', 'ilike', term),
                                       ('nickname', 'ilike', term)], limit=30)
            found = found.sorted(lambda c: (c.legacy_code != term, not c.legacy_code.startswith(term), c.legacy_code))
        else:
            words = name_tokens(hint)
            found = Code.browse()
            for w in sorted(words):
                found |= Code.search(dom + ['|', ('original_name', 'ilike', w), ('nickname', 'ilike', w)], limit=10)
            suggested = set(found.ids)
        return [dict(self._code_out(c), suggested=c.id in suggested, status=dict(c._fields['verification_status'].selection).get(c.verification_status))
                for c in found[:30]]

    @api.model
    def partner_search(self, term=''):
        """Sold (OUT) / customer look-up (kept for older callers): the same rows as party_search('customer')."""
        return self.party_search('customer', term)

    ROLE_FLAG = {'supplier': 'ei_is_supplier_mill', 'pin': 'ei_is_purchase_in', 'customer': None}

    @api.model
    def party_search(self, role, term=''):
        """Type a name or an old code; pick it. Everything already in the system is offered: companies and contacts (those
        already used in this place first), and for a customer also the client's old CUSTOMER codes that have no contact yet.
        When nothing has exactly that name, the last row adds it as new. Picking goes through party_take."""
        P = self.env['res.partner']
        term = (term or '').strip()
        if role not in self.ROLE_FLAG or not term or not P.has_access('read'):
            return []
        flag = self.ROLE_FLAG[role]
        found = P.search(['|', '|', ('name', 'ilike', term), ('ref', '=ilike', term), ('ref', '=like', term + '%'),
                          ('parent_id', '=', False)], limit=40)          # companies and people, not their addresses
        found = found.sorted(lambda p: (not (flag and p[flag]), not p.is_company, (p.name or '').lower() != term.lower(), p.name or ''))[:15]
        rows = [{'key': 'p%d' % p.id, 'kind': 'partner', 'id': p.id, 'name': p.display_name, 'ref': p.ref or ''} for p in found]
        Code = self.env['ei.legacy.code']
        if role == 'customer' and Code.has_access('read'):
            refs = set(found.mapped('ref'))
            codes = Code.search([('source_sheet_key', '=', 'CUSTOMER'), ('verification_status', '!=', 'rejected'),
                                 '|', '|', ('legacy_code', '=like', term + '%'), ('original_name', 'ilike', term), ('nickname', 'ilike', term)], limit=15)
            rows += [{'key': 'c%d' % c.id, 'kind': 'code', 'id': c.id, 'name': c.original_name, 'ref': c.legacy_code}
                     for c in codes if c.legacy_code not in refs]
        if not any((r['name'] or '').strip().lower() == term.lower() for r in rows):
            rows.append({'key': 'new', 'kind': 'new', 'id': 0, 'name': term, 'ref': ''})
        return rows

    def _link_code(self, code, partner):
        """An old customer code that is not linked to any contact yet is linked to this one (the contact it was picked as).
        A code the accountant already linked is never moved."""
        code = code.sudo().exists()
        if code and partner and code.source_sheet_key == 'CUSTOMER' and not code.linked_res_id:
            code.with_context(ei_system_write=True).write({'linked_model': 'res.partner', 'linked_res_id': partner.id})
            if not partner.ref:
                partner.sudo().write({'ref': code.legacy_code})

    @api.model
    def party_take(self, role, row):
        """The picked row as a contact, ready for the DA: an existing contact is used as it is (and marked for this place);
        an old code becomes a contact named and referenced like the code; a new name becomes a new company. No other question."""
        if role not in self.ROLE_FLAG:
            raise UserError(_("Unknown party."))
        if not self.env['ei.da'].has_access('create'):
            raise AccessError(_("Your role cannot enter delivery advices."))
        P = self.env['res.partner'].sudo()
        kind, name = row.get('kind'), (row.get('name') or '').strip()
        partner = P.browse()
        if kind == 'partner':
            partner = P.browse(int(row.get('id') or 0)).exists()
            if role == 'customer' and partner.ref:            # a contact made from an old code keeps that code's link
                self._link_code(self.env['ei.legacy.code'].sudo().search([('source_sheet_key', '=', 'CUSTOMER'), ('legacy_code', '=', partner.ref)], limit=1), partner)
        elif kind == 'code':
            code = self.env['ei.legacy.code'].browse(int(row.get('id') or 0)).exists()
            if not code:
                raise UserError(_("This old code no longer exists."))
            partner = P.search([('ref', '=', code.legacy_code)], limit=1) or P.search([('name', '=ilike', code.original_name)], limit=1)
            if not partner:
                partner = P.create({'name': code.original_name, 'ref': code.legacy_code, 'is_company': True, 'customer_rank': 1})
            self._link_code(code, partner)
        elif kind == 'new' and name:
            partner = P.search([('name', '=ilike', name)], limit=1) or P.create({'name': name, 'is_company': True})
        if not partner:
            raise UserError(_("Type a name and pick it from the list."))
        flag = self.ROLE_FLAG[role]
        vals = {flag: True} if flag and not partner[flag] else {}
        if role == 'customer' and not partner.customer_rank:
            vals['customer_rank'] = 1
        if role == 'supplier' and not partner.supplier_rank:
            vals['supplier_rank'] = 1
        if vals:
            partner.write(vals)
        return {'id': partner.id, 'name': partner.display_name, 'ref': partner.ref or ''}
