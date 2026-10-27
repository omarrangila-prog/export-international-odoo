"""Writes small synthetic FoxPro 2.x tables (with a memo file) for the tests. Synthetic data only."""
import struct


def write_table(path, fields, rows, codepage=0x7E, memo_texts=None, deleted=()):
    """fields: [(name, type, length, decimals)]; rows: list of lists of raw text values (memo fields take a memo index)."""
    memo_texts = memo_texts or []
    header_len = 32 + 32 * len(fields) + 1
    record_len = 1 + sum(f[2] for f in fields)
    has_memo = any(f[1] == 'M' for f in fields)
    head = struct.pack('<BBBBIHH', 0xF5 if has_memo else 0x03, 126, 10, 27, len(rows), header_len, record_len)
    head += b'\0' * 17 + bytes([codepage]) + b'\0\0'
    for name, t, length, dec in fields:
        head += name.encode('ascii').ljust(11, b'\0') + t.encode('ascii') + b'\0' * 4 + bytes([length, dec]) + b'\0' * 14
    head += b'\x0d'
    blocks, memo = [], b''
    if has_memo:
        size, nxt = 64, 8
        for text in memo_texts:
            data = text.encode('cp1256')
            chunk = struct.pack('>II', 1, len(data)) + data
            chunk += b'\0' * (-len(chunk) % size)
            blocks.append(nxt)
            memo += chunk
            nxt += len(chunk) // size
        memo = struct.pack('>I', nxt) + b'\0\0' + struct.pack('>H', size) + b'\0' * 504 + memo
    body = b''
    for i, row in enumerate(rows):
        rec = b'*' if i in deleted else b' '
        for (name, t, length, dec), v in zip(fields, row):
            if t == 'M':
                rec += (str(blocks[v]).rjust(length).encode('ascii') if v is not None else b' ' * length)
            elif t == 'N':
                rec += str(v).rjust(length).encode('ascii')
            else:
                rec += str(v).encode('cp1256').ljust(length, b' ')[:length]
        body += rec
    with open(path, 'wb') as f:
        f.write(head + body + b'\x1a')
    if has_memo:
        with open(path[:-4] + '.fpt', 'wb') as f:
            f.write(memo)
