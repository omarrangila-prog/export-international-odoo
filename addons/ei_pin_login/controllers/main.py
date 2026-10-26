from odoo import _
from odoo.addons.ei_ui_theme.controllers.main import EiHome
from odoo.http import request, route


class EiPinHome(EiHome):
    @route()
    def web_login(self, redirect=None, **kw):
        """Second way in: the four-digit PIN (alone, or with a user name when `ei.pin.only_enabled` is off). The PIN field is called `ei_pin` (so that nothing that looks for the password
        field is confused); here it is handed to Odoo as the credential of type `ei_pin`. Everything else (database, redirect, cooldown,
        two-step sign-in) is Odoo's own."""
        enabled = request.env['res.users'].sudo()._ei_pin_enabled()
        wants_pin = enabled and request.httprequest.method == 'POST' and request.params.get('type') == 'ei_pin'
        if wants_pin:
            request.params['password'] = request.params.get('ei_pin') or ''
            request.params.pop('ei_pin', None)
        response = super().web_login(redirect=redirect, **kw)
        if hasattr(response, 'qcontext'):
            q = response.qcontext
            q['ei_pin_enabled'] = enabled
            q['ei_pin_only'] = enabled and request.env['res.users'].sudo()._ei_pin_only_enabled()
            q['ei_login_mode'] = 'pin' if (wants_pin or (enabled and request.params.get('mode') == 'pin')) else ''
            if wants_pin and q.get('error') == _('Wrong login/password'):
                q['error'] = _('That did not work. Check the four digits, or use the Password tab. '
                               'After several wrong tries, signing in with a PIN rests for a while.')
        return response
