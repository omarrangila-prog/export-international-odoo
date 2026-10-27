from odoo import api, models

TITLES = {'summary': "Summary", 'pnl': "Profit and loss", 'balance_sheet': "Balance sheet", 'trial_balance': "Trial balance", 'cash_flow': "Cash flow"}


class ReportFinancial(models.AbstractModel):
    _name = 'report.ei_reports.report_financial'
    _description = "Financial statement (preview) as a PDF"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        d = self.env['ei.report.financials'].get_statements(data.get('date_from'), data.get('date_to'))
        cur = self.env.company.currency_id

        def money(v):
            return f"{v:,.2f}"
        return {'doc_ids': [], 'doc_model': 'ei.report.financials', 'docs': self.env['ei.report.financials'], 'd': d, 'money': money, 'currency': cur.name,
                'statement': data.get('statement') or 'pnl', 'title': TITLES.get(data.get('statement') or 'pnl', "Statement")}
