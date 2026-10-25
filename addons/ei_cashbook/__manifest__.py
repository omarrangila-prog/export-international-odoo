{
    'name': 'Export International - Cash Book',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Cash vouchers with maker-checker, receipts, safe/bank transfers, daily cash count',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_legacy_master', 'account', 'analytic'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/sequence.xml',
        'report/cash_report.xml',
        'views/cash_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
