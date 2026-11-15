# -*- coding: utf-8 -*-
{
    'name': 'Commercial',
    'version': '18.0.2.0.0',
    'category': 'Sales',
    'summary': 'Export LC, Back-to-Back LC, PI, UD, Commercial Invoice, Bank Submission and Realization for garments exporters',
    'description': """
Garments Commercial Module
==========================
Buyer PO -> Export LC -> PI -> BBLC -> UD -> Commercial Invoice / Packing List
-> Bank Submission -> Realization.
""",
    'author': 'Temakaw Fashion Ltd',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'sale', 'purchase', 'stock', 'purchase_stock'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/cron_data.xml',
        'report/report_templates.xml',
        'report/automation_reports.xml',
        'views/export_lc_views.xml',
        'views/pi_views.xml',
        'views/btb_lc_views.xml',
        'views/ud_views.xml',
        'views/invoice_views.xml',
        'views/submission_views.xml',
        'views/realization_views.xml',
        'views/inherit_views.xml',
        'views/demo_loader_views.xml',
        'views/automation_views.xml',
        'views/menu.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'application': True,
    'installable': True,
}
