"""The Overview pieces of Home: money and material flows for a chosen period against the period before it, the customers who
owe most, and the latest documents.

Real figures only. A flow is the sum of real records dated inside the period (posted customer invoices, posted bank receipts,
verified truck loadings), and its change is worked out against the same number of days just before it. When there is nothing to
compare with the card says "New" or "No activity" instead of inventing a percentage. A card the role may not see is ABSENT,
never shown as a zero. Every card opens exactly the records it counted (open_flow)."""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.tools.misc import format_amount, format_date

PERIODS = (('7d', 7), ('14d', 14), ('30d', 30), ('month', 0))
DEFAULT_PERIOD = '14d'
TOP_N = 5
RECENT_N = 6


class EiHomeOverview(models.AbstractModel):
    _inherit = 'ei.home'

    # ------------------------------------------------------------------ the period
    def _period_options(self):
        labels = {'7d': _("Last 7 days"), '14d': _("Last 14 days"), '30d': _("Last 30 days"), 'month': _("This month")}
        return [{'key': k, 'label': labels[k]} for k, _days in PERIODS]

    def _range(self, key):
        """(key, start, end, previous start, previous end). An unknown key falls back to the default: the client never chooses dates."""
        key = key if key in dict(PERIODS) else DEFAULT_PERIOD
        today = fields.Date.context_today(self)
        if key == 'month':
            start = today.replace(day=1)
            prev_start = (start - timedelta(days=1)).replace(day=1)
            prev_end = min(prev_start + (today - start), start - timedelta(days=1))
        else:
            n = dict(PERIODS)[key]
            start = today - timedelta(days=n - 1)
            prev_end = start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=n - 1)
        return key, start, today, prev_start, prev_end

    def _period_info(self, key):
        key, start, end, prev_start, prev_end = self._range(key)
        short = lambda d: format_date(self.env, d, date_format='dd MMM')
        return {'key': key, 'options': self._period_options(), 'range': '%s - %s' % (short(start), short(end)),
                'compare': '%s - %s' % (short(prev_start), short(prev_end)), 'days': (end - start).days + 1}

    # ------------------------------------------------------------------ flows
    @staticmethod
    def _delta(cur, prev):
        if prev > 0:
            pct = round((cur - prev) / prev * 100)
            if pct > 0:
                return {'dir': 'up', 'text': '+%s%%' % pct, 'tone': 'ok'}
            if pct < 0:
                return {'dir': 'down', 'text': '%s%%' % pct, 'tone': 'bad'}
            return {'dir': 'flat', 'text': _("No change"), 'tone': 'neutral'}
        if cur > 0:
            return {'dir': 'new', 'text': _("New"), 'tone': 'ok'}
        return {'dir': 'flat', 'text': _("No activity"), 'tone': 'neutral'}

    def _flow_allowed(self, key):
        fin = self._finance_ok()
        if key == 'invoiced':
            return bool(fin and self._can('account.move'))
        if key == 'collected':
            return bool((fin or self._allowed('bank')) and self._can('ei.bank.import.line'))
        if key == 'lifted':
            return bool(self._can('ei.lifting') and (self._allowed('ops') or fin))
        return False

    def _flow(self, key, label, icon, color, unit, by_day, window):
        """One card. by_day: {date: amount}; window: the dates of the period and of the one before it."""
        days, prev_days = window
        cur = sum(by_day.get(d, 0.0) for d in days)
        prev = sum(by_day.get(d, 0.0) for d in prev_days)
        digits = 3 if unit == 'mtl' else 2
        text = (lambda v: '{:,.3f} MTL'.format(v)) if unit == 'mtl' else self._fmt
        return {
            'key': key, 'label': label, 'icon': icon, 'color': color, 'unit': unit,
            'value': round(cur, digits), 'text': text(cur), 'prev': round(prev, digits), 'prev_text': text(prev),
            'delta': self._delta(cur, prev), 'empty': not (cur or prev),
            'sub': _("Before: %s", text(prev)),
            'series': [{'iso': fields.Date.to_string(d), 'date': format_date(self.env, d, date_format='dd MMM'),
                        'v': round(by_day.get(d, 0.0), digits), 'text': text(by_day.get(d, 0.0))} for d in days],
        }

    def _flows(self, period):
        env = self.env
        key, start, end, prev_start, prev_end = self._range(period)
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        prev_days = [prev_start + timedelta(days=i) for i in range((prev_end - prev_start).days + 1)]
        window = (days, prev_days)
        out = []
        if self._flow_allowed('invoiced'):
            rows = env['account.move']._read_group(
                [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('invoice_date', '>=', prev_start), ('invoice_date', '<=', end),
                 ('company_id', 'in', env.companies.ids)], ['invoice_date:day'], ['amount_total_signed:sum'])
            out.append(self._flow('invoiced', _("Invoiced"), 'invoice', 's1', 'money', {d: t or 0.0 for d, t in rows}, window))
        if self._flow_allowed('collected'):
            by = {}
            for line in env['ei.bank.import.line'].search_fetch([('state', '=', 'posted'), ('amount', '>', 0), ('date', '>=', prev_start), ('date', '<=', end)],
                                                                ['date', 'amount']):
                by[line.date] = by.get(line.date, 0.0) + line.amount
            out.append(self._flow('collected', _("Received in the bank"), 'in', 's2', 'money', by, window))
        if self._flow_allowed('lifted'):
            rows = env['ei.lifting']._read_group([('state', '=', 'verified'), ('date', '>=', prev_start), ('date', '<=', end)], ['date:day'], ['verified_mtl:sum'])
            out.append(self._flow('lifted', _("Material lifted"), 'truck', 's3', 'mtl', {d: t or 0.0 for d, t in rows}, window))
        return out

    @api.model
    def open_flow(self, key, period=DEFAULT_PERIOD):
        """Open exactly the records a flow card added up."""
        if not self._flow_allowed(key):
            raise AccessError(_("Your role cannot open these records."))
        _key, start, end, _ps, _pe = self._range(period)
        spec = {
            'invoiced': (_("Invoiced"), 'account.move', [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('invoice_date', '>=', start), ('invoice_date', '<=', end)]),
            'collected': (_("Received in the bank"), 'ei.bank.import.line', [('state', '=', 'posted'), ('amount', '>', 0), ('date', '>=', start), ('date', '<=', end)]),
            'lifted': (_("Material lifted"), 'ei.lifting', [('state', '=', 'verified'), ('date', '>=', start), ('date', '<=', end)]),
        }[key]
        return {'type': 'ir.actions.act_window', 'name': '%s (%s - %s)' % (spec[0], format_date(self.env, start, date_format='dd MMM'), format_date(self.env, end, date_format='dd MMM')),
                'res_model': spec[1], 'domain': spec[2], 'views': self._views_for(spec[1]), 'target': 'current'}

    # ------------------------------------------------------------------ who owes most, latest documents
    def _top_owing(self, dash):
        env = self.env
        if dash is None or not self._finance_ok():
            return None
        today = fields.Date.context_today(self)
        L = env['account.move.line'].sudo()
        rows = L._read_group(dash._dom_lines('ar'), groupby=['partner_id'], aggregates=['amount_residual:sum', '__count'],
                             order='amount_residual:sum desc', limit=TOP_N)
        total = dash.ar_open
        if not rows or total <= 0:
            return None
        late = {p.id: (amt, oldest) for p, amt, oldest in L._read_group(
            dash._dom_lines('ar') + [('date_maturity', '<', today), ('partner_id', 'in', [r[0].id for r in rows])],
            groupby=['partner_id'], aggregates=['amount_residual:sum', 'date_maturity:min'])}
        out = []
        for rank, (p, a, n) in enumerate(rows, 1):
            if a <= 0:
                continue
            over, first = late.get(p.id, (0.0, None))
            out.append({'rank': rank, 'partner_id': p.id, 'name': p.name or _("(no party on the entry)"), 'amount': round(a, 2), 'text': self._fmt(a), 'items': n,
                        'pct': round(100 * a / total), 'overdue': round(over, 2), 'overdue_text': self._fmt(over) if over > 0 else '',
                        'oldest_days': (today - first).days if first and over > 0 else 0})
        return {'title': _("Who owes us most"), 'total_text': self._fmt(total), 'rows': out}

    def _recent(self):
        env, today = self.env, fields.Date.context_today(self)
        fmt = lambda d: format_date(env, d, date_format='dd MMM yyyy') if d else ''
        if self._finance_ok() and self._can('account.move'):
            rows = []
            for m in env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted')], order='invoice_date desc, id desc', limit=RECENT_N):
                late = m.payment_state in ('not_paid', 'partial') and m.invoice_date_due and m.invoice_date_due < today
                label = _("Overdue %sd", (today - m.invoice_date_due).days) if late else dict(m._fields['payment_state']._description_selection(env)).get(m.payment_state, m.payment_state)
                tone = 'bad' if late else 'ok' if m.payment_state in ('paid', 'in_payment') else 'warning'
                rows.append({'model': 'account.move', 'res_id': m.id, 'name': m.name, 'date': fmt(m.invoice_date), 'party': m.partner_id.name or '',
                             'amount': format_amount(env, m.amount_total, m.currency_id), 'status': label, 'tone': tone, 'detail': fmt(m.invoice_date_due)})
            return {'kind': 'invoices', 'title': _("Recent invoices"), 'rows': rows} if rows else None
        if self._can('ei.lifting'):
            rows = []
            for r in env['ei.lifting'].search([], order='date desc, id desc', limit=RECENT_N):
                qty = r.verified_mtl or r.claimed_mtl or 0.0
                label = dict(r._fields['state']._description_selection(env)).get(r.state, r.state)
                rows.append({'model': 'ei.lifting', 'res_id': r.id, 'name': r.name, 'date': fmt(r.date), 'party': r.customer_id.name or r.da_id.parent_partner_id.name or '',
                             'amount': '{:,.3f} MTL'.format(qty), 'status': label, 'tone': 'ok' if r.state == 'verified' else 'warning', 'detail': r.vehicle_no or ''})
            return {'kind': 'loadings', 'title': _("Recent truck loadings"), 'rows': rows} if rows else None
        return None
