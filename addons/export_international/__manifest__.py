{
    'name': 'Export International ERP',
    'version': '20.0.1.0.1',
    'category': 'Accounting',
    'summary': 'The whole Export International system in one install: contracts, orders, trucks, bank, cash, invoices, parent statements, reports and close.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': [
        'ei_legacy_master', 'ei_bank_operations', 'ei_cashbook', 'ei_contract_da', 'ei_daily_orders', 'ei_material_lifting',
        'ei_invoice_extensions', 'ei_parent_reconciliation', 'ei_trade_lc', 'ei_management_dashboard', 'ei_ui_theme', 'ei_party360',
        'ei_automation', 'ei_matching', 'ei_assistant', 'ei_reports', 'ei_pin_login', 'ei_app_shell', 'ei_close', 'ei_migration', 'ei_da_feeding', 'ei_approvals',
    ],
    'post_init_hook': 'give_the_administrator_the_app',
    'application': True,
    'installable': True,
}
