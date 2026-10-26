{
    'name': 'Export International - Ask (read-only assistant)',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Ask a question in plain words; answers come from your own records, with sources, and nothing can be changed',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_party360', 'ei_matching'],
    'data': [
        'security/ir.access.csv',
        'views/assistant_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_assistant/static/src/assistant/assistant.scss',
            'ei_assistant/static/src/assistant/assistant.js',
            'ei_assistant/static/src/assistant/assistant.xml',
        ],
    },
    'installable': True,
}
