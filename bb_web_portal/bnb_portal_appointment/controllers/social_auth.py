from odoo import http
from odoo.http import request
import requests
import json
import jwt
import time
import secrets
import base64
import hashlib
import hmac
import textwrap
import logging
from werkzeug.utils import redirect
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

_logger = logging.getLogger(__name__)

class SocialAuthController(http.Controller):
    @staticmethod
    def _allowed_company_ids():
        return request.env.companies.ids or [request.env.company.id]

    def _get_safe_return_url(self, return_url, fallback='/book-online'):
        if not return_url:
            return fallback
        parsed = urlparse(return_url)
        if parsed.scheme or parsed.netloc:
            if parsed.netloc != request.httprequest.host:
                return fallback
            return urlunparse(('', '', parsed.path, parsed.params, parsed.query, parsed.fragment))
        if not return_url.startswith('/'):
            return fallback
        return return_url

    def _verify_apple_id_token(self, id_token, client_id):
        jwks_client = jwt.PyJWKClient("https://appleid.apple.com/auth/keys")
        signing_key = jwks_client.get_signing_key_from_jwt(id_token).key
        return jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://appleid.apple.com",
        )

    @staticmethod
    def _parse_apple_user(user_json):
        """Return the one-time Apple name payload without trusting its shape."""
        if not user_json:
            return '', ''
        try:
            user_data = json.loads(user_json)
        except (TypeError, json.JSONDecodeError):
            return '', ''
        name_info = user_data.get('name') if isinstance(user_data, dict) else {}
        if not isinstance(name_info, dict):
            return '', ''

        def clean(value):
            return ' '.join(str(value or '').split())[:128]

        return clean(name_info.get('firstName')), clean(name_info.get('lastName'))

    @staticmethod
    def _partner_name_parts(partner):
        first_name = (partner.apple_signin_first_name or '').strip()
        last_name = (partner.apple_signin_last_name or '').strip()
        if first_name or last_name:
            return first_name, last_name
        parts = (partner.name or '').strip().split(None, 1)
        return (parts[0] if parts else '', parts[1] if len(parts) > 1 else '')

    def _apple_state_secret(self):
        secret = request.env['ir.config_parameter'].sudo().get_param('database.secret')
        if not secret:
            raise ValueError('Database secret is not configured')
        return secret.encode()

    def _make_apple_state(self, return_url):
        payload = {
            'return_url': self._get_safe_return_url(return_url),
            'nonce': secrets.token_urlsafe(24),
            'issued_at': int(time.time()),
        }
        raw = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
        encoded = base64.urlsafe_b64encode(raw).rstrip(b'=')
        signature = hmac.new(self._apple_state_secret(), encoded, hashlib.sha256).digest()
        return f"{encoded.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}", payload

    def _read_apple_state(self, state, max_age=600):
        try:
            encoded, supplied_signature = state.split('.', 1)
            expected_signature = hmac.new(
                self._apple_state_secret(), encoded.encode(), hashlib.sha256,
            ).digest()
            padded_signature = supplied_signature + '=' * (-len(supplied_signature) % 4)
            if not hmac.compare_digest(
                expected_signature, base64.urlsafe_b64decode(padded_signature.encode()),
            ):
                return None
            padded_payload = encoded + '=' * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded_payload.encode()))
            issued_at = int(payload.get('issued_at', 0))
            if not issued_at or abs(int(time.time()) - issued_at) > max_age:
                return None
            payload['return_url'] = self._get_safe_return_url(payload.get('return_url'))
            return payload
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _find_apple_partner(self, apple_sub, email, first_name, last_name):
        Partner = request.env['res.partner'].sudo()
        partner = Partner.search([('apple_signin_sub', '=', apple_sub)], limit=1)
        if partner and partner.company_id and partner.company_id.id not in self._allowed_company_ids():
            raise ValueError('This Apple account is linked outside the available company')
        if partner:
            return partner

        candidates = Partner.search([
            ('email', '=ilike', email),
            '|',
            ('company_id', '=', False),
            ('company_id', 'in', self._allowed_company_ids()),
        ])
        session_partner_id = request.session.get('social_auth_user_data', {}).get('partner_id')
        session_partner = candidates.filtered(lambda item: item.id == session_partner_id)
        if len(session_partner) == 1:
            return session_partner
        if len(candidates) == 1:
            return candidates
        if len(candidates) > 1 and (first_name or last_name):
            requested_name = f"{first_name} {last_name}".strip().casefold()
            name_matches = candidates.filtered(
                lambda item: (item.name or '').strip().casefold() == requested_name
            )
            if len(name_matches) == 1:
                return name_matches
        if len(candidates) > 1:
            raise ValueError('Multiple customer profiles use this email; please contact the salon to link your Apple account')
        return Partner

    # ============================================================================
    # GOOGLE OAUTH FLOW (FIXED)
    # ============================================================================

    @http.route('/auth/google/login', type='http', auth='public', website=True, csrf=False)
    def google_auth_login(self, **kw):
        """Initiate Google OAuth flow"""

        ICP = request.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('bnb_portal_appointment.google_client_id')
        enabled = ICP.get_param('bnb_portal_appointment.enable_google_connector')

        if not enabled or not client_id:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'Google Sign-In is not enabled or configured'
            })

        # Build redirect URI
        base_url = request.httprequest.url_root.rstrip('/')
        redirect_uri = f"{base_url}/auth/google/callback"

        # Get return URL from frontend
        return_url = self._get_safe_return_url(kw.get('return_url') or '/book-online/customer?branch_id=3')

        # Clean old social_auth params from return URL
        parsed = urlparse(return_url)
        query_params = parse_qs(parsed.query)
        query_params.pop('social_auth', None)

        clean_query = urlencode({k: v[0] if isinstance(v, list) else v for k, v in query_params.items()})
        return_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, clean_query, parsed.fragment
        ))

        # Store in session
        request.session['social_auth_return_url'] = return_url
        state = secrets.token_urlsafe(16)
        request.session['google_oauth_state'] = state

        # Build Google OAuth URL
        google_auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            "?response_type=code"
            f"&client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            "&scope=openid%20email%20profile"
            "&access_type=offline"
            "&prompt=consent"
            f"&state={state}"
        )

        return redirect(google_auth_url)

    @http.route('/auth/google/callback', type='http', auth='public', website=True, csrf=False)
    def google_auth_callback(self, **kw):
        """Handle Google OAuth callback - FIXED VERSION"""

        code = kw.get('code')
        error = kw.get('error')
        state = kw.get('state')
        expected_state = request.session.pop('google_oauth_state', None)
        if not state or state != expected_state:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'Invalid authentication state'
            })

        if error:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': f'Google authentication failed: {error}'
            })

        if not code:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'No authorization code received from Google'
            })

        try:
            ICP = request.env['ir.config_parameter'].sudo()
            client_id = ICP.get_param('bnb_portal_appointment.google_client_id')
            client_secret = ICP.get_param('bnb_portal_appointment.google_client_secret')

            base_url = request.httprequest.url_root.rstrip('/')
            redirect_uri = f"{base_url}/auth/google/callback"

            # Exchange code for token
            token_response = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri
                },
                timeout=10
            )

            if token_response.status_code != 200:
                raise Exception(token_response.text)

            token_data = token_response.json()
            access_token = token_data.get("access_token")

            # Get user info
            userinfo_response = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )

            if userinfo_response.status_code != 200:
                raise Exception(userinfo_response.text)

            userinfo = userinfo_response.json()

            # Create or find existing contact (res.partner) on first login
            email = userinfo.get('email')
            first_name = userinfo.get('given_name', '')
            last_name = userinfo.get('family_name', '')
            partner = request.env['res.partner'].sudo().search([
                ('email', '=', email),
                '|',
                ('company_id', '=', False),
                ('company_id', 'in', self._allowed_company_ids()),
            ], limit=1)
            # Save in session (including partner_id for checkout)
            request.session['social_auth_user_data'] = {
                'provider': 'google',
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
                'picture': userinfo.get('picture', ''),
                'verified_email': userinfo.get('verified_email', False),
                'partner_id': partner.id,
                'phone': partner.phone or '',
            }

            # Restore return URL
            return_url = request.session.get(
                'social_auth_return_url',
                '/book-online/customer?branch_id=3'
            )

            # Parse and clean URL properly
            parsed_url = urlparse(return_url)
            query_params = parse_qs(parsed_url.query)

            # Check if already on customer page
            is_customer_page = (
                    'customer' in parsed_url.path or
                    ('step' in query_params and 'customer' in str(query_params.get('step', [])))
            )

            # Remove old social_auth param if exists
            query_params.pop('social_auth', None)

            # Only add step=customer if NOT already on customer page
            if not is_customer_page and 'step' not in query_params:
                query_params['step'] = ['customer']

            # Add success flag
            query_params['social_auth'] = ['success']

            # Rebuild query string
            clean_params = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in query_params.items()}
            new_query = urlencode(clean_params, doseq=True)

            # Rebuild full URL
            redirect_url = urlunparse((
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                new_query,
                parsed_url.fragment
            ))

            return redirect(redirect_url)

        except Exception as e:
            _logger.exception('Google sign-in could not be completed')
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'Google sign-in could not be completed. Please try again or enter your details manually.'
            })

    # ============================================================================
    # APPLE SIGN-IN FLOW (FIXED)
    # ============================================================================

    @http.route('/auth/apple/login', type='http', auth='public', website=True, csrf=False)
    def apple_auth_login(self, **kw):
        """Initiate Apple OAuth flow"""

        ICP = request.env['ir.config_parameter'].sudo()
        client_id = ICP.get_param('bnb_portal_appointment.apple_client_id')
        enabled = ICP.get_param('bnb_portal_appointment.enable_apple_connector')

        if not enabled or not client_id:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'Apple Sign-In is not enabled or configured'
            })

        base_url = request.httprequest.url_root.rstrip('/')
        redirect_uri = f"{base_url}/auth/apple/callback"

        # Get return URL and clean it
        return_url = self._get_safe_return_url(kw.get('return_url') or '/book-online/customer?branch_id=3')

        parsed = urlparse(return_url)
        query_params = parse_qs(parsed.query)
        query_params.pop('social_auth', None)

        clean_query = urlencode({k: v[0] if isinstance(v, list) else v for k, v in query_params.items()})
        return_url = urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, clean_query, parsed.fragment
        ))

        request.session['social_auth_return_url'] = return_url
        state, state_payload = self._make_apple_state(return_url)
        request.session['apple_oauth_state'] = state

        apple_auth_url = "https://appleid.apple.com/auth/authorize?" + urlencode({
            'response_type': 'code',
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': 'name email',
            'response_mode': 'form_post',
            'state': state,
            'nonce': state_payload['nonce'],
        })

        return redirect(apple_auth_url)

    @http.route('/auth/apple/callback', type='http', auth='public', website=True, csrf=False, methods=['POST', 'GET'])
    def apple_auth_callback(self, **kw):
        """Handle Apple OAuth callback - FIXED VERSION"""

        code = kw.get('code')
        error = kw.get('error')
        state = kw.get('state')
        expected_state = request.session.pop('apple_oauth_state', None)
        state_payload = self._read_apple_state(state)
        if not state_payload or (expected_state and not hmac.compare_digest(state, expected_state)):
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'Invalid authentication state'
            })

        if error:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': f'Apple authentication failed: {error}'
            })

        if not code:
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'No authorization code received from Apple'
            })

        try:
            ICP = request.env['ir.config_parameter'].sudo()
            client_id = ICP.get_param('bnb_portal_appointment.apple_client_id')
            team_id = ICP.get_param('bnb_portal_appointment.apple_team_id')
            key_id = ICP.get_param('bnb_portal_appointment.apple_key_id')
            private_key = ICP.get_param('bnb_portal_appointment.apple_private_key')

            base_url = request.httprequest.url_root.rstrip('/')
            redirect_uri = f"{base_url}/auth/apple/callback"

            client_secret = self._generate_apple_client_secret(team_id, client_id, key_id, private_key)

            token_response = requests.post(
                "https://appleid.apple.com/auth/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri
                },
                timeout=10
            )

            if token_response.status_code != 200:
                raise Exception(token_response.text)

            token_data = token_response.json()
            id_token = token_data.get("id_token")
            if not id_token:
                raise Exception("Missing id_token from Apple")
            decoded_token = self._verify_apple_id_token(id_token, client_id)
            if not hmac.compare_digest(
                str(decoded_token.get('nonce') or ''), str(state_payload.get('nonce') or ''),
            ):
                raise ValueError('Invalid Apple authentication nonce')

            # Apple returns the name only once. Persist it with the stable `sub`
            # claim and restore it from the linked contact on later sign-ins.
            apple_sub = str(decoded_token.get('sub') or '').strip()
            email = str(decoded_token.get('email') or '').strip().lower()
            if not apple_sub or not email:
                raise ValueError('Apple did not return a usable customer identity')
            # Apple may provide name in user JSON on first auth only
            apple_first_name, apple_last_name = self._parse_apple_user(kw.get('user', ''))
            partner = self._find_apple_partner(
                apple_sub, email, apple_first_name, apple_last_name,
            )
            stored_first_name, stored_last_name = self._partner_name_parts(partner) if partner else ('', '')
            apple_first_name = apple_first_name or stored_first_name
            apple_last_name = apple_last_name or stored_last_name
            email_verified = decoded_token.get('email_verified', False)
            if isinstance(email_verified, str):
                email_verified = email_verified.lower() == 'true'

            request.session['social_auth_user_data'] = {
                'provider': 'apple',
                'apple_sub': apple_sub,
                'email': email,
                'first_name': apple_first_name,
                'last_name': apple_last_name,
                'verified_email': bool(email_verified),
                'partner_id': partner.id,
                'phone': partner.phone or '',
            }

            # Restore return URL
            return_url = state_payload['return_url']

            # Parse and clean URL properly (same as Google)
            parsed_url = urlparse(return_url)
            query_params = parse_qs(parsed_url.query)

            # Check if already on customer page
            is_customer_page = (
                    'customer' in parsed_url.path or
                    ('step' in query_params and 'customer' in str(query_params.get('step', [])))
            )

            # Remove old social_auth param if exists
            query_params.pop('social_auth', None)

            # Only add step=customer if NOT already on customer page
            if not is_customer_page and 'step' not in query_params:
                query_params['step'] = ['customer']

            # Add success flag
            query_params['social_auth'] = ['success']

            # Rebuild query string
            clean_params = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in query_params.items()}
            new_query = urlencode(clean_params, doseq=True)

            # Rebuild full URL
            redirect_url = urlunparse((
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                new_query,
                parsed_url.fragment
            ))

            return redirect(redirect_url)

        except Exception as e:
            _logger.exception('Apple sign-in could not be completed')
            return request.render('bnb_portal_appointment.social_auth_error', {
                'error': 'Apple sign-in could not be completed. Please try again or enter your details manually.'
            })

    def _generate_apple_client_secret(self, team_id, client_id, key_id, private_key):
        """Generate Apple client secret JWT"""

        private_key = self._normalize_apple_private_key(private_key)

        headers = {"kid": key_id, "alg": "ES256"}
        payload = {
            "iss": team_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + 86400 * 180,
            "aud": "https://appleid.apple.com",
            "sub": client_id
        }

        return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

    @staticmethod
    def _normalize_apple_private_key(private_key):
        """Accept either a complete Apple .p8 PEM or its base64 body."""
        value = str(private_key or '').strip().replace('\\n', '\n')
        if not value:
            raise ValueError('Apple private key is not configured')
        if value.startswith('-----BEGIN PRIVATE KEY-----'):
            if not value.endswith('-----END PRIVATE KEY-----'):
                raise ValueError('Apple private key PEM footer is missing')
            return value

        compact = ''.join(value.split())
        try:
            base64.b64decode(compact, validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError('Apple private key is not valid PEM or base64') from error
        body = '\n'.join(textwrap.wrap(compact, 64))
        return f'-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----'

    # ============================================================================
    # API ENDPOINT
    # ============================================================================

    @http.route('/auth/social/userdata', type='jsonrpc', auth='public', website=True, csrf=False)
    def get_social_user_data(self, **kw):
        """Fetch social auth user data from session"""

        user_data = request.session.get('social_auth_user_data')

        if user_data:
            # Keep partner_id in session for checkout, return user data for form
            return {'success': True, 'data': user_data}

        return {'success': False, 'message': 'No user data found'}
