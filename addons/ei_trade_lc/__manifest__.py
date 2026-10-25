{
    'name': 'Export International - Import / LC Register',
    'version': '20.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Register of the 58 legacy LC / import references (group 16.xx). Settlement postings are gated.',
    'author': 'Odoovations',
    'license': 'LGPL-3',
    'depends': ['ei_legacy_master', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.access.csv',
        'views/lc_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
}
