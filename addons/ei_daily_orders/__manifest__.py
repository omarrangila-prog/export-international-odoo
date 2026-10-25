{
    'name': 'Export International - Daily Order Request',
    'version': '20.0.1.0.0',
    'category': 'Sales/Purchase',
    'summary': 'Daily Order Request generated idempotently from approved DAs, printable, linkable to later supplier invoices',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_contract_da', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/sequence.xml',
        'report/order_report.xml',
        'views/order_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
