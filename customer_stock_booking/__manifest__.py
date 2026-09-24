{
    'name': 'Customer Stock Booking',
    'version': '19.0.1.0.2',
    'summary': 'Standalone customer stock booking with two-level approval and expiry',
    'description': '''
Customer-specific standalone stock booking without Sales Orders or Manufacturing Orders.
Reserves only free-to-use stock, supports multi-location reservation, lot/serial booking,
manual delivered quantity validation, reminders, automatic expiry, and Sales Order warnings.
    ''',
    'author': 'Mehedi Hasan',
    'website': 'https://www.zencoreltd.com',
    'category': 'Inventory/Inventory',
    'license': 'LGPL-3',
    'depends': ['stock', 'sale_stock', 'mail'],
    'data': [
        'security/booking_security.xml',
        'security/ir.model.access.csv',
        'data/booking_sequence.xml',
        'data/booking_location.xml',
        'data/booking_cron.xml',
        'views/customer_booking_views.xml',
        'wizard/booking_delivery_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {},
    'application': True,
    'installable': True,
}
