{
    'name': 'Export International - Automation rules',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Business-owned reminders: missing supplier invoices, stalled lifting, overdue customers, anomalies. Internal reminders only.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_ui_theme'],
    'data': [
        'security/ir.access.csv',
        'views/rule_views.xml',
        'data/rules.xml',
        'data/cron.xml',
    ],
    'installable': True,
}
