"""The system says which system it is. A person must never enter live figures into the staging copy, or the reverse."""
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'ei')
class TestEnvironmentLabel(HttpCase):

    def test_e01_the_label_reaches_the_web_client_and_the_sign_in_page(self):
        params = self.env['ir.config_parameter'].sudo()
        self.authenticate('admin', 'admin')
        session_label = lambda: self.make_jsonrpc_request('/web/session/get_session_info', {})['ei_environment_label']
        params.set_str('ei.environment_label', '')
        self.assertEqual(session_label(), '')                                                        # live: nothing is shown
        params.set_str('ei.environment_label', 'STAGING - synthetic demo data')
        self.assertEqual(session_label(), 'STAGING - synthetic demo data')
        self.opener.cookies.clear()                                                                  # the sign-in page is for someone not signed in
        page = self.url_open('/web/login').text
        self.assertIn('Export International', page)                                                  # the brand line
        self.assertIn('STAGING - synthetic demo data', page)                                          # and which system this is
        self.assertIn('oe_login_form', page)                                                          # Odoo's own form and security flow are still there
