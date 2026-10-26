from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """The user menu offers "Sign-in PIN" only to a person who may have one."""
        res = super().session_info()
        user = self.env.user
        res['ei_pin_allowed'] = bool(user and not user._is_public() and user._ei_pin_allowed())
        return res
