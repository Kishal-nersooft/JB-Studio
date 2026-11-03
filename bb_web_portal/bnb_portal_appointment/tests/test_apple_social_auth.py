from pathlib import Path

from psycopg2.errors import UniqueViolation
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from odoo.addons.bnb_portal_appointment.controllers.social_auth import SocialAuthController
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAppleSocialAuth(TransactionCase):

    def test_apple_private_key_is_supported_by_settings(self):
        field = self.env['res.config.settings']._fields['apple_private_key']
        self.assertEqual(field.type, 'char')
        self.assertEqual(
            field.config_parameter,
            'bnb_portal_appointment.apple_private_key',
        )

    def test_apple_user_payload_is_cleaned_and_bounded(self):
        first_name, last_name = SocialAuthController._parse_apple_user(
            '{"name":{"firstName":"  Jane   Mary  ","lastName":" Doe "}}'
        )
        self.assertEqual(first_name, 'Jane Mary')
        self.assertEqual(last_name, 'Doe')
        self.assertEqual(SocialAuthController._parse_apple_user('not-json'), ('', ''))

    def test_saved_apple_names_are_restored_on_later_login(self):
        partner = self.env['res.partner'].create({
            'name': 'Fallback Contact Name',
            'apple_signin_sub': 'apple-contract-user-1',
            'apple_signin_first_name': 'Apple',
            'apple_signin_last_name': 'Customer',
        })
        self.assertEqual(
            SocialAuthController._partner_name_parts(partner),
            ('Apple', 'Customer'),
        )

    def test_partner_name_is_legacy_fallback(self):
        partner = self.env['res.partner'].create({'name': 'Legacy Customer'})
        self.assertEqual(
            SocialAuthController._partner_name_parts(partner),
            ('Legacy', 'Customer'),
        )

    def test_raw_p8_body_generates_client_secret(self):
        private_key = ec.generate_private_key(ec.SECP256R1())
        pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        raw_body = ''.join(
            line for line in pem.splitlines() if not line.startswith('-----')
        )
        token = SocialAuthController()._generate_apple_client_secret(
            'TEAMID1234', 'com.example.signin', 'KEYID12345', raw_body,
        )
        self.assertTrue(token)

    def test_apple_subject_cannot_link_to_two_customers(self):
        self.env['res.partner'].create({
            'name': 'Apple Customer One',
            'apple_signin_sub': 'apple-contract-unique-user',
        })
        with self.assertRaises(UniqueViolation), self.env.cr.savepoint():
            self.env['res.partner'].create({
                'name': 'Apple Customer Two',
                'apple_signin_sub': 'apple-contract-unique-user',
            })

    def test_frontend_restores_social_session_and_assets_compile(self):
        module_root = Path(__file__).resolve().parents[1]
        controller_source = (module_root / 'controllers/social_auth.py').read_text()
        frontend_source = (module_root / 'static/src/js/social_login_auth.js').read_text()

        self.assertIn("decoded_token.get('sub')", controller_source)
        self.assertIn("decoded_token.get('nonce')", controller_source)
        self.assertIn("('apple_signin_sub', '=', apple_sub)", controller_source)
        self.assertIn('await this.restoreSocialUserData();', frontend_source)
        self.assertIn("sessionStorage.setItem('bnb_social_auth_user_data'", frontend_source)

        bundle = self.env['ir.qweb']._get_asset_bundle(
            'web.assets_frontend', css=False, js=True,
        )
        self.assertTrue(bundle.js())
