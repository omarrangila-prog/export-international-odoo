{
    'name': 'Export International - Reports',
    'version': '20.0.1.1.0',
    'category': 'Accounting',
    'summary': 'A report catalog and the first real reports: receivables ageing, bank book against bank confirmation, unmatched bank lines, '
               'contracts and spread, material lifting. Every figure is read from posted records and reconciles to the dashboard.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_ui_theme', 'ei_management_dashboard', 'ei_party360'],
    'data': [
        'data/groups.xml',
        'security/ir.access.csv',
        'views/report_views.xml',
        'views/financial_views.xml',
        'report/financial_report.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ei_reports/static/src/catalog/catalog.scss',
            'ei_reports/static/src/catalog/catalog.js',
            'ei_reports/static/src/catalog/catalog.xml',
            'ei_reports/static/src/workspace/workspace.scss',
            'ei_reports/static/src/workspace/workspace.js',
            'ei_reports/static/src/workspace/workspace.xml',
        ],
    },
    'installable': True,
}
