"""Pure-Python parsing and validation of the legacy code list.

No Odoo imports: this module is unit-testable on its own and is the only place that
decides what a "displayed" legacy code looks like. Codes are always handled as text.
"""
import csv
import hashlib
import io
import re
from decimal import Decimal, ROUND_HALF_UP

# Group totals stated in the project brief for CODE LIST.xlsx (keys are stripped sheet names).
EXPECTED_COUNTS = {
    'CUSTOMER': 452,
    'BANK': 79,
    'IMPORT PUR SALE': 58,
    'FOR PURCHASE': 24,
    'PROFIT & LOSS': 18,
    'EXPENSES': 8,
}
EXPECTED_TOTAL = sum(EXPECTED_COUNTS.values())  # 639

CODE_RE = re.compile(r'^\d+\.\d\d$')
CSV_COLUMNS = ('source_sheet', 'source_row', 'legacy_code', 'legacy_name', 'legacy_nickname')
FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sheet_key(name):
    """Sheet names are compared stripped ('PROFIT & LOSS ' has a trailing space in the source)."""
    return (name or '').strip()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def display_code(value, number_format='0.00'):
    """Return the code exactly as Excel displays it with a 0.00 format, as text."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, Decimal)):
        # repr() round-trips floats; quantize reproduces the two-decimal display (4.2 -> '4.20').
        return str(Decimal(repr(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    return str(value).strip()


def sanitize_cell(value):
    """Neutralise spreadsheet formula injection in anything we export."""
    value = '' if value is None else str(value)
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


class ParseResult:
    def __init__(self):
        self.rows = []          # dicts with keys: sheet, sheet_key, row, code, name, nick
        self.errors = []        # human readable, one per unhandled problem
        self.skipped = []       # (sheet, row, reason) for blank lines
        self.duplicates = []    # (sheet_key, code, row)
        self.formula_cells = 0  # cells that look like formulas / injection
        self.sha256 = ''

    @property
    def ok(self):
        return not self.errors


def _finalise(result):
    """Cross-row validation shared by CSV and XLSX readers."""
    seen = {}
    for r in result.rows:
        if not CODE_RE.match(r['code']):
            result.errors.append(
                "%s row %s: code %r is not in displayed N.NN text form" % (r['sheet_key'], r['row'], r['code']))
        if not r['name']:
            result.errors.append("%s row %s: empty NAME for code %s" % (r['sheet_key'], r['row'], r['code']))
        if r['sheet_key'] not in EXPECTED_COUNTS:
            result.errors.append("%s row %s: unknown sheet %r" % (r['sheet_key'], r['row'], r['sheet']))
        k = (r['sheet_key'], r['code'])
        if k in seen:
            result.duplicates.append((r['sheet_key'], r['code'], r['row']))
            result.errors.append("%s row %s: duplicate code %s (first seen row %s)" % (
                r['sheet_key'], r['row'], r['code'], seen[k]))
        else:
            seen[k] = r['row']
        for field in ('name', 'nick'):
            if r[field].startswith(FORMULA_PREFIXES):
                result.formula_cells += 1
    counts = {}
    for r in result.rows:
        counts[r['sheet_key']] = counts.get(r['sheet_key'], 0) + 1
    for sk, expected in EXPECTED_COUNTS.items():
        if counts.get(sk, 0) != expected:
            result.errors.append("sheet %s: expected %d rows, found %d" % (sk, expected, counts.get(sk, 0)))
    return result


def parse_csv(data):
    result = ParseResult()
    result.sha256 = sha256(data)
    text = data.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text, newline=''))
    missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        result.errors.append("CSV is missing columns: %s" % ', '.join(missing))
        return result
    for line_no, rec in enumerate(reader, start=2):
        if not any((v or '').strip() for v in rec.values()):
            result.skipped.append(('', line_no, 'blank line'))
            continue
        sheet = rec['source_sheet']  # raw, trailing space preserved
        try:
            row = int(rec['source_row'])
        except (TypeError, ValueError):
            result.errors.append("CSV line %d: bad source_row %r" % (line_no, rec['source_row']))
            continue
        result.rows.append({
            'sheet': sheet, 'sheet_key': sheet_key(sheet), 'row': row,
            'code': (rec['legacy_code'] or '').strip(),
            'name': (rec['legacy_name'] or '').strip(),
            'nick': (rec['legacy_nickname'] or '').strip(),
        })
    return _finalise(result)


def parse_xlsx(data):
    """Read the original CODE LIST.xlsx: INDEX is ignored, header on row 2, data from row 3.

    NOTE: written from the brief's description; it has NOT been run against the real workbook
    (not available on this machine). Counted formula cells are reported, never evaluated.
    """
    import openpyxl
    result = ParseResult()
    result.sha256 = sha256(data)
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    for ws in wb.worksheets:
        if sheet_key(ws.title).upper() == 'INDEX':
            continue
        for row_no, cells in enumerate(ws.iter_rows(min_row=3), start=3):
            code_cell, name_cell, nick_cell = (list(cells) + [None] * 3)[:3]
            if all(c is None or c.value in (None, '') for c in (code_cell, name_cell, nick_cell)):
                result.skipped.append((ws.title, row_no, 'blank row'))
                continue
            result.rows.append({
                'sheet': ws.title, 'sheet_key': sheet_key(ws.title), 'row': row_no,
                'code': display_code(code_cell.value if code_cell else None),
                'name': str(name_cell.value).strip() if name_cell and name_cell.value is not None else '',
                'nick': str(nick_cell.value).strip() if nick_cell and nick_cell.value is not None else '',
            })
    return _finalise(result)


def parse(filename, data):
    return parse_xlsx(data) if (filename or '').lower().endswith(('.xlsx', '.xlsm')) else parse_csv(data)
