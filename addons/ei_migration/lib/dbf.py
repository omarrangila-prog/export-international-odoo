"""Read-only reader for DOS FoxPro / dBase / Visual FoxPro tables (.dbf) and their memo files (.fpt / .dbt).

It never writes and never opens a file for writing. Every value comes back as the exact text stored in the file (numbers too: "4.20"
stays "4.20", never 4.2), plus a typed value where the type is unambiguous. Deleted records are kept and marked, so the extract can be
counted against the old system's own reports both with and without them. Standard library only, so it runs on any machine.
"""
import datetime
import hashlib
import os
import struct
from decimal import Decimal, InvalidOperation

# Language-driver (code page) byte at offset 29 -> Python codec. Unknown bytes fall back to cp437 (DOS) and are reported.
CODEPAGES = {
    0x00: None, 0x01: 'cp437', 0x02: 'cp850', 0x03: 'cp1252', 0x04: 'mac_roman', 0x64: 'cp852', 0x65: 'cp866', 0x66: 'cp865',
    0x67: 'cp861', 0x6A: 'cp737', 0x6B: 'cp857', 0x78: 'cp950', 0x79: 'cp949', 0x7A: 'cp936', 0x7B: 'cp932', 0x7C: 'cp874',
    0x7D: 'cp1255', 0x7E: 'cp1256', 0xC8: 'cp1250', 0xC9: 'cp1251', 0xCA: 'cp1254', 0xCB: 'cp1253', 0x57: 'cp1252', 0x59: 'cp1252',
}
VERSIONS = {0x02: 'FoxBASE', 0x03: 'dBase III / FoxPro (no memo)', 0x30: 'Visual FoxPro', 0x31: 'Visual FoxPro (autoincrement)',
            0x32: 'Visual FoxPro (varchar)', 0x43: 'dBase IV SQL table', 0x63: 'dBase IV SQL system', 0x83: 'dBase III with memo',
            0x8B: 'dBase IV with memo', 0xCB: 'dBase IV SQL with memo', 0xF5: 'FoxPro 2.x with memo', 0xFB: 'FoxBASE'}


