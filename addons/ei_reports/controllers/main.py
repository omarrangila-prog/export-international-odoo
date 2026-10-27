from odoo import http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.http.stream import content_disposition

STATEMENT_TITLES = {'summary': 'Summary', 'pnl': 'Profit and loss', 'balance_sheet': 'Balance sheet', 'trial_balance': 'Trial balance', 'cash_flow': 'Cash flow'}


class EiFinancialPdf(http.Controller):

    @http.route('/ei_reports/financial.pdf', type='http', auth='user')                 # not read-only: printing may build the report's style bundle
    def financial_pdf(self, statement='pnl', date_from=None, date_to=None, **kw):
        """The statement on screen as a PDF, worked out as the signed-in person (so it shows only what they may see)."""
        env = request.env
        fin = env['ei.report.financials']
        try:
            fin._require()
            if statement not in STATEMENT_TITLES:
                raise UserError(_("Unknown statement."))
            d_from, d_to = fin._period(date_from, date_to)
            pdf, _kind = env['ir.actions.report']._render_qweb_pdf('ei_reports.report_financial', res_ids=None,
                                                                    data={'statement': statement, 'date_from': str(d_from), 'date_to': str(d_to)})
        except (AccessError, UserError) as e:
            return request.make_response(str(e), headers=[('Content-Type', 'text/plain; charset=utf-8')], status=403 if isinstance(e, AccessError) else 400)
        name = f"Export-International-{STATEMENT_TITLES[statement].replace(' ', '-')}-{d_from}-{d_to}-PREVIEW.pdf"
        return request.make_response(pdf, headers=[('Content-Type', 'application/pdf'), ('Content-Length', len(pdf)), ('Content-Disposition', content_disposition(name))])
