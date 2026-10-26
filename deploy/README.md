# Putting Export International on a live server

**Read this first.** The system is a **functional first build for UAT preparation, not production-ready** (`docs/release_status.md`). It can be hosted and used by the three senior people for a pilot, but before real money is entered the open decisions in `docs/open_decisions.md` need answers (the tax and commission bases, the chart of accounts and opening balances, who may see what, bank and FBR access). Nothing here has been run on a real server: the installer was written from what was exercised on the staging machine and checked with `--dry-run`, not executed.

## What you need
| | |
|---|---|
| A server | Ubuntu 24.04, 2 vCPU, 4 GB RAM, 40 GB disk (any provider). SSH access with sudo |
| A name | a DNS record (for example `erp.yourcompany.com`) pointing at the server's address. The PWA install and the sign-in limits need https |
| The Odoo 20 package | **the same one the tests were run against**: on the build machine `~/odoo20/odoo20.deb` (a nightly changes every day, so a newer one is a new, untested system). Copy it to the server with `scp` |
| This repository | `git clone` it on the server (private repository: use a deploy key or a token) |

## One command
```
sudo bash deploy/install_ubuntu.sh --domain erp.yourcompany.com --odoo-deb /root/odoo20.deb --email you@yourcompany.com
```
Run it once with `--dry-run` first: it prints every step and touches nothing. It installs PostgreSQL, the patched wkhtmltopdf, the Odoo package and our addons, writes `/etc/odoo/odoo.conf` (no database manager, `proxy_mode`, workers), creates the database with **no demo data**, makes a random administrator password and a random master password (both shown once at the end), puts the key that protects PINs in `/etc/odoo/ei.env`, sets up nginx with https (Let's Encrypt), the firewall (ssh, http, https) and a nightly backup (`/usr/local/bin/ei-backup`, 14 days kept, **copy `/var/backups/ei` off the server as well**).

## Then
1. Sign in as `admin` with the printed password and change it. Fill in the company (name, address, logo) under Settings > Companies.
2. **Give the first people their PINs** (the people file is kept off git; see the header of `migration/provision_pins.py`):
   ```
   set -a; . /etc/odoo/ei.env; set +a
   EI_PROVISION_FILE=/root/people.json EI_PIN_ACCEPT_WEAK=1 sudo -u odoo --preserve-env=EI_PIN_PEPPER,EI_PROVISION_FILE,EI_PIN_ACCEPT_WEAK \
     odoo shell -c /etc/odoo/odoo.conf -d ei < migration/provision_pins.py
   ```
   The script refuses easy PINs (repeated digits, 1234...) unless `EI_PIN_ACCEPT_WEAK=1` and tells you why: with the PIN alone as the way in, anyone who tries 1111 to 9999 reaches such an account in a minute. **If easy PINs are used, restrict PIN sign-in to the office network** (Settings > Technical > System Parameters: `ei.pin.allowed_networks` = the office's public address, e.g. `203.0.113.7`). Everyone else, and everyone out of the office, signs in with the password.
3. Keep `base.group_system` (the administrator) on the password: it is reserved by default.
4. Do not load the demo data or the staging seeds (`seed_*.py`): they are for staging only. The sign-in page then shows no STAGING label (it appears only when `ei.environment_label` is set).
5. Import the client's code list with `migration/import_legacy_codes.py` (the workbook is not in the repository on purpose).

## Updating later
```
cd /path/to/repo && git pull
sudo rsync -a --delete --exclude .git --exclude docs/ui --exclude __pycache__ addons/ /opt/export-international/addons/
sudo chown -R odoo:odoo /opt/export-international
sudo -u odoo odoo -c /etc/odoo/odoo.conf -d ei -u all --stop-after-init   # or -u the modules that changed
sudo systemctl restart odoo
```
Take a backup first (`sudo ei-backup`). Re-run the tests on a copy before you touch the live system.

## Checklist before real data
- [ ] https works and the padlock is shown; `http://` redirects
- [ ] `list_db = False` (no "Manage Databases" link on the sign-in page)
- [ ] the master and administrator passwords are stored somewhere safe
- [ ] `EI_PIN_PEPPER` is set (Home shows a red line for the administrator if it is not) and the file `/etc/odoo/ei.env` is 600
- [ ] the nightly backup ran and a restore was tried on another machine
- [ ] outgoing mail is configured (Settings > Technical > Outgoing Mail Servers)
- [ ] sign-up is closed (it is, from this version: `auth_signup.invitation_scope = b2b`)
- [ ] the people who may approve are on the password, or PIN sign-in is limited to the office network
- [ ] the decisions in `docs/open_decisions.md` that touch money have an answer in writing

## What was not done here
No server was available to this build, so: the installer and nginx file are untested on a real machine, there is no Docker image (the build machine cannot run Docker), no monitoring or log shipping, no off-site backup, and no load test.
