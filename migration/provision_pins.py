"""Create (or update) named people and give each a first sign-in PIN.  For the operator, on ANY database:

    EI_PROVISION_FILE=/path/outside/the/repo/people.json  [EI_PIN_ACCEPT_WEAK=1]  odoo shell -c /etc/odoo/odoo.conf -d DB < migration/provision_pins.py

people.json is a list kept OUT of git (it holds the PINs):
    [{"login": "a.director", "name": "A. Director", "role": "executive",      "pin": "...."},
     {"login": "it.lead",    "name": "IT Lead",     "role": "all_operations", "pin": "...."}]
optional per person: "password" (otherwise a random one is made for a NEW person and printed once), "groups" (list of group ids, instead of "role").

roles:  executive       = the CEO's view (management: sees everything, approves, and may also prepare entries; never approves their own)
        all_operations  = every Export International role plus accountant: runs all the operations. NOT the system administrator
                          (Settings, users and groups stay with the administrator account).

A first PIN chosen here skips the rules a person's own choice must meet (no 1234, 0000, repeated digits...), because the operator decides.
Such a PIN is easy to guess, and with the PIN alone as the way in anyone who tries 1111 ... 9999 reaches it in a minute. So the script refuses
them unless EI_PIN_ACCEPT_WEAK=1, and says what to do instead (docs/pin_login.md: restrict PIN sign-in to the office network, or pick other PINs).
It never prints a PIN."""
import json
import os
import secrets

from odoo import Command
from odoo.addons.ei_pin_login.models.pin_policy import PIN_RE, why_too_easy

people = json.load(open(os.environ['EI_PROVISION_FILE']))
accept_weak = os.environ.get('EI_PIN_ACCEPT_WEAK') == '1'
env = env(su=True)
Users, Group = env['res.users'], env['res.groups']

weak = [p['login'] for p in people if why_too_easy(p['pin'])]
bad = [p['login'] for p in people if not PIN_RE.fullmatch(p.get('pin') or '')]
assert not bad, 'not four digits: %s' % ', '.join(bad)
assert len({p['pin'] for p in people}) == len(people), 'two people were given the same PIN'
networks = env['ir.config_parameter'].get_str('ei.pin.allowed_networks', '')
if weak and not accept_weak:
    raise SystemExit('REFUSED: easy-to-guess PINs for %s.\n  With the PIN alone as the way in, anyone who tries 1111, 2222 ... reaches these accounts in a minute.\n'
                     '  Either choose other PINs, or restrict PIN sign-in to the office network (System Parameter ei.pin.allowed_networks),\n'
                     '  and then run again with EI_PIN_ACCEPT_WEAK=1.' % ', '.join(weak))


def role_groups(role):
    if role == 'executive':
        return [env.ref('ei_management_dashboard.group_ei_management')]
    if role == 'all_operations':
        privs = env['res.groups.privilege'].search([('name', 'ilike', 'Export International')])
        return list(Group.search([('privilege_id', 'in', privs.ids)])) + [env.ref('account.group_account_user')]
    raise SystemExit('unknown role %r' % role)


co = env.company
home = env.ref('ei_ui_theme.action_ei_home')
for p in people:
    groups = [env.ref(g) for g in p['groups']] if p.get('groups') else role_groups(p['role'])
    user = Users.search([('login', '=', p['login'])])
    made = ''
    if not user:
        password = p.get('password') or secrets.token_urlsafe(12)
        user = Users.with_context(no_reset_password=True).create({
            'name': p['name'], 'login': p['login'], 'password': password, 'company_id': co.id, 'company_ids': [Command.set([co.id])],
            'group_ids': [Command.set([g.id for g in groups])], 'action_id': home.id})
        made = 'created, first password %s (shown once)' % ('as given' if p.get('password') else password)
    else:
        user.write({'group_ids': [Command.link(g.id) for g in groups]})
        made = 'already existed, roles added'
    assert user._ei_pin_allowed(), '%s may not use a PIN (reserved role); see ei.pin.blocked_groups' % p['login']
    env['ei.pin.credential']._set_pin(user, p['pin'])
    env.cr.commit()                                          # the sign-in log is written in a transaction of its own and must see the person
    env['ei.pin.log']._write_apart({'event': 'set', 'success': True, 'reason': 'first PIN set by the operator', 'user_id': user.id, 'login': user.login, 'ip': 'console'})
    print('  %-16s %-15s %s; PIN set%s' % (p['login'], p['role'] if p.get('role') else 'custom roles', made, ' (EASY TO GUESS)' if p['login'] in weak else ''))
env.cr.commit()
print('PINs set for %d people.' % len(people))
if weak:
    print('WARNING: %d easy-to-guess PIN(s). PIN sign-in is %s.' % (len(weak), 'restricted to ' + networks if networks else 'OPEN FROM ANY NETWORK; set ei.pin.allowed_networks'))
if not os.environ.get('EI_PIN_PEPPER'):
    print('NOTE: EI_PIN_PEPPER is not set in this environment; set it for the server (docs/pin_login.md).')
