import os

from odoo import _, models


class EiHome(models.AbstractModel):
    _inherit = 'ei.home'

    def _system(self):
        """The administrator's checks on Home gain one line about signing in with a PIN: is the key kept outside the database, is anybody
        guessing, and from where may a PIN be used."""
        res = super()._system()
        Log = self.env['ei.pin.log']
        refused, paused = Log._pin_only_refused(24), Log._pin_only_paused()
        networks = self.env['ir.config_parameter'].sudo().get_str('ei.pin.allowed_networks', '').strip()
        people = self.env['ei.pin.credential'].sudo().search_count([])
        if not people and not refused:
            return res
        if paused:
            ok, text = False, _("Resting: %s refused PIN sign-ins in 24 hours. Someone may be guessing PINs; see Setup > Sign-in PIN activity", refused)
        elif refused >= 10:
            ok, text = False, _("%s refused PIN sign-ins in 24 hours; see Setup > Sign-in PIN activity", refused)
        elif not os.environ.get('EI_PIN_PEPPER'):
            ok, text = False, _("The key that protects PINs is not set in the server's environment (EI_PIN_PEPPER); see docs/pin_login.md")
        else:
            ok, text = True, _("%(p)s people have a PIN; %(r)s refused sign-ins in 24 hours; %(n)s", p=people, r=refused,
                               n=_("PIN sign-in only from %s", networks) if networks else _("PIN sign-in is open from any network"))
        res['checks'].append(dict(label=_("Signing in with a PIN"), ok=ok, text=text))
        return res
