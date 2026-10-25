#!/usr/bin/env python3
"""Check that every file the database points at exists in the filestore.   usage: check_filestore.py DB [--repair-assets]

Exit 0 = consistent; 1 = business attachments are missing (never auto-repaired); 2 = only generated web bundles are
missing (derived data; harmless to regenerate, but we say so loudly instead of showing a blank page).
--repair-assets deletes ONLY the rows of missing generated bundles (url like /web/assets/%) so Odoo rebuilds them."""
import os
import subprocess
import sys

db = sys.argv[1]
repair = '--repair-assets' in sys.argv
data_dir = os.environ.get('EI_DATA_DIR', os.path.expanduser('~/.local/share/Odoo'))
root = os.path.join(data_dir, 'filestore', db)


def psql(sql):
    out = subprocess.run(['psql', db, '-Atc', sql], capture_output=True, text=True)
    if out.returncode:
        sys.exit('psql failed: ' + out.stderr.strip())
    return [r for r in out.stdout.split('\n') if r]


rows = [r.split('|') for r in psql("select id, coalesce(url,''), store_fname, name from ir_attachment where store_fname is not null")]
missing = [r for r in rows if not os.path.exists(os.path.join(root, r[2]))]
assets = [r for r in missing if r[1].startswith('/web/assets/')]
business = [r for r in missing if not r[1].startswith('/web/assets/')]
print('filestore %s: %d files referenced, %d missing (%d web bundles, %d other)' % (root, len(rows), len(missing), len(assets), len(business)))
for r in business[:10]:
    print('  MISSING FILE for attachment %s %r' % (r[0], r[3]))
if business:
    print('  Business attachments are never repaired automatically: restore the filestore from backup.')
    sys.exit(1)
if assets:
    if repair:
        psql("delete from ir_attachment where id in (%s)" % ','.join(r[0] for r in assets))
        print('  repaired: deleted %d missing web-bundle rows; Odoo rebuilds them on the next page load' % len(assets))
        sys.exit(0)
    print('  Web bundles are missing, so the site would show a blank page. Re-run with --repair-assets.')
    sys.exit(2)
