from odoo import Command


def give_the_administrator_the_app(env):
    """So the app is on the main screen straight after installing. Only the administrator; everyone else gets a role from Settings > Users."""
    admin = env.ref('base.user_admin', raise_if_not_found=False)
    if admin:
        admin.write({'group_ids': [Command.link(env.ref('ei_management_dashboard.group_ei_management').id)]})


# The owner's instruction (17 Nov 2026): every internal user may do everything in Export International, and the
# client's imported codes count as verified. base.group_user implies every role below, so present and future users
# get them all. For now the maker-checker rule is off too: one person may enter and approve the same record.
OPEN_ROLES = (
    'ei_legacy_master.group_ei_user', 'ei_legacy_master.group_ei_importer', 'ei_legacy_master.group_ei_mapping_approver',
    'ei_legacy_master.group_ei_auditor',
    'ei_bank_operations.group_ei_bank_officer', 'ei_bank_operations.group_ei_bank_approver', 'ei_bank_operations.group_ei_bank_poster',
    'ei_cashbook.group_ei_cash_clerk', 'ei_cashbook.group_ei_cash_approver',
    'ei_contract_da.group_ei_contract_staff', 'ei_contract_da.group_ei_contract_approver', 'ei_contract_da.group_ei_da_override',
    'ei_contract_da.group_ei_formula_approver', 'ei_daily_orders.group_ei_order_approver',
    'ei_invoice_extensions.group_ei_invoicing', 'ei_invoice_extensions.group_ei_invoice_approver',
    'ei_management_dashboard.group_ei_management',
    'ei_material_lifting.group_ei_dispatch_officer', 'ei_material_lifting.group_ei_lifting_reviewer',
    'ei_parent_reconciliation.group_ei_recon_user', 'ei_parent_reconciliation.group_ei_recon_approver',
    'ei_trade_lc.group_ei_trade_manager', 'account.group_account_user',
)


def open_everything(env):
    """Only where the deploy package carries client_data/open_access (the client's own Production package);
    the source and test databases keep separate roles, so the role checks stay tested."""
    import logging
    import os
    log = logging.getLogger(__name__)
    if not os.path.isfile(os.path.join(os.path.dirname(__file__), 'client_data', 'open_access')):
        log.info("export_international: separate roles (no open_access marker in this package)")
        return
    roles = [g for g in (env.ref(x, raise_if_not_found=False) for x in OPEN_ROLES) if g]
    env.ref('base.group_user').write({'implied_ids': [Command.link(g.id) for g in roles]})
    # for now one person may also enter and approve the same record (owner, 17 Nov 2026); set it back to True to restore
    env['ir.config_parameter'].sudo().set_bool('ei_legacy_master.enforce_maker_checker', False)
    # and no workflow waits for approval: Save & Submit confirms at once (owner, 17 Nov 2026)
    env['ei.approval.policy'].sudo().set_all(False)
    # nor is the DA paper required before Save & Continue (it can still be attached)
    env['ir.config_parameter'].sudo().set_bool('ei_contract_da.require_da_paper', False)
    env['ir.config_parameter'].sudo().set_bool('ei_cashbook.require_receipt', False)    # a cash voucher's receipt: optional too
    env['ir.config_parameter'].sudo().set_bool('ei_da_feeding.link_codes_on_entry', True)  # a coil's customer and its old code are linked on entry
    env['ir.config_parameter'].sudo().set_bool('ei_material_lifting.require_proof', False)   # a loading's gate-pass paper: optional
    env['ir.config_parameter'].sudo().set_bool('ei_app_shell.confirm_summary', False)        # no 'Verify ...?' summary before confirming
    env['ir.config_parameter'].sudo().set_bool('ei_invoice_extensions.require_document', False)  # the supplier invoice's scan: optional
    # a cash voucher needs a cash box: a fresh database without a chart's Cash journal gets one, so the screen is never empty
    J = env['account.journal'].sudo()
    for company in env['res.company'].sudo().search([]):
        if not J.search_count([('type', '=', 'cash'), ('company_id', '=', company.id)]):
            try:
                with env.cr.savepoint():
                    J.with_company(company).create({'name': 'Cash', 'type': 'cash', 'code': 'CSH', 'company_id': company.id})
                    log.info("export_international: Cash journal opened for %s", company.name)
            except Exception as e:  # noqa: BLE001 - a chart without the accounts it needs must not stop the upgrade
                log.warning("export_international: no Cash journal for %s: %s", company.name, e)
    Code = env['ei.legacy.code'].sudo()
    todo = Code.search([('verification_status', 'in', ('unverified', 'proposed', 'needs_review'))])  # a code the accountant rejected stays rejected
    done = failed = 0
    for c in todo:
        try:
            with env.cr.savepoint():
                c.action_approve(c.approved_target_type or c.proposed_target_type or 'legacy_ref_only',
                                 c.approval_note or "Verified on import at the owner's instruction (17 Nov 2026).")
            done += 1
        except Exception as e:  # noqa: BLE001 - one odd code must not stop the rest
            failed += 1
            log.warning("export_international: code %s left for the accountant: %s", c.legacy_code, e)
    log.info("export_international: %s roles for every user; %s codes verified, %s left", len(roles), done, failed)
    _feeding_formulas(env, log)


