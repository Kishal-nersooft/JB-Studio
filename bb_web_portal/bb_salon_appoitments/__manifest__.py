{
    'name': 'Beauty Branch Management',
    'version': '19.0.1.3.9',
    'category': 'Services',
    'sequence': 1,
    'author': 'Nerosoft Solutions',
    'website': 'https://nerosoftsolutions.com/',
    'summary': 'Manage beauty branches, franchises, and appointments',
    'description': """
        Beauty Branch Management System
        ==============================
        * Multi-company branch management
        * Franchise support
        * Beautician management
        * Appointment booking system
        * POS and Website integration per branch
    """,
    'depends': ['web_gantt', 'base', 'website', 'mail', 'point_of_sale', 'hr', 'crm', 'bnb_customer_extra_fields'],
    'data': [
        'views/res_partner_client_overview_views.xml',
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/sequences.xml',
        'data/cancellation_reason_data.xml',
        'data/payment_status_reconciliation.xml',
        'data/ir_cron_data.xml',
        'data/backfill_appointment_type.xml',
        'data/backfill_added_at_checkout.xml',
        'views/res_company_views.xml',
        'views/branch_views.xml',
        'views/appointment_views.xml',
        'views/customer_deposit_views.xml',
        'views/credit_redemption_views.xml',
        'views/menu_views.xml',
        'views/cancellation_reason_views.xml',
        'views/appointment_cancel_wizard_view.xml',
        'views/hr_employee.xml',
        'views/beautician_bulk_add_wizard_view.xml',
        'views/service_bulk_add_wizard_view.xml',
        'views/product_template.xml',
        'views/res_partner_view.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {'web.assets_backend_lazy': [
        'bb_salon_appoitments/static/src/js/branch_time_views.js',
    ]},
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
