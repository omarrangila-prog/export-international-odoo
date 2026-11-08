{
    'name': 'Export International - DA Feeding Desk',
    'version': '20.0.1.0.0',
    'category': 'Sales/Purchase',
    'summary': 'Feed a delivery advice coil by coil with the six feeding methods, codes, dates and currency; practise without posting',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_contract_da', 'ei_ui_theme'],
    'data': [
        'views/desk_views.xml',
        'views/da_views.xml',
        'views/report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_da_feeding/static/src/desk/desk.scss',
            'ei_da_feeding/static/src/desk/desk.js',
            'ei_da_feeding/static/src/desk/desk.xml',
        ],
    },
    'installable': True,
}
