{
    'name': 'Export International - Online Feeding and Cash Book',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Two-sided entries in the old codes (credit code, debit code, amount), as fed in the old system: online bank feeding, '
               'cash book, balance brought forward; maker-checker, ledgers by code and a printed day book. PKR only.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_approvals', 'ei_cashbook', 'ei_bank_operations', 'ei_da_feeding', 'ei_reports'],
    'data': [
        'security/ir.access.csv',
        'data/sequence.xml',
        'report/daybook_report.xml',
        'views/daybook_views.xml',
        'views/menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
