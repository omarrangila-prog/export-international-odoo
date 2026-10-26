"""The automation recipes: plain code, reviewed, never written by a user.

A business owner can switch a recipe on or off and change its numbers (days, repeat window, cap). Nobody can change what it
does. Every recipe is READ-ONLY: it looks at real records and returns findings. The only thing the rule engine does with a
finding is an internal reminder (an Odoo activity) for a colleague. No recipe posts, pays, sends anything outside the company
or changes a business record. Thresholds below are PROPOSED defaults: the business has not yet fixed any deadline.
"""
from collections import namedtuple
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import fields, _
from odoo.tools.misc import format_amount
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

# record: the record the reminder is attached to; owners: res.users to tell; summary: one line; note: Markup body
Finding = namedtuple('Finding', 'record owners summary note')

MANAGEMENT_GROUP = 'ei_management_dashboard.group_ei_management'


def managers(env):
    return env.ref(MANAGEMENT_GROUP).sudo().user_ids.filtered(lambda u: u.active and not u.share)


def owners_for(env, record, *preferred):
    """The colleague(s) who should be told about this record: the preferred person if they are still an active internal user who
    may read it, otherwise the managers. A reminder is never given to someone who cannot open the record."""
    people = env['res.users']
    for u in preferred:
        if u and u.active and not u.share and record.with_user(u).has_access('read'):
            people |= u
    return people or managers(env).filtered(lambda u: record.with_user(u).has_access('read'))


def _p(*parts):
    return Markup('').join(Markup('<p>%s</p>') % p for p in parts if p)


def _now(env):
    return fields.Datetime.now()


# ---------------------------------------------------------------------------------------------------- A17
def missing_supplier_invoice(env, rule):
    cutoff = _now(env) - timedelta(days=rule.days)
    out = []
    for o in env['ei.daily.order'].search([('state', '=', 'approved'), ('approved_at', '<=', cutoff),
                                           ('company_id', '=', rule.company_id.id)], order='approved_at'):
        missing = o.line_ids.filtered(lambda l: not l.invoice_ref)
        if not missing:
            continue
        age = (_now(env) - o.approved_at).days
        lines = ', '.join('%s (%.3f MTL)' % (l.da_id.name, l.requested_mtl) for l in missing)
        out.append(Finding(o, owners_for(env, o, o.maker_id), _("Supplier invoice still missing: %s", o.name), _p(
            _("%(o)s for %(s)s was approved %(n)s days ago, and no supplier invoice number has been recorded for: %(l)s.",
              o=o.name, s=o.parent_partner_id.name, n=age, l=lines),
            _("Ask the parent company for the invoice and enter it on the order. Nothing is booked from this reminder."))))
    return out


# ---------------------------------------------------------------------------------------------------- A18
def lifting_waiting(env, rule):
    now, today = _now(env), fields.Date.context_today(env['ei.rule'])
    cutoff = now - timedelta(days=rule.days)
    since = today - timedelta(days=rule.days)
    out = []
    for o in env['ei.daily.order'].search([('state', '=', 'approved'), ('approved_at', '<=', cutoff),
                                           ('company_id', '=', rule.company_id.id)], order='approved_at'):
        waiting = []
        for line in o.line_ids.filtered(lambda l: l.remaining_mtl > 0.0005):
            last = env['ei.lifting'].search([('order_line_id', '=', line.id), ('state', 'in', ('draft', 'verified'))], order='date desc', limit=1)
            if last and last.date >= since:
                continue                                # something is moving on this line
            waiting.append('%s: %.3f MTL still to lift, %s' % (
                line.da_id.name, line.remaining_mtl, _("last loading on %s", last.date) if last else _("nothing loaded yet")))
        if not waiting:
            continue
        age = (now - o.approved_at).days
        out.append(Finding(o, owners_for(env, o, o.maker_id), _("Material waiting to be lifted: %s", o.name), _p(
            _("%(o)s was approved %(n)s days ago and these lines have had no truck loading for %(d)s days or more:", o=o.name, n=age, d=rule.days),
            Markup('<br/>').join(escape(w) for w in waiting),
            _("Check with the parent company and the dispatch team. A supplier invoice does not mean the material was lifted."))))
    return out


