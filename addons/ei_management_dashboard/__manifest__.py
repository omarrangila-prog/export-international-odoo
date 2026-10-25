{
    'name': 'Export International - Management Dashboard & Approvals',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Role-based dashboard on posted records with freshness labels, drill-down, approvals queue, daily summary',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_bank_operations', 'ei_cashbook', 'ei_contract_da', 'ei_daily_orders', 'ei_material_lifting',
                'ei_invoice_extensions', 'ei_parent_reconciliation', 'ei_trade_lc'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'report/dashboard_report.xml',
        'views/dashboard_views.xml',
        'views/menus.xml',
        'data/cron.xml',
    ],
    'installable': True,
}
