#!/usr/bin/env python3
"""Read-only extract of the old DOS FoxPro system.

    python3 migration/foxpro_extract.py  /path/to/COPY/of/foxpro/folder  /path/to/output  [--encoding cp1256]

Work on a COPY of the FoxPro folder, never on the live one. This script opens every file for reading only, and checks at the end that
no source file changed while it ran. For every table (.dbf) it writes:
  * <table>.csv  every record, every field as the exact text stored (numbers keep their digits: 4.20 stays 4.20), plus _recno and
                 _deleted (FoxPro keeps deleted records in the file until PACK; they are kept here and marked, not dropped);
  * manifest.json  for the whole folder: each file's SHA-256 and size (tables, memo .fpt, index .cdx/.idx, programs .prg, reports),
                 and per table its version, code page, field list, record counts (header and found) and deleted count.
Load manifest.json in Odoo (Setup > Old system extracts) to record the extract and compare its counts with the old system's own
control reports. Nothing is posted to the accounts by this script or by that screen.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'addons', 'ei_migration', 'lib'))
from dbf import DbfError, Table, sha256_file  # noqa: E402


def snapshot(src):
    out = {}
    for root, _dirs, files in os.walk(src):
        for name in files:
            p = os.path.join(root, name)
            out[os.path.relpath(p, src)] = {'sha256': sha256_file(p), 'bytes': os.path.getsize(p)}
    return out


def extract(src, dst, encoding=None):
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if not os.path.isdir(src):
        raise SystemExit('Source folder not found: %s' % src)
    if dst == src or dst.startswith(src + os.sep):
        raise SystemExit('Write the output OUTSIDE the FoxPro folder; nothing may be written next to the old files.')
    os.makedirs(dst, exist_ok=True)
    before = snapshot(src)
    tables, problems = [], []
    for rel in sorted(before):
        if not rel.lower().endswith('.dbf'):
            continue
        path = os.path.join(src, rel)
        try:
            t = Table(path, encoding=encoding)
            summary = t.summary()
        except (DbfError, OSError, ValueError) as e:
            problems.append({'file': rel, 'problem': str(e)})
            continue
        summary['file'] = rel
        out_csv = os.path.join(dst, rel.replace(os.sep, '__')[:-4] + '.csv')
        names = [f['name'] for f in summary['fields']]
        with open(out_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['_recno', '_deleted'] + names)
            for r in t.records():
                w.writerow([r['_recno'], 'Y' if r['_deleted'] else ''] + [r[n] for n in names])
        summary['csv'] = os.path.basename(out_csv)
        summary['csv_sha256'] = sha256_file(out_csv)
        if summary['records_in_header'] != summary['records_found']:
            problems.append({'file': rel, 'problem': 'header says %s records, %s found' % (summary['records_in_header'], summary['records_found'])})
        if not summary['codepage_known']:
            problems.append({'file': rel, 'problem': 'code page byte %s unknown; read as %s - check Urdu/special characters' % (summary['codepage_byte'], summary['codepage'])})
        if summary['memo'] and summary['memo']['missing']:
            problems.append({'file': rel, 'problem': 'memo file missing: memo fields are empty in the extract'})
        tables.append(summary)
    after = snapshot(src)
    if after != before:
        raise SystemExit('A source file changed while extracting. Stop the old system and extract again from a quiet copy.')
    manifest = {'format': 'ei-foxpro-extract/1', 'source_files': before, 'tables': tables, 'problems': problems,
                'encoding_override': encoding or None}
    with open(os.path.join(dst, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source')
    ap.add_argument('output')
    ap.add_argument('--encoding', help='force a code page (e.g. cp1256 for Urdu/Arabic text) when the table header does not say')
    a = ap.parse_args(argv)
    m = extract(a.source, a.output, a.encoding)
    print('%d tables, %d records (%d deleted), %d problems. Source unchanged. Manifest: %s' % (
        len(m['tables']), sum(t['records_found'] for t in m['tables']), sum(t['deleted'] for t in m['tables']), len(m['problems']),
        os.path.join(a.output, 'manifest.json')))
    for p in m['problems']:
        print('  ! %s: %s' % (p['file'], p['problem']))


if __name__ == '__main__':
    main()
