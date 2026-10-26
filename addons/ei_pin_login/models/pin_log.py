from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models

from .pin_policy import IP_LIMIT, IP_WINDOW_SECONDS, PIN_ONLY_DAY_LIMIT, PIN_ONLY_HOUR_LIMIT, SET_REFUSED_LIMIT


class EiPinLog(models.Model):
    """Every PIN sign-in attempt and every change to a PIN, who and from where. It never holds a PIN, right or wrong. Kept 180 days."""
    _name = 'ei.pin.log'
    _description = 'Sign-in PIN activity'
    _order = 'id desc'

    at = fields.Datetime('When', default=fields.Datetime.now, readonly=True, index=True)
    event = fields.Selection([('signin', 'PIN sign-in'), ('set', 'PIN set or changed'), ('removed', 'PIN removed by the person'),
                              ('reset', 'PIN removed by an administrator'), ('unlocked', 'Lock lifted by an administrator')],
                             required=True, readonly=True)
    success = fields.Boolean('Worked', readonly=True)
    reason = fields.Char('What happened', readonly=True)
    login = fields.Char('Name typed', readonly=True)
    user_id = fields.Many2one('res.users', 'Person', readonly=True, ondelete='set null', index=True)
    actor_id = fields.Many2one('res.users', 'Done by', readonly=True, ondelete='set null')
    ip = fields.Char('From address', readonly=True, index=True)
    pin_only = fields.Boolean('PIN alone', readonly=True, help='Signed in (or tried to) with the PIN and no user name.')

    @api.model
    def _write_apart(self, vals):
        """Written in its own transaction and committed at once: a refused sign-in rolls the request back, the record of it must not go."""
        with self.pool.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            env['ei.pin.log'].create(vals)

    @api.model
    def _ip_throttled(self, ip):
        if not ip or ip == 'n/a':
            return False
        since = fields.Datetime.now() - timedelta(seconds=IP_WINDOW_SECONDS)
        return self.sudo().search_count([('event', '=', 'signin'), ('success', '=', False), ('ip', '=', ip), ('at', '>=', since)]) >= IP_LIMIT

    @api.model
    def _pin_only_refused(self, hours):
        since = fields.Datetime.now() - timedelta(hours=hours)
        return self.sudo().search_count([('event', '=', 'signin'), ('success', '=', False), ('pin_only', '=', True), ('at', '>=', since)])

    @api.model
    def _pin_only_paused(self):
        """Too many refused PIN-only sign-ins lately, from anywhere: PIN sign-in rests for everybody (the password still works)."""
        return self._pin_only_refused(1) >= PIN_ONLY_HOUR_LIMIT or self._pin_only_refused(24) >= PIN_ONLY_DAY_LIMIT

    @api.model
    def _set_refused_recently(self, user):
        return self.sudo().search_count([('event', '=', 'set'), ('success', '=', False), ('actor_id', '=', user.id),
                                         ('at', '>=', fields.Datetime.now() - timedelta(hours=1))]) >= SET_REFUSED_LIMIT

    @api.autovacuum
    def _gc_old_activity(self):
        self.sudo().search([('at', '<', fields.Datetime.now() - timedelta(days=180))]).unlink()
