from odoo import models
from odoo.tools import SQL


class EiReportBase(models.AbstractModel):
    """A report model is a read-only SQL view: _select_sql() writes the SELECT (one row per record the report is about, with an id column),
    and Odoo uses it as the table. Nothing here can change a record."""
    _name = 'ei.report.base'
    _description = "Report base"

    def _select_sql(self):
        raise NotImplementedError

    @property
    def _table_sql(self):
        return SQL("(%s)", self._select_sql())

    def _open_record(self, record, title=None):
        """The window action that opens one real record: a row of a report always leads to the document behind it."""
        record.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': title or record.display_name, 'res_model': record._name, 'res_id': record.id,
                'views': [[False, 'form']], 'target': 'current'}
