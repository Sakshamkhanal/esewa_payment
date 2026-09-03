{
    'name': 'eSewa Payment',

    'summary': "Accept payments with the eSewa payment gateway (ePay v2 API)",

    # The full description lives in README.md, which Odoo 19 loads
    # automatically when the manifest `description` is empty (see
    # odoo/modules/module.py).
    'description':"",

    'author': "Saksham Khanal",
    'website': "https://sakshamkhanal.com.np",

    'category': 'Accounting/Accounting',
    'version': '19.0.1.0.0',

    # App Store Images - All screenshots and icon

    'images': [
        # COVER IMAGE (First screenshot becomes the main thumbnail)
        'static/description/banner_screenshot.png',
        # ADDITIONAL SCREENSHOTS (Displayed in gallery)
        'static/description/banner1_screenshot.png',
        'static/description/banner2_screenshot.png',
        'static/description/banner3_screenshot.png',
        'static/description/banner4_screenshot.png',
        'static/description/banner5_screenshot.png',
        # APP ICON (Square icon for search results)
        'static/description/icon.png',
    ],

    # any module necessary for this one to work correctly
    'depends': ['base', 'payment'],

    # always loaded
    'data': [
        'views/payment_esewa_templates.xml',
        'views/payment_provider_views.xml',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',  # Depends on `payment_method_esewa`.
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'license': 'LGPL-3',
}
