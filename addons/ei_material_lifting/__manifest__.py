{
    'name': 'Export International - Material Lifting',
    'version': '20.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Verified physical lifting (gate pass, weighbridge, receipt) separate from invoices, with over-lifting control',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_daily_orders'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'data/sequence.xml',
        'views/lifting_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
