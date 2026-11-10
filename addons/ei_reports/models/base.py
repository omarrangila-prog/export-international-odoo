from odoo import _, models
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
        return self._if_allowed({'type': 'ir.actions.act_window', 'name': title or record.display_name, 'res_model': record._name,
                                 'res_id': record.id, 'views': [[False, 'form']], 'target': 'current'})

    def _if_allowed(self, action):
        """A report may show figures to people who may not open the records behind them (an accountant sees the bank book against the
        bank's confirmation, but the confirmations belong to the bank team). Clicking such a row says so, instead of an Access Error.
        The access rules themselves are unchanged."""
        model = action.get('res_model')
        if model and not self.env[model].has_access('read'):
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'type': 'info', 'sticky': False, 'title': _("Figures only"),
                'message': _("You can see these figures, but the %(what)s behind them belong to another team. Ask them to open it if you need the document.",
                             what=self.env['ir.model']._get(model).name)}}
        return action
