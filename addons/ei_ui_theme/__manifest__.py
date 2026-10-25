{
    'name': 'Export International - Easy Interface',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Guided Home page, plain-language menus, cards, help text and a clean visual theme',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_management_dashboard', 'web_tour'],
    'data': [
        'views/home_views.xml',
        'views/menus.xml',
        'views/cards.xml',
        'views/guidance.xml',
        'views/help.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            'ei_ui_theme/static/src/scss/primary_variables.scss',
        ],
        'web.assets_backend': [
            'ei_ui_theme/static/src/scss/theme.scss',
            'ei_ui_theme/static/src/home/home.scss',
            'ei_ui_theme/static/src/home/home.js',
            'ei_ui_theme/static/src/home/home.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
