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


def post_init_hook(env):
    give_the_administrator_the_app(env)
    open_everything(env)
