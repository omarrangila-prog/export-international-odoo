{
    'name': 'Export International - Maker-checker approvals',
    'version': '20.0.1.0.1',
    'category': 'Accounting',
    'summary': 'One person enters and submits; a different authorised person approves, returns or rejects. Requests, assignment, '
               'top-bar counter and notifications, an approvals centre and a full audit timeline.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_app_shell', 'ei_da_feeding', 'ei_close', 'bus'],
    'data': [
        'security/ir.access.csv',
        'data/rules.xml',
        'data/cron.xml',
        'views/rule_views.xml',
        'views/request_views.xml',
        'views/document_views.xml',
        'views/menus.xml',
        'views/settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_approvals/static/src/approvals.scss',
            'ei_approvals/static/src/systray/*.js',
            'ei_approvals/static/src/systray/*.xml',
            'ei_approvals/static/src/center/*.js',
            'ei_approvals/static/src/center/*.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
