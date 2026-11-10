from . import models


def post_init_hook(env):
    """The client's confirmed process (Nov 2026): maker-checker. Every workflow this module connects starts with approval ON;
    an administrator may still switch one off under Settings > Export International."""
    env['ei.approval.policy'].sudo().set_all(True)
