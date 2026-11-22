"""Account mode per territory: 'open' asks no age question; 'adult_only' requires 18+."""
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from config.territories import validate_account_modes
from core.api import DomainError
from core.models import AuditEvent
from . import enrollment, services
from .models import User

MODES = {'IN': 'open', 'BR': 'adult_only'}
NOTICE = {'account_notice_version': 'india-account-v1', 'account_terms_consent': True}
PASSWORD = {'password_purpose_consent': True, 'password_purpose_version': 'password-account-v1'}


def register(email, territory, **declaration):
    from .password_consent import validate_password_purpose_consent
    return services.register_member(email, 'Original-Territory-Passphrase-47', display_name='Reader',
                                    password_consent=validate_password_purpose_consent(dict(PASSWORD)),
                                    territory=territory, **declaration)


@override_settings(LOCAL=True, INDIA_FIRST_LAUNCH_ENABLED=True, MAISON_ACCOUNT_MODES=MODES)
class TerritoryAccountModeTests(TestCase):
    def test_india_signup_needs_no_capacity_fields(self):
        register('open-reader@example.test', 'IN', **NOTICE)
        user = User.objects.get(email='open-reader@example.test')
        event = AuditEvent.objects.get(actor=user, action='account.capacity_declared')
        self.assertEqual(event.detail['account_capacity'], 'not_asked')

    def test_open_territory_still_requires_notice_consent(self):
        with self.assertRaises(DomainError) as error:
            register('no-consent@example.test', 'IN')
        self.assertEqual(error.exception.code, 'account_permission_required')
        self.assertFalse(User.objects.filter(email='no-consent@example.test').exists())

    def test_brazil_signup_without_declaration_is_refused(self):
        with self.assertRaises(DomainError) as error:
            register('br-minor@example.test', 'BR', **NOTICE)
        self.assertEqual((error.exception.code, error.exception.status), ('adult_declaration_required', 422))
        self.assertFalse(User.objects.filter(email='br-minor@example.test').exists())

    def test_brazil_signup_with_adult_declaration_records_audit(self):
        register('br-adult@example.test', 'BR', account_capacity='adult', **NOTICE)
        event = AuditEvent.objects.get(actor__email='br-adult@example.test', action='account.capacity_declared')
        self.assertEqual(event.detail['account_capacity'], 'adult')

    def test_unknown_territory_fails_closed_to_adult_only(self):
        self.assertEqual(enrollment.account_mode('ZZ'), 'adult_only')
        self.assertEqual(enrollment.account_mode(None), 'adult_only')

    def test_google_declaration_in_adult_only_territory_requires_adult(self):
        with self.assertRaises(DomainError):
            enrollment.adult_declaration(dict(NOTICE), 'BR')
        self.assertEqual(enrollment.adult_declaration(dict(NOTICE), 'IN')['account_capacity'], 'not_asked')

    def test_signup_page_shows_adult_checkbox_only_in_adult_only_territory(self):
        with self.settings(MAISON_ACCOUNT_MODES={'IN': 'open'}):
            open_page = self.client.get('/en/sign-up/').content.decode()
        with self.settings(MAISON_ACCOUNT_MODES={'IN': 'adult_only'}):
            adult_page = self.client.get('/en/sign-up/').content.decode()
        self.assertNotIn('I am 18 or older', open_page)
        self.assertIn('name="account_terms_consent"', open_page)
        self.assertIn('I am 18 or older', adult_page)
        self.assertNotIn('Help a younger reader', open_page + adult_page)


class AccountModeConfigTests(TestCase):
    def test_active_territory_without_mode_fails_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_account_modes({'IN': 'open'}, ('IN', 'BR'))

    def test_unknown_mode_fails_startup(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_account_modes({'IN': 'guardian'}, ('IN',))

    def test_valid_modes_pass(self):
        self.assertEqual(validate_account_modes({'IN': 'open', 'BR': 'adult_only'}, ('IN', 'BR')), {'IN': 'open', 'BR': 'adult_only'})
