from odoo import fields, models, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'


    google_client_id = fields.Char(
        string="Google OAuth Client ID",
        config_parameter="bnb_portal_appointment.google_client_id",
        help="Enter your Google OAuth 2.0 Client ID from Google Cloud Console. "
             "Get it from: https://console.cloud.google.com/apis/credentials"
    )

    google_client_secret = fields.Char(
        string='Google Client Secret',
        config_parameter='bnb_portal_appointment.google_client_secret',
        help='Enter your Google OAuth 2.0 Client Secret from Google Cloud Console'
    )

    enable_google_connector = fields.Boolean(
        string="Enable Google Sign-In",
        config_parameter='bnb_portal_appointment.enable_google_connector',
        default=False,
        help='Enable or disable Google OAuth authentication for booking portal'
    )

    google_redirect_uri = fields.Char(
        string="Google Redirect URI",
        compute="_compute_google_redirect_uri",
        help="Use this URI in your Google Cloud Console OAuth configuration"
    )


    apple_client_id = fields.Char(
        string="Apple Sign-In Service ID",
        config_parameter="bnb_portal_appointment.apple_client_id",
        help="Enter your Apple Service ID (e.g., com.yourcompany.signin). "
             "Get it from: https://developer.apple.com/account/resources/identifiers/list/serviceId"
    )

    apple_team_id = fields.Char(
        string="Apple Team ID",
        config_parameter="bnb_portal_appointment.apple_team_id",
        help="Enter your Apple Developer Team ID (10 characters). "
             "Find it in your Apple Developer account: Membership section"
    )

    apple_key_id = fields.Char(
        string="Apple Key ID",
        config_parameter="bnb_portal_appointment.apple_key_id",
        help="Enter your Apple Sign-In Key ID (10 characters). "
             "Create a key in: https://developer.apple.com/account/resources/authkeys/list"
    )


    enable_apple_connector = fields.Boolean(
        string="Enable Apple Sign-In",
        config_parameter='bnb_portal_appointment.enable_apple_connector',
        default=False,
        help='Enable or disable Apple Sign-In authentication for booking portal'
    )

    # res.config.settings only supports scalar config_parameter field types.
    # Char still stores the complete PEM value, including embedded newlines.
    apple_private_key = fields.Char(
        string="Apple Private Key (.p8)",
        config_parameter="bnb_portal_appointment.apple_private_key",
        help="Paste the complete contents of your .p8 private key file here. "
    )

    apple_redirect_uri = fields.Char(
        string="Apple Redirect URI",
        compute="_compute_apple_redirect_uri",
        help="Use this URI in your Apple Sign-In configuration"
    )


    @api.depends('google_client_id')
    def _compute_google_redirect_uri(self):
        """Compute Google redirect URI"""
        for record in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record.google_redirect_uri = f"{base_url}/auth/google/callback"

    @api.depends('apple_client_id')
    def _compute_apple_redirect_uri(self):
        """Compute Apple redirect URI"""
        for record in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record.apple_redirect_uri = f"{base_url}/auth/apple/callback"
