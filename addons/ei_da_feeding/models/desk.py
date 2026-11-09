"""The DA Feeding Desk: one screen for practice (never posts) and for real entry (draft -> review -> approval).

Every number on the screen comes from here, worked out again on the server from what was typed. Practice writes
NOTHING to the database. Real entry writes only draft DA lines, through the DA's own rules and permissions."""
import base64
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
                'contracts': [{'id': c.id, 'name': '%s - %s (%s)' % (c.name, c.contract_ref, c.parent_partner_id.name),
                               'parent_id': c.parent_partner_id.id, 'currency': c.currency_id.name}
                              for c in self.env['ei.contract'].search([('state', '=', 'active')], limit=200)]}

    @api.model
    def da_create(self, vals):
        c = self.env['ei.contract'].browse(int(vals.get('contract_id') or 0)).exists()
        if not c:
            raise UserError(_("Choose the active contract this DA belongs to."))
        if not (vals.get('name') or '').strip():
            raise UserError(_("Type the DA number exactly as printed."))
        d = self.env['ei.da'].create({'name': vals['name'].strip(), 'parent_partner_id': c.parent_partner_id.id, 'contract_id': c.id,
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
                          'customer': l.customer_id and {'id': l.customer_id.id, 'name': l.customer_id.display_name},
                          'customer_code': self._code_out(l.customer_code_id), 'trade_code': self._code_out(l.trade_code_id),
                          'pl_code': self._code_out(l.pl_code_id), 'method': l.feeding_method or '',
                          'method_label': dict(l._fields['feeding_method'].selection).get(l.feeding_method, _("Not worked out")),
                          'basic_rate': l.basic_rate, 'sale_offset': l.sale_offset, 'sale_typed': l.sale_typed, 'cn_amount': l.cn_amount,
                          'cn_text': l.cn_text or '', 'purchase_rate': l.purchase_rate, 'sale_rate': l.sale_rate, 'loss_reason': l.loss_reason or '',
                          'rate_note': l.rate_note or '', 'spread': l.spread_per_mtl, 'gross': l.gross_spread, 'code_issue': l.code_issue or '',
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
                                'target_customer': cl.target_customer_id and {'id': cl.target_customer_id.id, 'name': cl.target_customer_id.display_name}}
                               for cl in d.contract_id.line_ids],
            'lines': lines, 'total_mtl': d.total_mtl, 'total_spread': sum(d.line_ids.mapped('gross_spread')),
            'review_requested': d.review_requested, 'approval_on': self.env['ei.approval.policy'].flow_on('da'),
            'approved_by': d.approved_by.name or '',
        }

    def _code_out(self, c):
        return c and {'id': c.id, 'code': c.legacy_code, 'name': c.original_name, 'nick': c.nickname or '',
                      'verified': c.verification_status == 'approved'} or None

    @api.model
    def da_save_header(self, da_id, vals):
        d = self._da(da_id, write=True)
        allowed = {k: vals[k] or False for k in ('printed_customer', 'ship_date', 'date') if k in vals}
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
        res.update(ok=True, currency=d.currency_id.name, base=self._base(d, r))
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