def _feeding_formulas(env, log):
    """The client's mills and their rate formula (client_data/feeding_setup.json, private package only): the formula is approved
    on the owner's instruction for the accountant, and each named mill uses it, so Basic rate + the sale offset work as in FoxPro."""
    import json
    import os
    path = os.path.join(os.path.dirname(__file__), 'client_data', 'feeding_setup.json')
    if not os.path.isfile(path):
        return
    cfg = json.load(open(path))
    F = env['ei.formula.definition'].sudo()
    for item in cfg.get('formulas', []):
        f = F.search([('code', '=', item['code']), ('state', '=', 'approved')], order='version desc', limit=1)
        if not f:
            f = F.search([('code', '=', item['code']), ('state', '=', 'draft')], order='version desc', limit=1)
            if not f:
                log.warning("export_international: formula %s not found", item['code'])
                continue
            failed = [t.name for t, ok in f.run_tests() if not ok]
            if failed:
                log.warning("export_international: formula %s not approved, test cases fail: %s", f.code, failed)
                continue
            f.action_approve()
            f.message_post(body=item.get('note') or "Approved on the owner's instruction for the accountant.")
            log.info("export_international: formula %s v%s approved", f.code, f.version)
        P = env['res.partner'].sudo()
        for name in item.get('suppliers', []):
            mill = P.search([('name', '=ilike', name)], limit=1) or P.create({'name': name, 'is_company': True})
            mill.write({'ei_is_supplier_mill': True, 'ei_feeding_formula_id': f.id, 'supplier_rank': mill.supplier_rank or 1})
            # material lines of this mill opened before the formula was approved take it too, unless a DA on them is already confirmed
            lines = env['ei.contract.line'].sudo().search([('contract_id.contract_type', '=', 'feeding'), ('contract_id.parent_partner_id', '=', mill.id),
                                                          ('formula_id', '=', False)])
            for line in lines:
                if any(dl.da_id.state not in ('draft', 'cancelled') for dl in line.da_line_ids):
                    continue
                test = f.test_ids[:1]
                params = json.loads(test.params_json or '{}') if test else {}
                for k in f._param_names():
                    params.setdefault(k, '0')
                line.with_context(ei_system=True).write({'formula_id': f.id, 'cost_class': 'commission', 'param_ids': [(5, 0, 0)] + [
                    (0, 0, {'key': k, 'value': str(v)}) for k, v in params.items()]})
            log.info("export_international: %s uses formula %s", mill.name, f.code)


def post_init_hook(env):
    give_the_administrator_the_app(env)
    open_everything(env)
