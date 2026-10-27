"""The reconciliation centre: every reconciliation of the business on one page, each answering "does it agree, what is open, since
when, who signed last". Read-only. Each section is shown only to people who may read its records, and everything opens the records
behind it with the person's own rights."""
from odoo import api, fields, models, _

STATUS_ORDER = {'attention': 0, 'blocked': 1, 'ok': 2}


class EiReconCentre(models.AbstractModel):
    _name = 'ei.recon.centre'
    _description = 'Reconciliation centre'

    def _can(self, model):
        return model in self.env and self.env[model].has_access('read')

    @staticmethod
    def _age(d, today):
        return (today - d).days if d else None

    def _act(self, xmlid):
        return xmlid if self.env.ref(xmlid, raise_if_not_found=False) else False

    @api.model
    def get_overview(self):
        env, today = self.env, fields.Date.context_today(self)
        co = env.companies.ids
        cards = []

        def card(key, code, title, question, status, figures, action, note='', rows=None, signed=None):
            cards.append({'key': key, 'code': code, 'title': title, 'question': question, 'status': status, 'figures': figures,
                          'action': self._act(action) if action else False, 'note': note, 'rows': rows or [], 'signed': signed})

        fmt = lambda u, t: {'who': u.name, 'when': fields.Datetime.to_string(t)} if u else None

        # R1 bank book vs bank
        if self._can('ei.bank.balance.check'):
            Chk = env['ei.bank.balance.check']
            rows, open_n = [], 0
            for j in env['account.journal'].search([('type', '=', 'bank'), ('company_id', 'in', co)]):
                last = Chk.search([('journal_id', '=', j.id)], order='date desc, id desc', limit=1)
                book = j._ei_ledger_balance(today)
                ok = last and last.date == today and last.state == 'signed'
                open_n += not ok
                rows.append({'name': j.name, 'book': book, 'bank': last.bank_balance if last else None, 'date': str(last.date) if last else '',
                             'unexplained': last.unexplained_difference if last else None,
                             'proof': dict(Chk._fields['evidence_state'].selection).get(last.evidence_state) if last else '',
                             'state': dict(Chk._fields['state'].selection).get(last.state) if last else _("Never confirmed")})
            last_signed = Chk.search([('state', '=', 'signed')], order='signed_at desc', limit=1)
            card('r1', 'R1', _("Bank book against the bank"), _("Does each bank account in our books agree with what the bank says today?"),
                 'attention' if open_n else 'ok', [{'label': _("Accounts not signed off today"), 'value': open_n}],
                 'ei_bank_operations.ei_balance_check_action', _("A typed balance is not bank-confirmed until the bank's proof is attached."),
                 rows=rows, signed=fmt(last_signed.signed_by, last_signed.signed_at))
        # R2 bank line -> party -> invoice
        if self._can('ei.bank.import.line'):
            L = env['ei.bank.import.line']
            open_lines = L.search([('company_id', 'in', co), ('state', 'in', ('new', 'proposed', 'verified', 'unidentified'))], order='date asc')
            oldest = open_lines[:1].date
            card('r2', 'R2', _("Bank receipts to parties and invoices"), _("Which money has the bank shown that is not yet given to a party and its invoices?"),
                 'attention' if open_lines else 'ok',
                 [{'label': _("Lines waiting"), 'value': len(open_lines)},
                  {'label': _("Of which unidentified"), 'value': len(open_lines.filtered(lambda l: l.state == 'unidentified'))},
                  {'label': _("Oldest waiting (days)"), 'value': self._age(oldest, today) or 0}],
                 'ei_matching.action_ei_matching' if env.ref('ei_matching.action_ei_matching', raise_if_not_found=False) else 'ei_bank_operations.ei_bank_line_action',
                 _("A payment screenshot is never treated as money received: only a bank statement line can be given to an invoice."))
        # R3 party balances vs control accounts
        if self._can('ei.subledger.check'):
            S = env['ei.subledger.check']
            figs, stale = [], 0
            for kind, label in S._fields['kind'].selection:
                last = S.search([('kind', '=', kind), ('state', '=', 'signed'), ('company_id', 'in', co)], order='date desc', limit=1)
                age = self._age(last.date, today)
                stale += age is None or age > 31
                figs.append({'label': _("%s: last signed off", label), 'value': str(last.date) if last else _("never")})
            last = S.search([('state', '=', 'signed')], order='signed_at desc', limit=1)
            card('r3', 'R3', _("Party balances against the control accounts"), _("Do customers' and suppliers' balances add up to the ledger?"),
                 'attention' if stale else 'ok', figs, 'ei_close.ei_subledger_action', signed=fmt(last.signed_by, last.signed_at))
        # R4 contract -> DA
        if self._can('ei.contract.line') and self._can('ei.da'):
            over = env['ei.contract.line'].search_count([('company_id', 'in', co), ('remaining_mtl', '<', 0)])
            review = env['ei.da'].search_count([('company_id', 'in', co), ('state', '=', 'under_review')])
            card('r4', 'R4', _("Contracts and delivery advices"), _("Is every delivery advice within its contract's quantity?"),
                 'attention' if over or review else 'ok',
                 [{'label': _("Contract lines promised beyond their quantity"), 'value': over}, {'label': _("DAs waiting for approval"), 'value': review}],
                 'ei_contract_da.ei_da_action')
        # R5 order -> invoice -> physical lifting
        if self._can('ei.daily.order.line'):
            lines = env['ei.daily.order.line'].search([('company_id', 'in', co), ('state', '=', 'approved')])
            billed_not_lifted = lines.filtered(lambda l: l.invoice_ref and l.lifted_mtl + 1e-9 < l.requested_mtl)
            lifted_not_billed = lines.filtered(lambda l: not l.invoice_ref and l.lifted_mtl > 0)
            card('r5', 'R5', _("Order requests, supplier invoices and lifting"), _("What was invoiced but not lifted, or lifted with no supplier invoice yet?"),
                 'attention' if billed_not_lifted or lifted_not_billed else 'ok',
                 [{'label': _("Invoiced, not fully lifted"), 'value': len(billed_not_lifted)},
                  {'label': _("Lifted, no supplier invoice yet"), 'value': len(lifted_not_billed)}],
                 'ei_daily_orders.ei_daily_order_action', _("An invoice number never counts as a lifting: only verified loadings do."))
        # R6 supplier invoice vs contract / DA
        if self._can('ei.supplier.intake'):
            I = env['ei.supplier.intake']
            mism = I.search_count([('company_id', 'in', co), ('state', '=', 'mismatch')])
            card('r6', 'R6', _("Supplier invoices against contract and DA"), _("Which supplier invoices disagree with what was agreed?"),
                 'attention' if mism else 'ok',
                 [{'label': _("Blocked on a mismatch"), 'value': mism},
                  {'label': _("Not yet checked"), 'value': I.search_count([('company_id', 'in', co), ('state', '=', 'draft')])}],
                 'ei_invoice_extensions.ei_intake_action')
        # R7 parent statements
        if self._can('ei.parent.statement.line'):
            PL = env['ei.parent.statement.line']
            open_l = PL.search([('company_id', 'in', co), ('status', '!=', 'matched'), ('resolution_state', '=', 'open'),
                                ('statement_id.state', 'not in', ('signed', 'rejected'))])
            unsigned = env['ei.parent.statement'].search_count([('company_id', 'in', co), ('state', 'not in', ('signed', 'rejected'))])
            last = env['ei.parent.statement'].search([('state', '=', 'signed')], order='signed_at desc', limit=1)
            card('r7', 'R7', _("Parent-company month-end statements"), _("Where does the parent's ledger disagree with ours?"),
                 'attention' if open_l or unsigned else 'ok',
                 [{'label': _("Open differences"), 'value': len(open_l)}, {'label': _("Their amount"), 'value': sum(open_l.mapped('difference')), 'money': True},
                  {'label': _("Statements not signed off"), 'value': unsigned}],
                 'ei_parent_reconciliation.ei_parent_statement_action', signed=fmt(last.signed_by, last.signed_at))
        # R8 cash
        if self._can('ei.cash.count'):
            C = env['ei.cash.count']
            boxes = env['account.journal'].search([('type', '=', 'cash'), ('company_id', 'in', co)])
            missing = boxes.filtered(lambda j: not C.search_count([('journal_id', '=', j.id), ('date', '=', today), ('state', '=', 'closed')]))
            card('r8', 'R8', _("Cash count"), _("Was every cash box counted and closed today?"), 'attention' if missing else 'ok',
                 [{'label': _("Cash boxes not closed today"), 'value': len(missing)}], 'ei_cashbook.ei_cash_count_action')
        # R9 migration
        if self._can('ei.import.batch'):
            B = env['ei.import.batch']
            last = B.search([('state', '!=', 'failed')], order='imported_at desc', limit=1)
            card('r9', 'R9', _("Old system (FoxPro) to Odoo"), _("Does what was brought over agree with the old system's own totals?"), 'blocked',
                 [{'label': _("Old codes: last import"), 'value': '%s rows, %s' % (last.total_rows, dict(B._fields['state'].selection)[last.state]) if last else _("none")}],
                 'ei_legacy_master.ei_import_batch_action',
                 _("Only the code list is migrated. FoxPro files, opening balances and the old system's control totals have not been received."))
        # R10 FBR
        if self._can('ei.compliance.submission'):
            Sub = env['ei.compliance.submission']
            n = Sub.search_count([('state', '!=', 'submitted')])
            card('r10', 'R10', _("FBR e-invoicing"), _("Which posted invoices did the tax authority accept?"), 'blocked',
                 [{'label': _("Waiting (not configured or failed)"), 'value': n}], False,
                 _("Not connected: registration, integrator and credentials are pending. Nothing is shown as accepted."))
        if self._can('ei.close'):
            last = env['ei.close'].search([('state', '=', 'signed')], order='signed_at desc', limit=1)
            open_c = env['ei.close'].search([('state', '=', 'open'), ('company_id', 'in', co)])
            card('close', _("Close"), _("Day and month close"), _("Is the day or month closed, and what still blocks it?"),
                 'attention' if open_c else 'ok', [{'label': _("Closes not signed off"), 'value': len(open_c)},
                                                    {'label': _("Last signed"), 'value': last.name or _("never")}],
                 'ei_close.ei_close_action', signed=fmt(last.signed_by, last.signed_at))
        cards.sort(key=lambda c: STATUS_ORDER.get(c['status'], 9))
        return {'cards': cards, 'today': str(today), 'currency': env.company.currency_id.symbol,
                'attention': sum(c['status'] == 'attention' for c in cards)}
