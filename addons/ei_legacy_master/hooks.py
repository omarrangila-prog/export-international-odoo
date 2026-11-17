"""Loads the client's own code list when the deploy package carries it.

The file is the client's real data, so it is never in the public source: the private deploy package adds it at
client_data/EXI_legacy_codes.csv. Without the file nothing happens. With it, the same audited import as
More > Setup > Import Codes runs once per file (matched by its sha256), so an upgrade never loads it twice and a
changed file is loaded as a new batch whose differences are logged. Imported codes start "not verified": the
accountant still verifies them before entries using them can be approved.
"""
import hashlib
import logging
import os

_logger = logging.getLogger(__name__)
CLIENT_FILE = os.path.join(os.path.dirname(__file__), 'client_data', 'EXI_legacy_codes.csv')


def autoload_client_codes(env):
    if not os.path.isfile(CLIENT_FILE):
        _logger.info("ei_legacy_master: no client code list in the package; codes are imported from the screen")
        return False
    with open(CLIENT_FILE, 'rb') as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    Batch = env['ei.import.batch'].sudo()
    if Batch.search_count([('file_sha256', '=', sha), ('state', 'in', ('imported', 'signed'))]):
        _logger.info("ei_legacy_master: client code list %s already imported", sha[:12])
        return False
    batch = Batch.import_file(os.path.basename(CLIENT_FILE), data)
    _logger.info("ei_legacy_master: client code list loaded: %s %s, %s rows, %s new, %s unchanged, %s changed",
                 batch.name, batch.state, batch.total_rows, batch.total_created, batch.total_unchanged, batch.total_changed)
    if batch.state != 'imported':
        _logger.warning("ei_legacy_master: client code list failed validation; nothing loaded:\n%s", batch.error_log)
    return batch


def post_init_hook(env):
    autoload_client_codes(env)
