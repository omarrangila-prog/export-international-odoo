"""UAT / demo helper. Run inside `odoo shell`:   EI_USER=admin odoo shell -d <db> < migration/grant_uat_roles.py

Gives ONE user every Export International role so a single tester can click through all screens.
Do NOT use in production: it defeats the maker-checker separation (the controls then block that user
from approving their own work, which is the point, but a real rollout uses one user per role)."""
import os

login = os.environ['EI_USER']
user = env['res.users'].search([('login', '=', login)], limit=1)
assert user, 'no such user'
privs = env['res.groups.privilege'].search([('name', 'ilike', 'Export International')])
groups = env['res.groups'].search([('privilege_id', 'in', privs.ids)])
user.write({'group_ids': [(4, g.id) for g in groups]})
env.cr.commit()
print('granted %d EI groups to %s:' % (len(groups), login))
for g in groups.sorted('name'):
    print('  -', g.name)
