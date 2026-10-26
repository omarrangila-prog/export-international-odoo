"""The app can be installed as itself: its own name, icons and colours, a head that suits a phone, a sign-in page that offers it too."""
import json
import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestInstallableApp(HttpCase):

    def test_p01_the_manifest_is_ours_and_its_icons_exist(self):
        res = self.url_open('/web/manifest.webmanifest')
        self.assertEqual(res.status_code, 200)
        m = json.loads(res.text)
        self.assertEqual((m['name'], m['display'], m['start_url'], m['scope']), ('Export International', 'standalone', '/odoo', '/'))
        self.assertNotIn('Odoo', json.dumps(m))
        self.assertNotIn('share_target', m)
        self.assertEqual(m['theme_color'], m['background_color'])
        sizes = {(i['sizes'], i['purpose']) for i in m['icons']}
        self.assertTrue({('192x192', 'any'), ('512x512', 'any'), ('512x512', 'maskable')} <= sizes)
        for icon in m['icons']:
            r = self.url_open(icon['src'])
            self.assertEqual((r.status_code, r.headers['Content-Type']), (200, 'image/png'), icon['src'])
            self.assertTrue(r.content.startswith(b'\x89PNG'))

    def test_p02_the_sign_in_page_and_the_app_head_suit_a_phone(self):
        login = self.url_open('/web/login').text
        self.assertIn('rel="manifest"', login)
        self.assertIn('viewport-fit=cover', login)
        self.assertIn('ei-icon-180.png', login)
        self.assertIn('ei-favicon-64.png', login)
        self.authenticate('admin', 'admin')
        app = self.url_open('/odoo').text
        self.assertIn('viewport-fit=cover', app)
        self.assertNotIn('user-scalable=no', app, 'pinch zoom must stay available')
        self.assertIn('#F4F6FA', app)
        self.assertIn('ei-icon-180.png', app)
        self.assertIn('apple-mobile-web-app-capable', app)

    def test_p03_the_page_shown_without_a_network_carries_our_icon_not_odoo_s(self):
        page = self.url_open('/odoo/offline').text
        self.assertEqual(len(re.findall(r'data:image/png;base64,', page)) >= 1, True)
