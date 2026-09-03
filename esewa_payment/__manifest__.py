{
    'name': 'eSewa Payment',

    'summary': "Accept payments with the eSewa payment gateway (ePay v2 API)",

    # The full description lives in README.md, which Odoo 19 loads
    # automatically when the manifest `description` is empty (see
    # odoo/modules/module.py).
    'description': """
        <div class="container">
            <h1>eSewa Payment Gateway</h1>
            <p>This module integrates the <strong>eSewa</strong> payment gateway with Odoo, allowing you to accept payments via eSewa's ePay v2 API.</p>
            <p><strong>I have only tested it with test credentials</strong> so I don't if it has bugs in live env.I have left context.md so It'll be easy for your agentic AI to pickup context</p>
            <h2>Features</h2>
            <ul>
                <li>Seamless eSewa payment integration</li>
                <li>Secure payment processing</li>
                <li>Automatic transaction status updates</li>
                <li>Support for multiple currencies</li>
                <li>Test and live environment support</li>
            </ul>
            
            <h2>Installation</h2>
            <p>Install this module like any other Odoo module. After installation, configure your eSewa merchant credentials in the payment settings.</p>
            
            <h2>Configuration</h2>
            <p>Go to <strong>Accounting > Configuration > Payment Providers</strong> and select eSewa. Enter your:</p>
            <ul>
                <li>Merchant ID</li>
                <li>Secret Key</li>
                <li>Environment (Test/Live)</li>
            </ul>
            
            <h2>Support</h2>
            <p>For any issues, please contact me at saksham.khanal01@gmail.com or visit our <a href="https://github.com/Sakshamkhanal/esewa_payment.git">GitHub repository</a>.</p>
        </div>
    """,

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
