{
    'name': 'Export International - App shell',
    'version': '20.0.1.0.0',
    'category': 'Hidden',
    'summary': 'Installable on a phone or desktop (own name, icons, colours), a phone bottom bar, workspace tabs like a browser, '
               'and undo / redo of edits.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_ui_theme'],
    'data': [
        'data/params.xml',
        'views/head_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_app_shell/static/src/shell/shell.scss',
            'ei_app_shell/static/src/shell/bottom_nav.js',
            'ei_app_shell/static/src/shell/bottom_nav.xml',
            'ei_app_shell/static/src/tabs/tabs.scss',
            'ei_app_shell/static/src/tabs/tabs_service.js',
            'ei_app_shell/static/src/tabs/tab_strip.js',
            'ei_app_shell/static/src/tabs/tab_strip.xml',
            'ei_app_shell/static/src/undo/undo.scss',
            'ei_app_shell/static/src/undo/undo.js',
            'ei_app_shell/static/src/undo/undo.xml',
        ],
    },
    'installable': True,
}
