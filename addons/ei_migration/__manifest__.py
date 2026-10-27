{
    'name': 'Export International - Old system (FoxPro) migration control',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Record read-only FoxPro extracts (file hashes, code pages, record and deleted counts) and compare control totals from the '
               'old system with the books, with sign-off. Nothing is posted from here.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_close'],
    'data': [
        'security/ir.access.csv',
        'views/migration_views.xml',
    ],
    'installable': True,
}
