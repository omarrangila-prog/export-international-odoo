import hashlib
import hmac
import logging
import os
from datetime import timedelta

import psycopg2.errors

from odoo import _, api, fields, models

from .pin_policy import EiPinDenied, PinNotAvailable, lock_for

_logger = logging.getLogger(__name__)
_warned = set()


class EiPinCredential(models.Model):
    """The sign-in PIN of one person. Only a keyed hash (HMAC-SHA256, key kept OUTSIDE the database), never the PIN. The same PIN cannot
    belong to two people (that is what lets a PIN alone say who is signing in). Nobody, an administrator included, can read or choose
    someone else's PIN; an administrator can only remove it or lift a lock."""
    _name = 'ei.pin.credential'
    _description = 'Sign-in PIN'
    _log_access = True

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    pin_index = fields.Char(required=True, copy=False, prefetch=False)
    set_on = fields.Datetime(readonly=True)
    last_used = fields.Datetime(readonly=True)
    failed_count = fields.Integer('Wrong tries since the last good one', readonly=True, default=0)
    locked_until = fields.Datetime('Paused until', readonly=True)
    hard_locked = fields.Boolean('Locked until unlocked', readonly=True)

    _user_uniq = models.Constraint('unique(user_id)', 'A person has one PIN.')
    _pin_uniq = models.Constraint('unique(pin_index)', 'That PIN cannot be used.')

    # ---- keyed hash. 10 000 PINs can be tried in a blink by anyone who has BOTH the database and the key, so the key lives in the server's
    # environment (EI_PIN_PEPPER), not in the database. Without it the fallback is the database's own secret: it works, and protects
    # nothing if the database is copied (a warning says so once).
    @api.model
    def _pepper(self):
        key = os.environ.get('EI_PIN_PEPPER')
        if key:
            return key
        if self.env.cr.dbname not in _warned:
            _warned.add(self.env.cr.dbname)
            _logger.warning('EI_PIN_PEPPER is not set: sign-in PINs are keyed with the database secret, which protects nothing if the '
                            'database is copied. Set EI_PIN_PEPPER in the server environment (docs/pin_login.md).')
        return self.env['ir.config_parameter'].sudo().get_str('database.secret', 'ei')

    @api.model
    def _index(self, pin):
        return hmac.new(self._pepper().encode(), f'ei-pin:{pin}'.encode(), hashlib.sha256).hexdigest()

    # ---- set / remove (the person, after proving the password) and reset / unlock (an administrator)
    @api.model
    def _set_pin(self, user, pin):
        """Stores the PIN. No quality rule here (a person's PIN is checked by check_new_pin before; an operator provisioning a first PIN
        decides for themselves); the only refusal is a PIN that already belongs to somebody else."""
        index = self._index(pin)
        if self.sudo().search_count([('pin_index', '=', index), ('user_id', '!=', user.id)]):
            raise PinNotAvailable(_('That PIN cannot be used. Choose another.'))
        vals = {'pin_index': index, 'set_on': fields.Datetime.now(), 'failed_count': 0, 'locked_until': False, 'hard_locked': False}
        cred = self.sudo().search([('user_id', '=', user.id)])
        if cred:
            cred.write(vals)
        else:
            self.sudo().create(dict(vals, user_id=user.id))

    def _lift_lock(self):
        self.sudo().write({'failed_count': 0, 'locked_until': False, 'hard_locked': False})

    @api.model
    def _user_for_pin(self, pin):
        """Whose PIN is this? (empty recordset when nobody's.) Used by the sign-in with the PIN alone."""
        return self.sudo().search([('pin_index', '=', self._index(pin))], limit=1).user_id

    # ---- the check itself. One transaction of its own that is committed whatever happens to the request, with the row held, so two
    # guesses at the same moment cannot both be counted as the first. The refusal is raised only after the commit.
    @api.model
    def _verify(self, user, pin):
        wanted = self._index(pin)
        reason = 'wrong_pin'
        try:
            with self.pool.cursor() as cr:
                cr.execute('SELECT id, pin_index, failed_count, locked_until, hard_locked FROM ei_pin_credential WHERE user_id = %s FOR UPDATE', [user.id])
                row = cr.fetchone()
                if not row:
                    reason = 'not_set'
                else:
                    cid, stored, failed, locked_until, hard = row
                    failed = failed or 0
                    if hard:
                        reason = 'locked_hard'
                    elif locked_until and locked_until > fields.Datetime.now():
                        reason = 'paused'
                    elif hmac.compare_digest(stored, wanted):
                        cr.execute('UPDATE ei_pin_credential SET failed_count = 0, locked_until = NULL, last_used = %s WHERE id = %s', [fields.Datetime.now(), cid])
                        return {'uid': user.id, 'auth_method': 'ei_pin', 'mfa': 'default'}
                    else:
                        failed += 1
                        seconds, hard = lock_for(failed)
                        until = fields.Datetime.now() + timedelta(seconds=seconds) if seconds else None
                        cr.execute('UPDATE ei_pin_credential SET failed_count = %s, locked_until = COALESCE(%s, locked_until), hard_locked = %s WHERE id = %s',
                                   [failed, until, hard, cid])
                        if seconds or hard:
                            _logger.warning('Sign-in PIN of user %s paused after %d wrong tries (%s)', user.id, failed, 'until unlocked' if hard else f'{seconds} s')
        except psycopg2.errors.SerializationFailure:
            reason = 'busy'
        raise EiPinDenied(reason)
