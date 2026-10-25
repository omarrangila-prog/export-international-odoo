"""Idempotent importer, run inside `odoo shell`:

    EXI_SOURCE=migration/source/EXI_legacy_codes.csv \
    odoo shell -c /dev/null -d ei_staging --addons-path=... < migration/import_legacy_codes.py

Safe to re-run: unchanged rows are skipped, changed rows are logged as diffs, nothing is overwritten.
Writes a reconciliation CSV next to the source (migration/validation_reports/).
"""
import os

src = os.environ['EXI_SOURCE']
with open(src, 'rb') as f:
    data = f.read()
batch = env['ei.import.batch'].import_file(os.path.basename(src), data)
env.cr.commit()
print("BATCH", batch.name, batch.state, "rows", batch.total_rows, "created", batch.total_created,
      "unchanged", batch.total_unchanged, "changed", batch.total_changed)
for s in batch.sheet_ids:
    print("  %-16s expected %3d actual %3d created %3d unchanged %3d no-nick %2d dup %d" % (
        s.sheet_key, s.expected, s.actual, s.created, s.unchanged, s.missing_nick, s.duplicates))
if batch.error_log:
    print("ERRORS:\n" + batch.error_log)
out = os.environ.get('EXI_REPORT')
if out:
    with open(out, 'wb') as f:
        f.write(batch._reconciliation_csv())
    print("report ->", out)
