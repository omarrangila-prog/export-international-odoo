{
    'name': 'Export International - Sign-in with a PIN',
    'version': '20.0.1.1.0',
    'category': 'Hidden',
    'summary': 'Second way to sign in: a personal four-digit PIN (alone, no user name), beside user name and password. Keyed hash, pauses and '
               'locks after wrong tries, optional network allow-list, a sign-in log, the web page only (never the programming interfaces).',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_ui_theme', 'ei_management_dashboard', 'ei_legacy_master'],
    'data': [
        'security/ir.access.csv',
        'data/params.xml',
        'views/login_templates.xml',
        'views/pin_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ei_pin_login/static/src/login/pin_login.scss',
            'ei_pin_login/static/src/login/pin_tabs.js',
        ],
        'web.assets_backend': [
            'ei_pin_login/static/src/dialog/pin_dialog.scss',
            'ei_pin_login/static/src/dialog/pin_dialog.js',
            'ei_pin_login/static/src/dialog/pin_dialog.xml',
        ],
    },
    'installable': True,
}
