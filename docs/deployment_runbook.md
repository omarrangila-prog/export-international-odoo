# Deployment runbook (what was actually exercised on this machine)

Target: **Odoo 20.0 Community (nightly 20261018)**, PostgreSQL 16, Python 3.12. Odoo 20 is unpacked in `~/odoo20` and started with the isolating launcher `~/odoo20/odoo20`, so the system Odoo 19 Enterprise used by other projects is never touched.
The 12 modules depend only on Community apps (`base mail account analytic product uom web_tour`).

## 0. Machine set-up (all of this was needed, and is now scripted or checked)
* **One data directory.** Every script sources `migration/env.sh`, which fixes the filestore at `~/.local/share/Odoo` (override with `EI_DATA_DIR`). Never point a server at a temporary folder: generated web bundles and uploaded files live in the filestore while the database keeps rows that point at them. (25 Oct 2026: a staging server was started with its data directory inside a scratch folder, the folder was wiped, and every web bundle went missing, so the site showed a blank page.)
* `migration/check_filestore.py DB` compares every file the database points at with the disk and exits non-zero if any is missing. `migration/serve.sh` runs it before starting a server and refuses to start on missing business attachments; missing web bundles (derived data) are repaired with `EI_REPAIR_ASSETS=1`. Dropping a database with `ei_drop_db` also removes its filestore, so a re-created database never inherits a stale one.
* **PDF engine.** Daily Order, invoice and dashboard PDFs need `wkhtmltopdf` (patched Qt). It was not installed; it is unpacked, without root, from the official wkhtmltopdf 0.12.6.1-3 package into `~/odoo20/wkhtml` and put on the path by `migration/env.sh`. On a server install the same package system-wide. Home shows a red "System checks" line for administrators when it is missing.
* Document layout: `migration/setup_company.py` sets the standard layout so the first person to press Print is not interrupted by Odoo's layout wizard. Upload the logo and address in Settings > Companies.
* Browser tests need Node 20+, `playwright` and `axe-core` (see `tests/e2e/README.md`).

## 1. Fresh install and tests
```
tests/run_all.sh                      # unit tests on a fresh DB, then the real-browser suite; writes docs/test_results.md and docs/e2e_results.md
EI_SKIP_E2E=1 tests/run_all.sh        # unit tests only (say so when you report it)
tests/run_modules.sh "ei_party360"    # quick unit run of one module and its dependencies
tests/run_e2e.sh [--spec 03]          # the browser suite alone, on a fresh copy of the pristine staging database
```
## 2. Staging database (one command)
```
migration/build_staging.sh ei20b      # DB, modules, PKR company + Pakistan chart, 639 codes, UAT roles, synthetic demo data
migration/serve.sh ei20b              # loopback only on 8369; stop with: kill $(cat ~/.ei_server.pid)   (never pkill -f)
```
Logins: `admin`/`admin` (all roles, UAT only) and `demo.<role>`/`demo` (one role each, plus `demo.finance` and `demo.sysadmin`). The demo data is synthetic and must not be loaded in production.
After a code change run the server once with `-u <module>`; template (`.xml`) changes also need a server restart even with `--dev=assets`.
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
