"""Dark mode. Odoo 20 Community ships the dark asset bundle but always answers "light"; Enterprise overrides the answer.
We answer from the viewer's own choice: the `color_scheme` cookie that the Home theme button sets (the same cookie
Odoo's charts already read). Nothing is stored on the server; the choice follows the browser."""
from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def color_scheme(self):
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
