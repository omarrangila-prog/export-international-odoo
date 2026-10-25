from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        for v in vals_list:
            v.setdefault('tour_enabled', False)   # no pop-up tutorial pointers for office staff
        users = super().create(vals_list)
        users._ei_set_home()
        return users

    def write(self, vals):
        res = super().write(vals)
        if 'group_ids' in vals:
            self._ei_set_home()
        return res

    def _ei_set_home(self):
        """Staff with any Export International role land on the guided Home page after login (set once)."""
        home = self.env.ref('ei_ui_theme.action_ei_home', raise_if_not_found=False)
        group = self.env.ref('ei_legacy_master.group_ei_user', raise_if_not_found=False)
        if not (home and group):
            return
        for u in self.sudo().filtered(lambda x: not x.action_id and x._is_internal() and x.has_group('ei_legacy_master.group_ei_user')):
            u.action_id = home.id
