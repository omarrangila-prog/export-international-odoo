{
    'name': 'Export International - Parent Ledger Reconciliation',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Monthly parent-company statement matching by invoice number with owned, approved exception resolution',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_invoice_extensions'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/sequence.xml',
        'report/statement_report.xml',
        'views/statement_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
