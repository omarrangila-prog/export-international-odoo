from odoo import Command


def give_the_administrator_the_app(env):
    """So the app is on the main screen straight after installing. Only the administrator; everyone else gets a role from Settings > Users."""
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if admin:
        admin.write({'group_ids': [Command.link(env.ref('ei_management_dashboard.group_ei_management').id)]})
