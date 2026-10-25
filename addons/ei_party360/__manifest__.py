{
    'name': 'Export International - Party 360',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'One page per customer or supplier: old codes, material chain, money, bank evidence and history',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_ui_theme'],
    'data': [
        'views/party360_views.xml',
        'views/partner_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_party360/static/src/party360/party360.scss',
            'ei_party360/static/src/party360/party360.js',
            'ei_party360/static/src/party360/party360.xml',
        ],
    },
    'installable': True,
}
