"""What a person sees BEFORE an approval takes effect. An approve, verify, sign or post button never acts blindly: a dialog first shows what is
being approved (the key facts and figures), who prepared it and when, what was changed since and by whom (old and new values), the documents
attached to it, what the approval will do, and whether this person may do it (their role, and the maker-checker rule).

The dialog explains; it does not decide. Every rule is still enforced by the approval method itself on the server, so a person who bypasses
the dialog (an old browser tab, a programming interface) is refused exactly as before."""
from lxml import html

from odoo import _, api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import format_amount, format_date, format_datetime

# (model, method): label of the button, what it does, the role that may press it, who counts as the maker, the facts to show
APPROVALS = {
    ('ei.contract', 'action_approve'): ("Approve", "The contract becomes approved: delivery advices can be issued against it.",
                                        'ei_contract_da.group_ei_contract_approver', 'create_uid',
                                        ['contract_ref', 'parent_partner_id', 'contract_type', 'date', 'valid_from', 'valid_to', 'revision']),
    ('ei.da', 'action_approve'): ("Approve", "The delivery advice becomes approved: its quantities can be ordered and lifted.",
                                  'ei_contract_da.group_ei_contract_approver', 'create_uid',
                                  ['contract_id', 'parent_partner_id', 'date', 'amendment_no', 'total_mtl', 'lifted_mtl', 'remaining_to_lift']),
    ('ei.daily.order', 'action_approve'): ("Approve", "The daily order becomes approved and can be printed or emailed to the parent company.",
                                           'ei_daily_orders.group_ei_order_approver', 'create_uid',
                                           ['parent_partner_id', 'date', 'total_requested', 'total_remaining']),
    ('ei.lifting', 'action_verify'): ("Verify", "The loading counts as lifted: the verified weight becomes the quantity a customer invoice may be made from.",
                                      'ei_material_lifting.group_ei_lifting_reviewer', 'maker_id',
                                      ['da_id', 'customer_id', 'product_id', 'date', 'vehicle_no', 'gate_pass_no', 'weighbridge_no', 'claimed_mtl', 'weighed_mtl', 'discrepancy_mtl']),
    ('ei.cash.voucher', 'action_approve'): ("Approve and post", "The voucher is approved and posted to the cash book; the cash balance changes.",
                                            'ei_cashbook.group_ei_cash_approver', 'maker_id',
                                            ['kind', 'journal_id', 'date', 'amount', 'partner_id', 'category_id', 'description']),
    ('ei.cash.count', 'action_post_discrepancy'): ("Post difference", "The difference between the count and the book is posted as an adjustment.",
                                                   'ei_cashbook.group_ei_cash_approver', 'custodian_id',
                                                   ['journal_id', 'date', 'book_balance', 'counted_amount', 'discrepancy']),
    ('ei.bank.import', 'action_approve'): ("Approve", "The statement is approved: its lines are accepted as what the bank says.",
                                           'ei_bank_operations.group_ei_bank_approver', 'imported_by',
                                           ['journal_id', 'filename', 'opening_balance', 'closing_balance', 'opening_diff', 'closing_diff', 'n_lines', 'n_duplicate', 'n_open']),
    ('ei.bank.import', 'action_post'): ("Post to ledger", "The statement is posted to the books: bank balances in the ledger change.",
                                        'ei_bank_operations.group_ei_bank_poster', 'imported_by',
                                        ['journal_id', 'filename', 'opening_balance', 'closing_balance', 'closing_diff', 'n_lines', 'n_open']),
    ('ei.supplier.intake', 'action_override'): ("Accept mismatch", "The supplier invoice is accepted although it differs from what was expected; the difference is recorded against your name.",
                                                'ei_invoice_extensions.group_ei_invoice_approver', 'maker_id',
                                                ['partner_id', 'invoice_number', 'invoice_date', 'stated_total', 'expected_total', 'stated_tax', 'expected_tax']),
    ('ei.parent.statement', 'action_sign'): ("Sign off", "The reconciliation with the parent company is signed off for this period.",
                                             'ei_parent_reconciliation.group_ei_recon_approver', 'imported_by',
                                             ['partner_id', 'date_from', 'date_to', 'statement_total', 'internal_total', 'n_matched', 'n_exceptions', 'n_open']),
    ('ei.import.batch', 'action_sign'): ("Sign", "The import of old codes is signed as checked.",
                                         'ei_legacy_master.group_ei_mapping_approver', 'imported_by',
                                         ['filename', 'total_expected', 'total_rows', 'total_created', 'total_changed', 'total_skipped']),
    ('ei.formula.definition', 'action_approve'): ("Approve", "The formula version becomes the one in force from its start date.",
                                                  'ei_contract_da.group_ei_formula_approver', 'create_uid',
                                                  ['code', 'version', 'effective_from', 'effective_to', 'rounding_mode']),
    ('ei.trade.lc', 'action_verify'): ("Verify", "The LC record is verified as matching the bank's documents.",
                                       'ei_trade_lc.group_ei_trade_manager', 'create_uid',
                                       ['lc_reference', 'supplier_id', 'bank_journal_id', 'expiry_date', 'quantity_mtl', 'lc_amount']),
}
# figures a checker should not miss: shown as a warning when they are not zero
WATCH = {'discrepancy_mtl': "The weighed quantity differs from what was claimed.", 'discrepancy': "The count differs from the book.",
         'opening_diff': "The opening balance differs from the ledger.", 'closing_diff': "The closing balance does not follow from the lines.",
         'n_duplicate': "Some lines look like lines already imported.", 'n_exceptions': "Some lines do not match.",
         'total_skipped': "Some rows were skipped."}


