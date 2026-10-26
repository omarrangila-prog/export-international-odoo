"""STAGING ONLY. Gives each demo.<role> a sign-in PIN so the "user name + PIN" way of signing in can be tried (the PINs are listed in
docs/pin_login.md). Never run on a live system: real people choose their own PIN from their name menu.
usage: migration/build_staging.sh runs it;  by hand:  ei_shell -d DB < migration/seed_demo_pins.py"""
from odoo.addons.ei_pin_login.models.pin_policy import check_new_pin

DEMO_PINS = {'demo.ceo': '4826', 'demo.finance': '5973', 'demo.accountant': '6184', 'demo.contractapprover': '7352', 'demo.contracts': '8419',
             'demo.bank': '3647', 'demo.cash': '2958', 'demo.dispatch': '9261'}              # demo.sysadmin: the system administrator signs in with the password only
n = 0
for login, pin in DEMO_PINS.items():
    check_new_pin(pin, pin)
    user = env['res.users'].sudo().search([('login', '=', login)])
    if user and user._ei_pin_allowed():
        env['ei.pin.credential']._set_pin(user, pin)
        n += 1
env.cr.commit()
print('DEMO PINs set for %d people' % n)
