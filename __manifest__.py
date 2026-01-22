# -*- coding: utf-8 -*-
{
    'name': 'Inventory API',
    'version': '18.0.1.0.0',
    'category': 'API',
    'summary': 'REST API for Inventory Management',
    'description': """
        Inventory API Addon
        ==================
        
        This addon provides REST API endpoints for inventory management.
        
        Features:
        - Get inventory table by SKU and warehouse/store
        - Transfer inventory between locations
        - Adjust inventory (set/add/subtract quantities)
        
        API Endpoints:
        - GET /api/inventory/by-sku?sku=XXX&warehouse_id=1
        - POST /api/inventory/transfer
        - POST /api/inventory/adjust
    """,
    'author': 'Your Name',
    'website': 'https://www.odoo.com',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/api_token_views.xml',
        'views/stock_quant_change_views.xml',
        'views/stock_quant_inherit.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

