import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.http import request

from .pin_policy import PIN_RE, EiPinDenied, check_new_pin

_logger = logging.getLogger(__name__)
DEFAULT_BLOCKED = 'base.group_system'


class ResUsers(models.Model):
    _inherit = 'res.users'

    ei_pin_state = fields.Selection([('none', 'No PIN'), ('set', 'PIN set'), ('paused', 'PIN paused after wrong tries'), ('locked', 'PIN locked')],
                                    string='Sign-in PIN', compute='_compute_ei_pin_state', groups='base.group_system')
    ei_pin_set_on = fields.Datetime('PIN set on', compute='_compute_ei_pin_state', groups='base.group_system')
    ei_pin_last_used = fields.Datetime('PIN last used', compute='_compute_ei_pin_state', groups='base.group_system')
    ei_pin_allowed = fields.Boolean('May use a PIN', compute='_compute_ei_pin_state', groups='base.group_system')

    def _compute_ei_pin_state(self):
        creds = {c.user_id.id: c for c in self.env['ei.pin.credential'].sudo().search([('user_id', 'in', self.ids)])}
        now = fields.Datetime.now()
        for user in self:
            c = creds.get(user.id)
            user.ei_pin_set_on = c.set_on if c else False
            user.ei_pin_last_used = c.last_used if c else False
            user.ei_pin_allowed = user._ei_pin_allowed()
            if not c:
                user.ei_pin_state = 'none'
            elif c.hard_locked:
                user.ei_pin_state = 'locked'
            elif c.locked_until and c.locked_until > now:
                user.ei_pin_state = 'paused'
            else:
                user.ei_pin_state = 'set'

    # ---- policy: the feature switch and the roles that must sign in with the password
    @api.model
    def _ei_pin_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_bool('ei.pin.enabled', True)

    def _ei_pin_blocked_groups(self):
        names = self.env['ir.config_parameter'].sudo().get_str('ei.pin.blocked_groups', DEFAULT_BLOCKED)
        return [n.strip() for n in names.split(',') if '.' in n]       # a value without a dot (write `none`) reserves no role

    def _ei_pin_allowed(self):
        """May this person sign in with a PIN at all? Not when the feature is off, and not when they hold a role that has been
        reserved for the password (by default only the system administrator; Settings > Technical > System Parameters)."""
        self.ensure_one()
        if not self._ei_pin_enabled():
            return False
        user = self.sudo()
        return not any(user.has_group(g) for g in self._ei_pin_blocked_groups() if self.env['ir.model.data']._xmlid_to_res_id(g, raise_if_not_found=False))

    # ---- signing in
    @api.model
    def _login(self, credential, user_agent_env):
        if credential.get('type') != 'ei_pin':
            return super()._login(credential, user_agent_env)
        Log = self.env['ei.pin.log']
        login = (credential.get('login') or '')[:80]
        ip = request.httprequest.remote_addr if request else 'n/a'
        if Log._ip_throttled(ip):
            raise AccessDenied(_('Too many login failures, please wait a bit before trying again.'))
        try:
            auth_info = super()._login(credential, user_agent_env)
        except EiPinDenied as e:
            Log._write_apart({'event': 'signin', 'success': False, 'reason': e.reason, 'login': login, 'ip': ip, 'user_id': e.user_id})
            raise
        except AccessDenied as e:
            reason = 'unknown_name' if e.args == AccessDenied().args else 'cooling_down'
            if reason == 'unknown_name':
                self.env['ei.pin.credential']._dummy_verify(credential.get('password') or '')     # take as long as for a real name
            # an unknown name is not kept: people sometimes type their password into the name box
            Log._write_apart({'event': 'signin', 'success': False, 'reason': reason, 'login': '(not a known name)', 'ip': ip})
            raise
        Log._write_apart({'event': 'signin', 'success': True, 'reason': 'ok', 'login': login, 'ip': ip, 'user_id': auth_info['uid']})
        return auth_info

    def _check_credentials(self, credential, env):
        if credential.get('type') != 'ei_pin':
            return super()._check_credentials(credential, env)
        self.ensure_one()
        try:
            if not (env or {}).get('interactive', True):
                raise EiPinDenied('not_interactive')       # a PIN opens the web page only, never the programming interfaces
            if not self._ei_pin_enabled():
                raise EiPinDenied('switched_off')
            if not self._ei_pin_allowed():
                self.env['ei.pin.credential']._dummy_verify(credential.get('password') or '')     # no quicker an answer for a reserved role
                raise EiPinDenied('role_not_allowed')
            pin = credential.get('password') or ''
            if not PIN_RE.fullmatch(pin):
                raise EiPinDenied('not_four_digits')
            return self.env['ei.pin.credential']._verify(self.sudo(), pin)
        except EiPinDenied as e:
            e.user_id = self.id
            raise

    def write(self, vals):
        res = super().write(vals)
        if vals.get('password'):
            # a password set by SOMEONE ELSE (an administrator after a doubt, a reset link) also removes the PIN: whoever held the old
            # secrets must not keep a way in. A person changing their own password keeps their PIN.
            others = self.filtered(lambda u: u != self.env.user)
            creds = self.env['ei.pin.credential'].sudo().search([('user_id', 'in', others.ids)]) if others else self.env['ei.pin.credential']
            for cred in creds:
                self.env['ei.pin.log']._write_apart({'event': 'reset', 'success': True, 'reason': 'password changed by someone else', 'user_id': cred.user_id.id,
                                                     'actor_id': self.env.user.id, 'login': cred.user_id.login, 'ip': request.httprequest.remote_addr if request else 'n/a'})
            creds.unlink()
        return res

    # ---- what the signed-in person can do with their own PIN
    @api.model
    def ei_pin_info(self):
        user = self.env.user
        cred = self.env['ei.pin.credential'].sudo().search([('user_id', '=', user.id)])
        return {'enabled': self._ei_pin_enabled(), 'allowed': user._ei_pin_allowed(), 'has_pin': bool(cred),
                'set_on': fields.Datetime.to_string(cred.set_on) if cred else False}

    def _ei_pin_require_password(self, password):
        user = self.env.user
        if not password:
            raise UserError(_('Type your password to confirm it is you.'))
        try:
            with user._assert_can_auth(user=user.login):
                user._check_credentials({'type': 'password', 'password': password}, {'interactive': True})
        except AccessDenied:
            raise UserError(_('That password is not right.'))

    @api.model
    def ei_set_pin(self, password, pin, confirm):
        """The person sets or changes their own PIN. Needs the password, so a borrowed, unlocked screen cannot plant a PIN."""
        user = self.env.user
        if not user._ei_pin_allowed():
            raise AccessError(_('A PIN cannot be used for this account. Sign in with your password.'))
        self._ei_pin_require_password(password)
        check_new_pin(pin, confirm)
        self.env['ei.pin.credential']._set_pin(user, pin)
        self.env['ei.pin.log']._write_apart({'event': 'set', 'success': True, 'user_id': user.id, 'actor_id': user.id, 'login': user.login,
                                             'ip': request.httprequest.remote_addr if request else 'n/a'})
        return True

    @api.model
    def ei_remove_pin(self, password):
        user = self.env.user
        self._ei_pin_require_password(password)
        self.env['ei.pin.credential'].sudo().search([('user_id', '=', user.id)]).unlink()
        self.env['ei.pin.log']._write_apart({'event': 'removed', 'success': True, 'user_id': user.id, 'actor_id': user.id, 'login': user.login,
                                             'ip': request.httprequest.remote_addr if request else 'n/a'})
        return True

    # ---- what an administrator can do for someone else: remove the PIN or lift a lock. Never read it, never choose it.
    def _ei_pin_admin_only(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can do this.'))

    def action_ei_pin_reset(self):
        self._ei_pin_admin_only()
        for user in self:
            self.env['ei.pin.credential'].sudo().search([('user_id', '=', user.id)]).unlink()
            self.env['ei.pin.log']._write_apart({'event': 'reset', 'success': True, 'user_id': user.id, 'actor_id': self.env.user.id, 'login': user.login,
                                                 'ip': request.httprequest.remote_addr if request else 'n/a'})
        return True

    def action_ei_pin_unlock(self):
        self._ei_pin_admin_only()
        for user in self:
            self.env['ei.pin.credential'].sudo().search([('user_id', '=', user.id)])._lift_lock()
            self.env['ei.pin.log']._write_apart({'event': 'unlocked', 'success': True, 'user_id': user.id, 'actor_id': self.env.user.id, 'login': user.login,
                                                 'ip': request.httprequest.remote_addr if request else 'n/a'})
        return True
