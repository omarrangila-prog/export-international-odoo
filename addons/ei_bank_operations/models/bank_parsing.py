"""Bank statement CSV parsing (pure Python, Decimal money, no Odoo imports)."""
import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

DATE_FORMATS = ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d-%b-%Y', '%d/%m/%y', '%d-%m-%y')
ALIASES = {
    'date': ('date', 'value date', 'txn date', 'transaction date', 'posting date'),
    'narration': ('description', 'narration', 'particulars', 'details', 'remarks'),
    'ref': ('reference', 'ref', 'txn id', 'transaction id', 'cheque no', 'instrument no'),
    'debit': ('debit', 'withdrawal', 'dr', 'paid out'),
    'credit': ('credit', 'deposit', 'cr', 'paid in'),
    'amount': ('amount',),
    'balance': ('balance', 'running balance', 'closing balance'),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalise_text(s):
    return re.sub(r'\s+', ' ', (s or '').upper()).strip()


def to_decimal(s):
    s = (s or '').strip().replace(',', '').replace(' ', '')
    if not s or s in ('-', '--'):
        return None
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()')
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError('not a number: %r' % s)
    return -d if neg else d


def to_date(s):
    s = (s or '').strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError('unrecognised date: %r' % s)


def fingerprint(journal_id, date, amount, ref, narration, occurrence):
    """Stable identity of a bank line. A bank-supplied reference is the key when present; otherwise
    date+amount+narration plus the n-th occurrence inside the file, so legitimately identical lines in one
    statement stay distinct while an overlapping re-upload of the same statement collapses onto them."""
    if ref:
        basis = '%s|REF|%s' % (journal_id, normalise_text(ref))
    else:
        basis = '%s|%s|%s|%s|%d' % (journal_id, date.isoformat(), amount, normalise_text(narration), occurrence)
    return hashlib.sha256(basis.encode()).hexdigest()


class StatementParse:
    def __init__(self):
        self.lines = []      # dict(date, amount, ref, narration, balance, sequence)
        self.errors = []
        self.sha256 = ''


def parse_statement_csv(data):
    res = StatementParse()
    res.sha256 = sha256(data)
    reader = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    header = None
    cols = {}
    for n, row in enumerate(reader, start=1):
        if not any(c.strip() for c in row):
            continue
        if header is None:
            header = [c.strip().lower() for c in row]
            for key, names in ALIASES.items():
                for i, h in enumerate(header):
                    if h in names:
                        cols.setdefault(key, i)
            if 'date' not in cols or not (('debit' in cols or 'credit' in cols) or 'amount' in cols):
                res.errors.append('Header must contain a date and either debit/credit or amount columns.')
                return res
            continue
        get = lambda k: row[cols[k]].strip() if k in cols and cols[k] < len(row) else ''
        try:
            date = to_date(get('date'))
            if 'amount' in cols and not (get('debit') or get('credit')):
                amount = to_decimal(get('amount'))
            else:
                cr, dr = to_decimal(get('credit')), to_decimal(get('debit'))
                if cr and dr:
                    raise ValueError('both debit and credit filled')
                amount = abs(cr or Decimal(0)) - abs(dr or Decimal(0))  # debit/credit columns are magnitudes
            if amount is None or amount == 0:
                raise ValueError('zero or missing amount')
            balance = to_decimal(get('balance')) if get('balance') else None
        except ValueError as e:
            res.errors.append('line %d: %s' % (n, e))
            continue
        res.lines.append({'date': date, 'amount': amount, 'ref': get('ref'), 'narration': get('narration'),
                          'balance': balance, 'sequence': len(res.lines) + 1})
    if header is None:
        res.errors.append('Empty file.')
    return res
