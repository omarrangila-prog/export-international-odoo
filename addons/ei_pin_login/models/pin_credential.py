import logging
from datetime import timedelta

import psycopg2.errors
from passlib.context import CryptContext

from odoo import api, fields, models
from odoo.addons.base.models.res_users import MIN_ROUNDS

from .pin_policy import EiPinDenied, lock_for

_logger = logging.getLogger(__name__)
_DUMMY = {}


class EiPinCredential(models.Model):
    """The sign-in PIN of one person: only a salted hash, never the PIN, and the count of wrong tries. Nobody (an administrator
    included) can read or choose someone else's PIN; an administrator can only remove it or lift a lock."""
    _name = 'ei.pin.credential'
    _description = 'Sign-in PIN'
    _log_access = True

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    pin_hash = fields.Char(required=True, copy=False, prefetch=False)
    set_on = fields.Datetime(readonly=True)
    last_used = fields.Datetime(readonly=True)
    failed_count = fields.Integer('Wrong tries since the last good one', readonly=True, default=0)
    locked_until = fields.Datetime('Paused until', readonly=True)
    hard_locked = fields.Boolean('Locked until unlocked', readonly=True)

    _user_uniq = models.Constraint('unique(user_id)', 'A person has one PIN.')

    # ---- hashing: pbkdf2-sha512 with a random salt per PIN, bound to the account so a copied hash does not work for another person
    @api.model
    def _context(self):
        rounds = max(MIN_ROUNDS, self.env['ir.config_parameter'].sudo().get_int('password.hashing.rounds'))
        return CryptContext(['pbkdf2_sha512'], pbkdf2_sha512__rounds=rounds)

    @api.model
    def _secret(self, user_id, pin):
        return f'{user_id}:{pin}'

    @api.model
    def _hash(self, user_id, pin):
        return self._context().hash(self._secret(user_id, pin))

    @api.model
    def _dummy_verify(self, pin):
        """Spend the same time on a person who has no PIN (or is paused) as on one who has, so the answer does not give the name away."""
        ctx = self._context()
        key = id(self.env.registry)
        if key not in _DUMMY:
            _DUMMY[key] = ctx.hash('0:0000')
        ctx.verify(self._secret(0, pin), _DUMMY[key])

    # ---- set / remove (the person, after proving the password) and reset / unlock (an administrator)
    @api.model
    def _set_pin(self, user, pin):
        now = fields.Datetime.now()
        vals = {'pin_hash': self._hash(user.id, pin), 'set_on': now, 'failed_count': 0, 'locked_until': False, 'hard_locked': False}
        cred = self.sudo().search([('user_id', '=', user.id)])
        if cred:
            cred.write(vals)
        else:
            self.sudo().create(dict(vals, user_id=user.id))

    def _lift_lock(self):
        self.sudo().write({'failed_count': 0, 'locked_until': False, 'hard_locked': False})

    # ---- the check itself. One transaction of its own that is committed whatever happens to the request, with the row held, so two
    # guesses at the same moment cannot both be counted as the first. The refusal is raised only after the commit.
    @api.model
    def _verify(self, user, pin):
        ctx = self._context()
        reason = 'wrong_pin'
        try:
            with self.pool.cursor() as cr:
                cr.execute('SELECT id, pin_hash, failed_count, locked_until, hard_locked FROM ei_pin_credential WHERE user_id = %s FOR UPDATE', [user.id])
                row = cr.fetchone()
                if not row:
                    self._dummy_verify(pin)
                    reason = 'not_set'
                else:
                    cid, pin_hash, failed, locked_until, hard = row
                    failed = failed or 0
                    if hard:
                        self._dummy_verify(pin)
                        reason = 'locked_hard'
                    elif locked_until and locked_until > fields.Datetime.now():
                        self._dummy_verify(pin)
                        reason = 'paused'
                    else:
                        valid, replacement = ctx.verify_and_update(self._secret(user.id, pin), pin_hash)
                        if valid:
                            cr.execute('UPDATE ei_pin_credential SET failed_count = 0, locked_until = NULL, last_used = %s, pin_hash = %s WHERE id = %s',
                                       [fields.Datetime.now(), replacement or pin_hash, cid])
                            return {'uid': user.id, 'auth_method': 'ei_pin', 'mfa': 'default'}
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
