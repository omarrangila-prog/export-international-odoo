{
    'name': 'Export International - Payment matching',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'One screen to decide who paid and which invoices a bank line settles, with the evidence and the effect beside it',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_bank_operations', 'ei_ui_theme', 'ei_party360'],
    'data': [
        'views/matching_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_matching/static/src/matching/matching.scss',
            'ei_matching/static/src/matching/matching.js',
            'ei_matching/static/src/matching/matching.xml',
        ],
    },
    'installable': True,
}
