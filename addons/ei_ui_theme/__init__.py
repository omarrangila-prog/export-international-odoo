from . import models
from . import controllers


def post_init_hook(env):
    """Existing users: switch off the onboarding pointers (they cover the menu)."""
    users = env['res.users'].sudo().search([])
    users.write({'tour_enabled': False})
    users._ei_set_home()
