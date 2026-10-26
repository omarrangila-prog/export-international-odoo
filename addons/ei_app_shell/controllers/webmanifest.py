from odoo.addons.web.controllers.webmanifest import WebManifest
from odoo.http import request

ICONS = '/ei_app_shell/static/img/'
COLOUR = '#F4F6FA'          # the page colour: the phone's status bar and the splash screen match the app instead of Odoo's purple


class EiWebManifest(WebManifest):
    """What the phone or the browser reads when someone installs the app: our name, our icons, our colours. Odoo's own manifest named the app
    "Odoo", used its purple and icons, and offered to receive shared files."""

    def _get_webmanifest(self):
        name = request.env['ir.config_parameter'].sudo().get_str('web.web_app_name', '') or 'Export International'
        return {
            'id': '/odoo',
            'name': name,
            'short_name': 'Export Intl',
            'description': 'Contracts, trucks, bank, bills and approvals for Export International.',
            'lang': 'en',
            'dir': 'ltr',
            'scope': '/',                       # the sign-in page is inside the app window too, so an expired session does not throw it into a browser bar
            'start_url': '/odoo',
            'display': 'standalone',
            'orientation': 'any',
            'background_color': COLOUR,
            'theme_color': COLOUR,
            'prefer_related_applications': False,
            'categories': ['business', 'finance', 'productivity'],
            'icons': [
                {'src': ICONS + 'ei-icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
                {'src': ICONS + 'ei-icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
                {'src': ICONS + 'ei-icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
            ],
            'shortcuts': [],
        }

    def _has_share_target(self):
        return False

    def _icon_path(self):
        return 'ei_app_shell/static/img/ei-icon-192.png'       # the page shown when the network is down
