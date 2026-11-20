"""Affirmative, purpose-specific choice at password collection boundaries.

Service-only calls omit evidence and never create historical consent receipts.
The public API/SSR boundary validates before authenticating or changing a password.
"""
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone
from core.api import DomainError
from core.services import audit

PASSWORD_PURPOSE_VERSION = 'password-account-v1'
PASSWORD_PURPOSE_FIELDS = {'password_purpose_consent', 'password_purpose_version'}
PASSWORD_PURPOSES = {'registration', 'sign_in', 'password_reset', 'reauthentication', 'password_change', 'admin_sign_in'}


@dataclass(frozen=True)
class PasswordPurposeConsent:
    version: str
    collected_at: datetime


def validate_password_purpose_consent(data):
    """Reject absent, stale or truthy-but-not-boolean choices before password use."""
    if data.get('password_purpose_consent') is not True or data.get('password_purpose_version') != PASSWORD_PURPOSE_VERSION:
        raise DomainError('password_purpose_consent_required', 'Please affirm the current password processing purpose before continuing.', 422)
    return PasswordPurposeConsent(PASSWORD_PURPOSE_VERSION, timezone.now())


def record_password_purpose_consent(user, purpose, evidence):
    """Call in the successful action's transaction with its actual account actor."""
    if evidence is None:
        return None
    if not isinstance(evidence, PasswordPurposeConsent) or evidence.version != PASSWORD_PURPOSE_VERSION or purpose not in PASSWORD_PURPOSES:
        raise ValueError('Invalid password purpose consent evidence')
    return audit(user, 'password.purpose_consented', user, {
        'purpose': purpose,
        'notice_version': evidence.version,
        'affirmative': True,
        'collected_at': evidence.collected_at.isoformat().replace('+00:00', 'Z'),
    })
