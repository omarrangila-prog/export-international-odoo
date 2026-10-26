#!/bin/bash
# Installs Export International on a fresh Ubuntu 24.04 server: PostgreSQL, the Odoo 20 package, our addons, nginx with https, daily backups.
#
#   sudo bash deploy/install_ubuntu.sh --domain erp.example.com --odoo-deb /path/to/odoo_20.0.deb [--email you@example.com] [--db ei] [--dry-run]
#
# STATUS: written from what was exercised on the staging machine (see docs/deployment_runbook.md) but NOT YET RUN ON A REAL SERVER.
# Read it, run it with --dry-run first, and expect to fix a detail or two on the first real run.
#
# Use the SAME Odoo 20 package that the tests were run against (a nightly changes every day). On the build machine it is ~/odoo20/odoo20.deb.
set -euo pipefail

DOMAIN=""; DEB=""; EMAIL=""; DB="ei"; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2;;
    --odoo-deb) DEB="$2"; shift 2;;
    --email) EMAIL="$2"; shift 2;;
    --db) DB="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    *) echo "unknown argument $1"; exit 2;;
  esac
done
[ -n "$DOMAIN" ] && [ -n "$DEB" ] || { echo "usage: install_ubuntu.sh --domain erp.example.com --odoo-deb /path/odoo.deb [--email you@example.com] [--db ei] [--dry-run]"; exit 2; }
run() { echo "+ $*"; [ "$DRY" = 1 ] || "$@"; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ "$DRY" = 1 ] || [ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }

echo "== 1. packages"
run apt-get update
run apt-get install -y postgresql nginx certbot python3-certbot-nginx ufw fontconfig xfonts-75dpi xfonts-base libxrender1 libxext6 python3-pip curl
# the patched wkhtmltopdf Odoo needs for PDFs (orders, invoices, the dashboard)
run bash -c 'curl -fsSL -o /tmp/wkhtml.deb https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb && apt-get install -y /tmp/wkhtml.deb'
run apt-get install -y "$DEB"

echo "== 2. our addons"
run mkdir -p /opt/export-international
run rsync -a --delete --exclude '.git' --exclude 'docs/ui' --exclude '__pycache__' "$REPO/addons/" /opt/export-international/addons/
run chown -R odoo:odoo /opt/export-international

echo "== 3. configuration and secrets"
MASTER=$(openssl rand -base64 24)
PEPPER=$(openssl rand -base64 32)
ADMINPW=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-18)
WORKERS=$(( $(nproc) > 1 ? $(nproc) * 2 - 1 : 0 ))
if [ "$DRY" = 0 ]; then
  sed -e "s|@@MASTER_PASSWORD@@|$MASTER|" -e "s|@@DB_NAME@@|$DB|g" -e "s|@@WORKERS@@|$WORKERS|" "$REPO/deploy/odoo.conf.template" > /etc/odoo/odoo.conf
  chown odoo:odoo /etc/odoo/odoo.conf; chmod 640 /etc/odoo/odoo.conf
  # the key that protects sign-in PINs lives in the server's environment, not in the database
  printf 'EI_PIN_PEPPER=%s\n' "$PEPPER" > /etc/odoo/ei.env; chmod 600 /etc/odoo/ei.env
  mkdir -p /etc/systemd/system/odoo.service.d
  printf '[Service]\nEnvironmentFile=/etc/odoo/ei.env\n' > /etc/systemd/system/odoo.service.d/ei.conf
  echo "Odoo master password (database manager): $MASTER   <- write it down, it is not shown again"
else
  echo "+ (would write /etc/odoo/odoo.conf, /etc/odoo/ei.env with a new EI_PIN_PEPPER, and a systemd drop-in)"
fi
run systemctl daemon-reload

echo "== 4. database and modules"
run sudo -u postgres createuser -s odoo || true
run sudo -u odoo createdb "$DB"
MODULES=$(grep '^EI_MODULES=' "$REPO/migration/env.sh" | cut -d= -f2)
export EI_PIN_PEPPER="$PEPPER" EI_COMPANY_NAME="Export International"        # exported, not typed on the command line, so they never show in the log
SUDO=(sudo -u odoo --preserve-env=EI_PIN_PEPPER,EI_COMPANY_NAME)
run "${SUDO[@]}" odoo -c /etc/odoo/odoo.conf -d "$DB" -i "$MODULES,l10n_pk" --stop-after-init --without-demo=all
run "${SUDO[@]}" odoo shell -c /etc/odoo/odoo.conf -d "$DB" < "$REPO/migration/setup_company.py" || true
# a database made from the command line starts with the administrator password "admin": replace it before anything else
if [ "$DRY" = 0 ]; then
  printf "env.ref('base.user_admin').password = '%s'\nenv.cr.commit()\n" "$ADMINPW" | "${SUDO[@]}" odoo shell -c /etc/odoo/odoo.conf -d "$DB"
fi
run systemctl enable --now odoo

echo "== 5. web server and https"
if [ "$DRY" = 0 ]; then
  sed -e "s|@@DOMAIN@@|$DOMAIN|g" "$REPO/deploy/nginx-ei.conf.template" > /etc/nginx/sites-available/ei
  ln -sf /etc/nginx/sites-available/ei /etc/nginx/sites-enabled/ei
  rm -f /etc/nginx/sites-enabled/default
else
  echo "+ (would write the nginx site for $DOMAIN)"
fi
run nginx -t
run systemctl reload nginx
CB=(--nginx -d "$DOMAIN" --redirect --non-interactive --agree-tos)
if [ -n "$EMAIL" ]; then CB+=(-m "$EMAIL"); else CB+=(--register-unsafely-without-email); fi
run certbot "${CB[@]}"

echo "== 6. firewall and backups"
run ufw allow OpenSSH
run ufw allow 'Nginx Full'
run ufw --force enable
run install -m 755 "$REPO/deploy/backup.sh" /usr/local/bin/ei-backup
run bash -c "echo '17 2 * * * root /usr/local/bin/ei-backup $DB >> /var/log/ei-backup.log 2>&1' > /etc/cron.d/ei-backup"

cat <<MSG

Installed. Next (see deploy/README.md):
  1. open https://$DOMAIN and sign in as  admin  with the password shown below (change it at once; it is not shown again)
     administrator password: $ADMINPW
  2. give the first people their PINs (people.json is kept OUT of git, see migration/provision_pins.py):
       set -a; . /etc/odoo/ei.env; set +a
       EI_PROVISION_FILE=/root/people.json sudo -u odoo --preserve-env=EI_PIN_PEPPER,EI_PROVISION_FILE,EI_PIN_ACCEPT_WEAK odoo shell -c /etc/odoo/odoo.conf -d $DB < migration/provision_pins.py
  3. restrict PINs to the office network:  System Parameters > ei.pin.allowed_networks
MSG
