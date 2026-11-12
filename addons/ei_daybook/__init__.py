from . import models


def post_init_hook(env):
    """Maker-checker is the client's process (Nov 2026): online and cash book entries start with approval ON."""
    env['ir.config_parameter'].sudo().set_bool('ei_approval.daybook', True)
