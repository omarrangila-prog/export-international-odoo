{
    'name': 'Export International - Online Banking',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Bank statement import, duplicate guards, balance matching, verified allocation and daily posting review',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_legacy_master', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'wizard/import_wizard_views.xml',
        'views/bank_import_views.xml',
        'views/other_views.xml',
        'views/legacy_code_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
