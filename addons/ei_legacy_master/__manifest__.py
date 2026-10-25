{
    'name': 'Export International - Legacy Code Master',
    'version': '20.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Raw legacy code registry, audited import and accountant-approved mapping queue',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'wizard/import_wizard_views.xml',
        'views/legacy_code_views.xml',
        'views/import_batch_views.xml',
        'views/menus.xml',
    ],
    'application': True,
    'installable': True,
}
