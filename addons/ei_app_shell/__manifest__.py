{
    'name': 'Export International - App shell',
    'version': '20.0.1.1.0',
    'category': 'Hidden',
    'summary': 'Installable on a phone or desktop (own name, icons, colours), a phone bottom bar, workspace tabs like a browser, '
               'undo / redo of edits, the evidence shown before an approval, and documents beside the record.',
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
            'ei_app_shell/static/src/review/review.scss',
            'ei_app_shell/static/src/review/approval.js',
            'ei_app_shell/static/src/review/documents.js',
            'ei_app_shell/static/src/review/review.xml',
        ],
    },
    'installable': True,
}
