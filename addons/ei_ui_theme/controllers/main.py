from odoo.addons.web.controllers.home import Home
from odoo.http import request, route


class EiHome(Home):
    @route()
    def web_login(self, redirect=None, **kw):
        """The sign-in page says which system it is, so nobody enters live figures into the staging copy (or the reverse)."""
        response = super().web_login(redirect=redirect, **kw)
        if hasattr(response, 'qcontext'):
            response.qcontext['ei_environment'] = request.env['ir.config_parameter'].sudo().get_str('ei.environment_label', '')
        return response
