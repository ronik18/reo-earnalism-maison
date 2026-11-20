"""Public password choices fail closed and receipts describe only actual actions."""
from unittest.mock import patch
from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from core.models import AuditEvent
from . import services
from .models import User, EmailActionToken
from .password_consent import PASSWORD_PURPOSE_VERSION

PASS = 'Explicit-Password-Choice-47'
CHOICE = {'password_purpose_consent': True, 'password_purpose_version': PASSWORD_PURPOSE_VERSION}
ACTION = 'password.purpose_consented'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordPurposeAcceptanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('choice@example.test', PASS, is_verified=True)
        self.client = Client(enforce_csrf_checks=True)
        self.csrf = self.client.get('/api/v1/session').json()['csrf_token']

    def post(self, path, data):
        result = self.client.post(path, data, content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf)
        if result.status_code == 200 and path == '/api/v1/auth/login':
            self.csrf = result.json()['csrf_token']
        return result

    def login(self):
        response = self.post('/api/v1/auth/login', {'email': self.user.email, 'password': PASS, **CHOICE})
        self.assertEqual(response.status_code, 200, response.content)

    def assert_receipt(self, user, purpose, before):
        receipt = AuditEvent.objects.filter(action=ACTION, actor=user).latest('created_at')
        self.assertEqual(receipt.entity_kind, 'User')
        self.assertEqual(receipt.entity_id, str(user.pk))
        self.assertEqual(set(receipt.detail), {'purpose', 'notice_version', 'affirmative', 'collected_at'})
        self.assertEqual(receipt.detail['purpose'], purpose)
        self.assertEqual(receipt.detail['notice_version'], PASSWORD_PURPOSE_VERSION)
        self.assertIs(receipt.detail['affirmative'], True)
        self.assertTrue(receipt.detail['collected_at'].endswith('Z'))
        self.assertGreaterEqual(receipt.created_at, before)
        self.assertLessEqual(receipt.created_at, timezone.now())
        self.assertNotIn(PASS, str(receipt.detail))
        self.assertNotIn(user.password, str(receipt.detail))

    # Rate-limit behavior has separate acceptance tests; this matrix deliberately
    # exercises every invalid choice beyond the anonymous registration limit.
    @override_settings(MIDDLEWARE=[m for m in settings.MIDDLEWARE if m != "core.rate_limits.MemberRateLimitMiddleware"])
    def test_every_public_password_surface_rejects_missing_false_truthy_or_stale_before_handling_password(self):
        self.client = Client(enforce_csrf_checks=True)
        self.csrf = self.client.get('/api/v1/session').json()['csrf_token']
        self.login()
        before = AuditEvent.objects.filter(action=ACTION).count()
        surfaces = [
            ('/api/v1/auth/register', {'email': 'new-choice@example.test', 'password': PASS, 'display_name': ''}, 'accounts.views.services.register_member'),
            ('/api/v1/auth/login', {'email': self.user.email, 'password': PASS}, 'accounts.views.services.login_member'),
            ('/api/v1/auth/password-resets/confirm', {'token': 'not-processed', 'new_password': PASS}, 'accounts.views.services.confirm_password_reset'),
            ('/api/v1/me/reauthenticate', {'password': PASS}, 'accounts.models.User.check_password'),
            ('/api/v1/me/password', {'current_password': PASS, 'new_password': PASS}, 'accounts.models.User.check_password'),
        ]
        invalid = [{}, {**CHOICE, 'password_purpose_consent': False}, {**CHOICE, 'password_purpose_consent': 1},
                   {**CHOICE, 'password_purpose_consent': 'true'}, {**CHOICE, 'password_purpose_version': 'old-version'},
                   {'password_purpose_consent': True}]
        for path, body, target in surfaces:
            for choice in invalid:
                with self.subTest(path=path, choice=choice), patch(target) as handling:
                    result = self.post(path, {**body, **choice})
                    self.assertEqual(result.status_code, 422, result.content)
                    self.assertEqual(result.json()['code'], 'password_purpose_consent_required')
                    handling.assert_not_called()
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), before)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASS))
        self.assertFalse(User.objects.filter(email='new-choice@example.test').exists())

    def test_registration_receipt_is_only_for_new_successful_account_not_duplicate(self):
        body = {'email': 'new-choice@example.test', 'password': PASS, 'display_name': '', **CHOICE}
        before = timezone.now()
        result = self.post('/api/v1/auth/register', body)
        self.assertEqual(result.status_code, 202, result.content)
        user = User.objects.get(email=body['email'])
        self.assert_receipt(user, 'registration', before)
        self.assertEqual(self.post('/api/v1/auth/register', body).status_code, 202)
        self.assertEqual(AuditEvent.objects.filter(action=ACTION, actor=user).count(), 1)

    def test_failed_login_and_invalid_registration_do_not_assert_consent_receipt(self):
        result = self.post('/api/v1/auth/login', {'email': self.user.email, 'password': 'Wrong-Password-47', **CHOICE})
        self.assertEqual(result.status_code, 403)
        result = self.post('/api/v1/auth/register', {'email': 'weak@example.test', 'password': 'weak', 'display_name': '', **CHOICE})
        self.assertEqual(result.status_code, 422)
        self.assertFalse(AuditEvent.objects.filter(action=ACTION).exists())

    def test_successful_login_receipt_is_current_and_password_free(self):
        before = timezone.now()
        self.login()
        self.assert_receipt(self.user, 'sign_in', before)

    def test_reset_receipt_tracks_token_owner_not_request_actor_and_replay_adds_nothing(self):
        services.request_password_reset(self.user.email)
        action = EmailActionToken.objects.get(user=self.user, purpose='password_reset', consumed_at=None)
        body = {'token': services._token_value(action), 'new_password': 'New-Explicit-Password-53', **CHOICE}
        before = timezone.now()
        self.assertEqual(self.post('/api/v1/auth/password-resets/confirm', body).status_code, 204)
        self.assert_receipt(self.user, 'password_reset', before)
        self.assertEqual(self.post('/api/v1/auth/password-resets/confirm', body).status_code, 410)
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), 1)

    def test_reauthentication_and_password_change_record_only_valid_successful_actions(self):
        self.login()
        before = timezone.now()
        self.assertEqual(self.post('/api/v1/me/reauthenticate', {'password': PASS, **CHOICE}).status_code, 200)
        self.assert_receipt(self.user, 'reauthentication', before)
        count = AuditEvent.objects.filter(action=ACTION).count()
        self.assertEqual(self.post('/api/v1/me/password', {'current_password': 'Wrong-Password-47', 'new_password': 'New-Explicit-Password-53', **CHOICE}).status_code, 403)
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), count)
        before = timezone.now()
        result = self.post('/api/v1/me/password', {'current_password': PASS, 'new_password': 'New-Explicit-Password-53', **CHOICE})
        self.assertEqual(result.status_code, 204, result.content)
        self.assert_receipt(self.user, 'password_change', before)

    def test_internal_service_calls_without_collected_choice_do_not_backfill_receipts(self):
        services.register_member('internal-choice@example.test', PASS)
        services.request_password_reset(self.user.email)
        action = EmailActionToken.objects.get(user=self.user, purpose='password_reset', consumed_at=None)
        services.confirm_password_reset(services._token_value(action), 'Internal-Explicit-Password-53')
        self.assertFalse(AuditEvent.objects.filter(action=ACTION).exists())

    def test_admin_password_choice_precedes_authentication_and_receipt_requires_actual_login(self):
        staff = User.objects.create_superuser('choice-staff@example.test', PASS)
        client = Client(enforce_csrf_checks=True)
        client.get('/admin/login/')
        from django.conf import settings
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        body = {'username': staff.email, 'password': PASS, 'next': '/admin/'}
        with patch('django.contrib.auth.forms.authenticate') as handling:
            missing = client.post('/admin/login/', body, HTTP_X_CSRFTOKEN=token)
            self.assertEqual(missing.status_code, 200)
            handling.assert_not_called()
        self.assertFalse(AuditEvent.objects.filter(action=ACTION).exists())
        before = timezone.now()
        result = client.post('/admin/login/', {**body, **CHOICE}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(result.status_code, 302, result.content)
        self.assert_receipt(staff, 'admin_sign_in', before)

    def test_admin_password_change_requires_choice_before_verifying_password(self):
        from .admin_forms import PasswordPurposeAdminPasswordChangeForm
        body = {'old_password': PASS, 'new_password1': 'Changed-Staff-Password-53', 'new_password2': 'Changed-Staff-Password-53'}
        with patch.object(self.user, 'check_password') as handling:
            form = PasswordPurposeAdminPasswordChangeForm(self.user, body)
            self.assertFalse(form.is_valid())
            handling.assert_not_called()
        before = timezone.now()
        form = PasswordPurposeAdminPasswordChangeForm(self.user, {**body, **CHOICE})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assert_receipt(self.user, 'password_change', before)

    def test_admin_password_change_route_uses_the_gated_form(self):
        staff = User.objects.create_superuser('choice-change-staff@example.test', PASS)
        client = Client(enforce_csrf_checks=True)
        client.get('/admin/login/')
        csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(client.post('/admin/login/', {'username': staff.email, 'password': PASS, 'next': '/admin/', **CHOICE}, HTTP_X_CSRFTOKEN=csrf).status_code, 302)
        before = AuditEvent.objects.filter(action=ACTION).count()
        csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
        body = {'old_password': PASS, 'new_password1': 'Changed-Staff-Password-53', 'new_password2': 'Changed-Staff-Password-53'}
        result = client.post('/admin/password_change/', body, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code, 200)
        staff.refresh_from_db()
        self.assertTrue(staff.check_password(PASS))
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), before)
        result = client.post('/admin/password_change/', {**body, **CHOICE}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(result.status_code, 302, result.content)
        staff.refresh_from_db()
        self.assertTrue(staff.check_password('Changed-Staff-Password-53'))
        self.assertEqual(AuditEvent.objects.filter(action=ACTION).count(), before + 1)
