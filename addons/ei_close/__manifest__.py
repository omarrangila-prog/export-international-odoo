{
    'name': 'Export International - Day and month close',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Daily and month-end close checklists with blockers, waivers and sign-off; party balances against the control accounts; '
               'the reconciliation centre that shows every reconciliation in one place.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_ui_theme'],
    'data': [
        'security/ir.access.csv',
        'views/subledger_views.xml',
        'views/close_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_close/static/src/centre/centre.scss',
            'ei_close/static/src/centre/centre.js',
            'ei_close/static/src/centre/centre.xml',
        ],
    },
    'installable': True,
}
