from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields, models

from .pin_policy import IP_LIMIT, IP_WINDOW_SECONDS


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

    @api.autovacuum
    def _gc_old_activity(self):
        self.sudo().search([('at', '<', fields.Datetime.now() - timedelta(days=180))]).unlink()
