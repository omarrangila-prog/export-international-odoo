# Deployment runbook (what was actually exercised on this machine)

Target: **Odoo 20.0 Community (nightly 20261018)**, PostgreSQL 16, Python 3.12. Odoo 20 is unpacked in `~/odoo20` and started with the isolating launcher `~/odoo20/odoo20`, so the system Odoo 19 Enterprise used by other projects is never touched.
The 12 modules depend only on Community apps (`base mail account analytic product uom web_tour`).

## 1. Fresh install and tests
```
tests/run_all.sh                      # creates DB ei_fulltest, installs all 12 modules, runs all tests, writes docs/test_results.md
```
## 2. Staging database (one command)
```
migration/build_staging.sh ei20b      # DB, modules, PKR company + Pakistan chart, 639 codes, UAT roles, synthetic demo data
~/odoo20/odoo20 -c /dev/null -d ei20b --addons-path=$HOME/odoo20/root/usr/lib/python3/dist-packages/odoo/addons,$PWD/addons --http-interface=127.0.0.1 --http-port=8369
# or: migration/serve.sh ei20b          (loopback only; stop with kill $(cat ~/.ei_server.pid))
```
Logins: `admin`/`admin` (all roles, UAT only) and `demo.<role>`/`demo` (one role each). The demo data is synthetic and must not be loaded in production.
The Home page, readable labels and card views come from `ei_ui_theme`; to refresh them after code changes run the server once with `-u ei_ui_theme`.
## 3. Company set-up (manual, not automated)
* Set the company country to Pakistan and currency to PKR **before** posting anything (`migration/setup_company.py` does this in the staging build).
* Load the chart of accounts (`l10n_pk` or the accountant's own), set the company's internal transfer account (needed for cash-to-bank transfers), and loss/profit accounts on cash journals.
* One Odoo company per legal entity (open decision).
## 4. Roles
Assign one user per role. `migration/grant_uat_roles.py` gives ONE user every role for click-through UAT only; it defeats separation of duties and must not be used in production.
Even the Odoo administrator holds no business role by default (verified in the smoke test: access denied until granted).
## 5. Parameters
`ei_bank_operations.strict_separation` (default True), `ei_legacy_master.enforce_maker_checker` (True), `ei_material_lifting.tolerance_mtl` (0),
`ei_management_dashboard.bank_stale_hours` (24). The daily-summary cron is installed **inactive**.
## 6. Backup and restore (tested)
```
pg_dump -Fc -d ei_staging -f ei_staging.dump
createdb ei_restore && pg_restore -d ei_restore --no-owner ei_staging.dump
```
Result on 2026-10-19: 639 legacy codes, 3 import batches, 1445 module rows, 51 accounts and 4 users matched; an md5 over all 639 code/name/nick rows was identical before and after.
Filestore (attachments) must be backed up with the database; it was not part of this test. Production hosting, off-site backups, monitoring, central logs and secrets management are **not** set up here.
## 7. Integrations
FBR/PRAL, bank APIs, OCR and WhatsApp are shown as "Pending configuration" in *Setup -> Connections to other systems*. Nothing connects to an external service.
