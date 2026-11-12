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
    def da_create(self, vals):
        if not (vals.get('name') or '').strip():
            raise UserError(_("Type the DO / DA number exactly as printed."))
        P = self.env['res.partner']
        c = self.env['ei.contract'].browse(int(vals.get('contract_id') or 0)).exists()
        pin = P.browse(int(vals.get('purchase_in_id') or 0)).exists()
        if not c:                                   # the usual way: no contract first, only the three parties
            supplier = P.browse(int(vals.get('supplier_id') or 0)).exists()
            if not supplier or not supplier.ei_is_supplier_mill:
                raise UserError(_("Choose the SUPPLIER (Purchase From)."))
            if not pin or not pin.ei_is_purchase_in:
                raise UserError(_("Choose the Purchase (IN) entity."))
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
            'attachments': [{'id': a.id, 'name': a.name, 'mimetype': a.mimetype} for a in att],
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

    @api.model
    def save_line(self, da_id, line_id, vals):
        d = self._da(da_id, write=True)
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
            raise UserError(_("Type the coil's weight in kg as printed."))
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
        return {'line_id': line.id, 'da': self.da_load(d.id)}

    @api.model
    def product_search(self, term=''):
        Pr = self.env['product.product']
        if not Pr.has_access('read'):
            return []
        dom = ['|', ('name', 'ilike', term), ('default_code', 'ilike', term)] if term else []
        return [{'id': p.id, 'name': p.display_name} for p in Pr.search(dom, limit=20)]

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

    @api.model
    def attach(self, da_id, name, data_b64, mimetype=None):
        d = self._da(da_id, write=True)
        raw = base64.b64decode(data_b64 or '')
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise UserError(_("The file is empty or larger than 20 MB."))
        self.env['ir.attachment'].create({'name': name or 'DA.pdf', 'raw': raw, 'mimetype': mimetype or False,
                                          'res_model': 'ei.da', 'res_id': d.id})
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
        P = self.env['res.partner']
        if not P.has_access('read'):
            return []
        rows = P.search(['|', ('name', 'ilike', term or ''), ('ref', '=ilike', term or '')], limit=20) if term else P.browse()
        return [{'id': p.id, 'name': p.display_name, 'ref': p.ref or ''} for p in rows]