class EiApprovalEvidence(models.AbstractModel):
    _name = 'ei.approval.evidence'
    _description = "What is shown before an approval"

    @api.model
    def approval_buttons(self):
        """{model: [methods]} of the buttons that open the dialog, for the models this person may read."""
        out = {}
        for model, method in APPROVALS:
            if model in self.env and self.env[model].has_access('read'):
                out.setdefault(model, []).append(method)
        return out

    def _value(self, rec, name):
        f = rec._fields.get(name)
        if not f:
            return None
        v = rec[name]
        if f.type == 'many2one':
            return v.display_name or ''
        if f.type == 'selection':
            return dict(f._description_selection(self.env)).get(v, '') if v else ''
        if f.type == 'monetary':
            cur = rec[f.get_currency_field(rec)] if f.get_currency_field(rec) in rec._fields else self.env.company.currency_id
            return format_amount(self.env, v or 0.0, cur or self.env.company.currency_id)
        if f.type == 'float':
            return f"{v or 0.0:,.3f}"
        if f.type == 'integer':
            return f"{v or 0:,}"
        if f.type == 'date':
            return format_date(self.env, v) if v else ''
        return v or ''

    @api.model
    def get_evidence(self, model, res_id, method):
        spec = APPROVALS.get((model, method))
        if not spec or model not in self.env:
            return False
        verb, effect, group, maker_field, fact_names = spec
        rec = self.env[model].browse(int(res_id)).exists()
        if not rec:
            return False
        rec.check_access('read')                                                    # never more than this person may already see
        me = self.env.user
        Model = self.env[model]
        facts = []
        for n in fact_names:
            v = self._value(rec, n)
            if v not in (None, '', False):
                facts.append(dict(label=Model._fields[n]._description_string(self.env), value=str(v)))
        warnings = []
        for n, text in WATCH.items():
            if n in fact_names and rec._fields.get(n) and abs(rec[n] or 0) > 1e-9:
                warnings.append(_("%(t)s (%(f)s: %(v)s)", t=_(text), f=Model._fields[n]._description_string(self.env), v=self._value(rec, n)))
        if model == 'ei.supplier.intake' and abs((rec.stated_total or 0) - (rec.expected_total or 0)) > 1e-6:
            warnings.append(_("Invoice total %(s)s against %(e)s expected: a difference of %(d)s.", s=self._value(rec, 'stated_total'), e=self._value(rec, 'expected_total'),
                              d=format_amount(self.env, (rec.stated_total or 0) - (rec.expected_total or 0), self.env.company.currency_id)))

        maker = rec[maker_field] if maker_field in rec._fields else self.env['res.users']
        self_made = bool(maker) and maker == me
        role = self.env.ref(group, raise_if_not_found=False)
        has_role = bool(role) and me.has_group(group)
        blocked = ''
        if not has_role:
            blocked = _("You do not hold the role this needs (%s). Ask someone who does.", role.name if role else group)
        elif self_made:
            blocked = _("You prepared this, so a second person must %s it. That is the maker-checker rule.", _(verb).lower())

        changes = []
        if 'message_ids' in rec._fields:
            # Odoo 20 keeps a tracked change in the message text: "<div>old → <b>new</b> <i>(Field)</i></div>", one div per field
            msgs = self.env['mail.message'].sudo().search([('model', '=', model), ('res_id', '=', rec.id), ('message_type', '=', 'tracking')], order='date desc, id desc', limit=12)
            for m in msgs:
                for div in (html.fromstring(f"<section>{m.body or ''}</section>").xpath('//div') if m.body else []):
                    new, field = div.find('b'), div.find('i')
                    old = (div.text or '').replace('→', '').strip()
                    changes.append(dict(when=format_datetime(self.env, m.date, dt_format='dd MMM yyyy HH:mm'), who=m.author_id.name or '',
                                        field=(field.text_content() if field is not None else '').strip(' ()'), old=old,
                                        new=new.text_content().strip() if new is not None else ''))
        docs = self.env['ei.documents'].list_for(model, rec.id)
        return dict(
            model=model, res_id=rec.id, method=method, verb=_(verb), title=_("%(v)s %(n)s?", v=_(verb), n=rec.display_name),
            kind=Model._description, name=rec.display_name, facts=facts, warnings=warnings, effect=_(effect),
            maker=dict(name=maker.name or rec.create_uid.name or '', when=format_datetime(self.env, rec.create_date, dt_format='dd MMM yyyy HH:mm') if rec.create_date else ''),
            last=dict(name=rec.write_uid.name or '', when=format_datetime(self.env, rec.write_date, dt_format='dd MMM yyyy HH:mm') if rec.write_date else ''),
            you=dict(name=me.name, role=role.name if role else '', has_role=has_role, self_made=self_made),
            blocked=blocked, changes=changes[:12], documents=docs,
        )
