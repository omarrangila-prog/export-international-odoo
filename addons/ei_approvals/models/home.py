"""The approvals block on Home: what the signed-in person made, what waits for them, and (for management) the whole picture.
Every figure is counted from the approval requests this person may see; every card opens the matching list in the approvals centre."""
from datetime import timedelta

from odoo import api, fields, models, _

from .rule import FLOW_SELECTION

MAKER_MODELS = ['ei.contract', 'ei.da', 'ei.daily.order', 'ei.cash.voucher', 'ei.lifting']


class EiHome(models.AbstractModel):
    _inherit = 'ei.home'

    @api.model
    def get_data(self, period=None):
        data = super().get_data(period)
        block = self._approvals_block()
        if block['groups']:
            data['approvals'] = block
            layout = list(data['layout'])
            # figures first; approvals belong with "what needs you": right after the decisions block, or after My Work
            anchor = next((k for k in ('decide', 'work', 'pulse', 'summary') if k in layout), None)
            layout.insert(layout.index(anchor) + 1 if anchor else 0, 'approvals')
            data['layout'] = layout
        return data

    def _approvals_block(self):
        R = self.env['ei.approval.request']
        me = self.env.user
        if not R.has_access('read'):
            return {'groups': []}                        # someone outside the business roles: nothing to show
        now = fields.Datetime.now()
        week, month = now - timedelta(days=7), now - timedelta(days=30)
        card = lambda key, label, value, sub, tab, tone='neutral', **kw: dict(key=key, label=label, value=value, sub=sub, tab=tab, tone=tone, **kw)
        groups = []
        # my entries
        drafts = 0
        for m in MAKER_MODELS:
            M = self.env[m]
            if M.has_access('read') and 'maker_id' in M._fields:
                drafts += M.search_count([('maker_id', '=', me.id), ('state', '=', 'draft')])
        mine = [('maker_id', '=', me.id)]
        waiting = R.search_count(mine + [('state', '=', 'pending')])
        returned = R.search_count(mine + [('state', 'in', ('returned', 'superseded'))])
        approved = R.search_count(mine + [('state', '=', 'approved'), ('decided_at', '>=', week)])
        if drafts or waiting or returned or approved or R.search_count(mine):
            groups.append({'title': _("My entries"), 'cards': [
                card('my_returned', _("Returned for correction"), returned, _("Correct and submit again"), 'returned', 'bad' if returned else 'neutral', mine=True),
                card('my_waiting', _("Waiting for approval"), waiting, _("Submitted, not decided yet"), 'mine'),
                card('my_approved', _("Recently approved"), approved, _("In the last 7 days"), 'approved', 'good' if approved else 'neutral', mine=True),
                card('my_drafts', _("My drafts"), drafts, _("Not submitted yet"), 'mine'),
            ]})
        # my approvals
        if R._user_is_checker():
            for_me = [('state', '=', 'pending'), ('approver_id', '=', me.id)]
            pending = R.search_count(for_me)
            overdue = R.search_count(for_me + [('is_overdue', '=', True)])
            urgent = R.search_count(for_me + ['|', ('urgent', '=', True), ('is_overdue', '=', True)])
            reviewed = R.search_count([('decided_by', '=', me.id), ('decided_at', '>=', week)])
            team = R.search_count([('submitted_at', '>=', week), ('maker_id', '!=', me.id)])
            groups.append({'title': _("My approvals"), 'cards': [
                card('ap_pending', _("Pending approvals"), pending, _("Assigned to you"), 'pending', 'info' if pending else 'neutral'),
                card('ap_urgent', _("Urgent"), urgent, _("Marked urgent or overdue"), 'urgent', 'warn' if urgent else 'neutral'),
                card('ap_overdue', _("Overdue"), overdue, _("Waiting longer than allowed"), 'urgent', 'bad' if overdue else 'neutral'),
                card('ap_reviewed', _("Recently reviewed"), reviewed, _("Decided by you, last 7 days"), 'history'),
                card('ap_team', _("Team submissions"), team, _("Entries submitted in the last 7 days"), 'all'),
            ]})
        # the whole picture, for management and administrators
        if me.has_group('ei_management_dashboard.group_ei_management') or me.has_group('base.group_system'):
            pend = R.search([('state', '=', 'pending')], order='submitted_at asc')
            oldest = pend[:1]
            decided = R.search([('state', 'in', ('approved', 'returned', 'rejected')), ('decided_at', '>=', month)])
            avg = (sum((r.decided_at - r.submitted_at).total_seconds() for r in decided) / len(decided) / 3600.0) if decided else 0.0
            by_flow = {}
            for r in pend:
                by_flow[r.flow] = by_flow.get(r.flow, 0) + 1
            exceptions = R.search_count([('state', '=', 'pending'), '|', ('needs_assignment', '=', True), ('is_overdue', '=', True)])
            groups.append({'title': _("Approvals across the company"), 'cards': [
                card('m_pending', _("Total pending"), len(pend), _("Waiting for a checker"), 'all', 'info' if pend else 'neutral', state='pending'),
                card('m_oldest', _("Oldest pending"), _("%s days", int((now - oldest.submitted_at).days)) if oldest else '-',
                     oldest.name if oldest else _("Nothing waits"), 'all', 'warn' if oldest and (now - oldest.submitted_at).days >= 2 else 'neutral', state='pending', request_id=oldest.id or False),
                card('m_avg', _("Average approval time"), _("%s h", round(avg, 1)) if decided else '-', _("Decisions in the last 30 days"), 'history'),
                card('m_returned', _("Returned entries"), R.search_count([('state', 'in', ('returned', 'superseded')), ('decided_at', '>=', month)]),
                     _("Last 30 days"), 'returned'),
                card('m_exceptions', _("Unresolved exceptions"), exceptions, _("No checker assigned, or overdue"), 'urgent', 'bad' if exceptions else 'neutral'),
            ], 'by_flow': [{'label': dict(FLOW_SELECTION)[k], 'value': v, 'flow': k} for k, v in sorted(by_flow.items(), key=lambda x: -x[1])]})
        return {'groups': groups}
