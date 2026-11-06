"""Dark mode. Odoo 20 Community ships the dark asset bundle but always answers "light": there we answer from the viewer's own
choice, the `color_scheme` cookie that the Home theme button sets (the same cookie Odoo's charts already read), and nothing is
stored on the server. Enterprise has its own answer, a setting per person that its web client enforces on the cookie, so there
we leave the decision to it and the Home button changes that setting."""
from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def color_scheme(self):
        if 'color_scheme' in self.env['res.users.settings']._fields:
            return super().color_scheme()
        choice = request.httprequest.cookies.get('color_scheme') if request else None
        if choice in ('dark', 'light'):
            return choice
        return super().color_scheme()

    def session_info(self):
        """The top bar shows a badge when this database is not the live one (an administrator sets the label in System Parameters:
        `ei.environment_label`, for example "STAGING - synthetic demo data"). Nothing is shown when the parameter is empty."""
        res = super().session_info()
        res['ei_environment_label'] = self.env['ir.config_parameter'].sudo().get_str('ei.environment_label', '')
        return res
