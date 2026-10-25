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