class DbfError(ValueError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class Field:
    __slots__ = ('name', 'type', 'length', 'decimals', 'offset')

    def __init__(self, name, ftype, length, decimals, offset):
        self.name, self.type, self.length, self.decimals, self.offset = name, ftype, length, decimals, offset

    def as_dict(self):
        return {'name': self.name, 'type': self.type, 'length': self.length, 'decimals': self.decimals}


class Table:
    """Open with Table(path). Iterate with .records(): dicts of {field: text}, plus '_deleted' and '_recno'."""

    def __init__(self, path, encoding=None):
        self.path = path
        with open(path, 'rb') as f:
            self._data = f.read()
        d = self._data
        if len(d) < 32:
            raise DbfError('%s: too short to be a table' % path)
        self.version = d[0]
        yy, mm, dd = d[1], d[2], d[3]
        try:
            self.last_update = datetime.date(1900 + yy if yy > 30 or self.version in (0x30, 0x31, 0x32) else 2000 + yy, mm, dd)
        except ValueError:
            self.last_update = None
        self.header_count, self.header_len, self.record_len = struct.unpack('<IHH', d[4:12])
        self.codepage_byte = d[29]
        self.codepage_known = self.codepage_byte in CODEPAGES
        self.encoding = encoding or CODEPAGES.get(self.codepage_byte) or 'cp437'
        self.fields = []
        pos, offset = 32, 1                           # byte 0 of every record is the deletion flag
        while pos < self.header_len and d[pos] != 0x0D:
            raw = d[pos:pos + 32]
            if len(raw) < 32:
                raise DbfError('%s: field list is cut short' % path)
            name = raw[:11].split(b'\0', 1)[0].decode('ascii', 'replace').strip()
            ftype = chr(raw[11])
            length, decimals = raw[16], raw[17]
            if ftype == 'C' and self.version not in (0x30, 0x31, 0x32):
                length = raw[16] + raw[17] * 256        # FoxPro/Clipper: long character fields use the decimals byte as the high byte
                decimals = 0
            self.fields.append(Field(name, ftype, length, decimals, offset))
            offset += length
            pos += 32
        if offset != self.record_len:
            raise DbfError('%s: fields add up to %s bytes, header says %s' % (path, offset, self.record_len))
        body = len(d) - self.header_len
        self.actual_count = max(body // self.record_len, 0) if self.record_len else 0
        self.memo = self._open_memo()

    def _open_memo(self):
        if not any(f.type in 'MGP' for f in self.fields):
            return None
        base = os.path.splitext(self.path)[0]
        for ext in ('.fpt', '.FPT', '.dbt', '.DBT'):
            if os.path.exists(base + ext):
                return Memo(base + ext, self.encoding)
        return MissingMemo(base)

    def schema(self):
        return [f.as_dict() for f in self.fields]

    def records(self):
        d, start, size = self._data, self.header_len, self.record_len
        for n in range(min(self.header_count, self.actual_count)):
            rec = d[start + n * size: start + (n + 1) * size]
            if len(rec) < size:
                break
            out = {'_recno': n + 1, '_deleted': rec[0:1] == b'*'}
            for f in self.fields:
                out[f.name] = self._value(f, rec[f.offset:f.offset + f.length])
            yield out

    def _value(self, f, raw):
        t = f.type
        if t in 'CV':
            return raw.decode(self.encoding, 'replace').rstrip(' \0')
        if t in 'NF':
            return raw.decode('ascii', 'replace').strip()           # exact digits as stored: "4.20" stays "4.20"
        if t == 'D':
            s = raw.decode('ascii', 'replace').strip()
            return '%s-%s-%s' % (s[:4], s[4:6], s[6:8]) if len(s) == 8 and s.isdigit() else ''
        if t == 'L':
            c = raw.decode('ascii', 'replace').strip().upper()
            return 'T' if c in ('T', 'Y') else 'F' if c in ('F', 'N') else ''
        if t == 'I':
            return str(struct.unpack('<i', raw)[0])
        if t == 'Y':                                                 # currency: 64-bit integer, four implied decimals
            return str(Decimal(struct.unpack('<q', raw)[0]).scaleb(-4))
        if t == 'B' and self.version in (0x30, 0x31, 0x32):
            return repr(struct.unpack('<d', raw)[0])
        if t == 'T':
            jd, ms = struct.unpack('<ii', raw)
            if not jd:
                return ''
            day = datetime.date.fromordinal(jd - 1721425)
            return '%sT%02d:%02d:%02d' % (day.isoformat(), ms // 3600000, ms // 60000 % 60, ms // 1000 % 60)
        if t in 'MGP':
            if not self.memo:
                return ''
            if len(raw) == 4:
                block = struct.unpack('<I', raw)[0]
            else:
                s = raw.decode('ascii', 'replace').strip()
                block = int(s) if s.isdigit() else 0
            return self.memo.read(block) if block else ''
        return raw.hex()

    def summary(self):
        recs = list(self.records())
        return {
            'file': os.path.basename(self.path), 'sha256': hashlib.sha256(self._data).hexdigest(), 'bytes': len(self._data),
            'version': VERSIONS.get(self.version, hex(self.version)), 'last_update': self.last_update and self.last_update.isoformat(),
            'codepage': self.encoding, 'codepage_byte': hex(self.codepage_byte), 'codepage_known': self.codepage_known,
            'records_in_header': self.header_count, 'records_found': len(recs), 'deleted': sum(r['_deleted'] for r in recs),
            'fields': self.schema(),
            'memo': None if self.memo is None else {'file': getattr(self.memo, 'name', None), 'missing': isinstance(self.memo, MissingMemo)},
        }


class Memo:
    def __init__(self, path, encoding):
        self.name = os.path.basename(path)
        with open(path, 'rb') as f:
            self._data = f.read()
        self.encoding = encoding
        self.fox = path.lower().endswith('.fpt')
        self.block = struct.unpack('>H', self._data[6:8])[0] if self.fox else 512
        self.block = self.block or 512

    def read(self, block):
        start = block * self.block
        d = self._data
        if start >= len(d):
            return ''
        if self.fox:
            _kind, length = struct.unpack('>II', d[start:start + 8])
            return d[start + 8:start + 8 + length].decode(self.encoding, 'replace')
        end = d.find(b'\x1a\x1a', start)
        return d[start:end if end >= 0 else len(d)].decode(self.encoding, 'replace')


class MissingMemo:
    """The table has memo fields but the memo file is not next to it: values come back empty and the extract says so."""

    def __init__(self, base):
        self.name = os.path.basename(base) + '.fpt'

    def read(self, _block):
        return ''


def decimal_or_none(text):
    try:
        return Decimal(text) if text not in ('', None) else None
    except InvalidOperation:
        return None
