#!/bin/bash
# Daily backup: the database and the filestore (attachments) together, 14 days kept. Run from cron as root; copy /var/backups/ei off the server too.
set -euo pipefail
DB=${1:-ei}
DEST=/var/backups/ei
STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$DEST"
sudo -u postgres pg_dump -Fc "$DB" > "$DEST/$DB-$STAMP.dump"
tar -C /var/lib/odoo/filestore -czf "$DEST/$DB-filestore-$STAMP.tgz" "$DB"
find "$DEST" -type f -mtime +14 -delete
echo "backup written: $DEST/$DB-$STAMP.dump and the filestore"