# ---------------------------------------------------------------------------------------------------- A19
def overdue_collection(env, rule):
    today = fields.Date.context_today(env['ei.rule'])
    limit = today - timedelta(days=rule.days)
    out = []
    for m in env['account.move'].search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('company_id', '=', rule.company_id.id),
                                         ('payment_state', 'in', ('not_paid', 'partial')), ('invoice_date_due', '<', limit)],
                                        order='invoice_date_due'):
        late = (today - m.invoice_date_due).days
        money = format_amount(env, m.amount_residual, m.currency_id)
        # never chase a customer whose money may already be in the bank file: say so
        pend = env['ei.bank.import.line'].search([('suggested_partner_id', 'child_of', m.partner_id.id),
                                                  ('state', 'in', ('new', 'proposed', 'verified', 'unidentified')), ('amount', '>', 0)])
        warn = _("Before you chase: %(n)s bank payment(s) worth %(a)s are waiting to be matched for this customer and may already cover it.",
                 n=len(pend), a=format_amount(env, sum(pend.mapped('amount')), m.currency_id)) if pend else False
        draft = _("Dear %(c)s, our records show invoice %(i)s for %(a)s was due on %(d)s, %(n)s days ago. Please arrange payment, or if you have "
                  "already paid, send us the payment reference so we can match it. Thank you. - %(co)s",
                  c=m.partner_id.name, i=m.name, a=money, d=m.invoice_date_due, n=late, co=env.company.name)
        out.append(Finding(m, owners_for(env, m, m.invoice_user_id, m.create_uid), _("Customer payment overdue: %s", m.name), _p(
            _("%(i)s for %(c)s is %(n)s days past its due date. Still unpaid in the books: %(a)s.", i=m.name, c=m.partner_id.name, n=late, a=money),
            warn, Markup('<b>%s</b>') % _("Draft reminder - read it, change it, and send it yourself:"), Markup('<i>%s</i>') % draft,
            _("This reminder is only a draft. Nothing is sent to the customer from here."))))
    return out


# ---------------------------------------------------------------------------------------------------- A24
def critical_anomaly(env, rule):
    now = _now(env)
    cutoff = now - timedelta(days=rule.days)
    boss = managers(env)
    out = []

    def add(rec, why, detail):
        owners = boss.filtered(lambda u: rec.with_user(u).has_access('read'))
        out.append(Finding(rec, owners, why, _p(detail, _("The managers are told because this needs a decision, not routine work."))))
    for l in env['ei.bank.import.line'].search([('state', '=', 'duplicate'), ('company_id', '=', rule.company_id.id)]):
        add(l, _("Possible duplicate bank payment: %s", l.display_name),
            _("The same bank line appeared twice (%(r)s). Do not post both.", r=l.display_name))
    for l in env['ei.bank.import.line'].search([('state', '=', 'unidentified'), ('create_date', '<=', cutoff), ('company_id', '=', rule.company_id.id)]):
        add(l, _("Money nobody has identified: %s", l.display_name),
            _("%(r)s arrived more than %(d)s days ago and nobody has said who paid. It stays out of the books until someone confirms.", r=l.display_name, d=rule.days))
    for i in env['ei.supplier.intake'].search([('state', '=', 'mismatch'), ('write_date', '<=', cutoff), ('company_id', '=', rule.company_id.id)]):
        add(i, _("Supplier invoice stuck in mismatch: %s", i.invoice_number),
            _("Supplier invoice %(n)s from %(s)s has not matched the delivery advice for more than %(d)s days.", n=i.invoice_number, s=i.partner_id.name, d=rule.days))
    return out


# key -> everything the screen needs to explain the recipe honestly, plus the code that finds records
RECIPES = {
    'missing_supplier_invoice': dict(
        code='A17', name=_lt("Supplier invoice missing after an order was approved"), find=missing_supplier_invoice, default_days=3,
        days_label=_lt("Days after approval"), owner=_lt("The person who prepared the order"),
        checks=_lt("Approved daily orders where at least one line has no supplier invoice number, and approval was at least N days ago."),
        does=_lt("Gives the person who prepared the order a reminder on the order."),
        owner_text=_lt("The person who prepared the order (the managers if that person can no longer open it).")),
    'lifting_waiting': dict(
        code='A18', name=_lt("Approved material not lifted for N days"), find=lifting_waiting, default_days=5,
        days_label=_lt("Days without a truck loading"), owner=_lt("The person who prepared the order"),
        checks=_lt("Approved daily orders with material still to lift, and no truck loading (draft or verified) on that line for N days."),
        does=_lt("Gives the person who prepared the order a reminder on the order."),
        owner_text=_lt("The person who prepared the order (the managers if that person can no longer open it).")),
    'overdue_collection': dict(
        code='A19', name=_lt("Customer invoice overdue (draft reminder)"), find=overdue_collection, default_days=7,
        days_label=_lt("Days past the due date"), owner=_lt("The invoice's salesperson or creator"),
        checks=_lt("Posted customer invoices still unpaid in the books, more than N days past the due date. It also warns when unmatched bank payments for that customer may already cover it."),
        does=_lt("Gives the invoice owner a reminder with a DRAFT wording to review. Nothing is sent to the customer."),
        owner_text=_lt("The invoice's salesperson, else its creator (the managers if neither can open it).")),
    'critical_anomaly': dict(
        code='A24', name=_lt("Problems that need a manager"), find=critical_anomaly, default_days=1,
        days_label=_lt("Days before managers are told"), owner=_lt("Every manager"),
        checks=_lt("Possible duplicate bank payments (at once), bank money nobody has identified, and supplier invoices stuck in mismatch, once older than N days."),
        does=_lt("Gives each manager a reminder on the record."), owner_text=_lt("Every user with the management role.")),
}
