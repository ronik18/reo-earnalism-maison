"""Founding-member Pass plans: created inactive, activated only once the start condition and merchant approval hold."""
from django.db import transaction

from core.api import DomainError
from core.services import audit
from library.models import Edition
from .models import Offer
from .subscription_models import BillingPlan

MIN_AUDIO_TITLES = 8
SPECS = {
    'month': dict(code='founding-pass-month', name='Earnalism Pass — founding member (monthly)', price_minor=9900, duration_seconds=2592000),
    'year': dict(code='founding-pass-year', name='Earnalism Pass — founding member (yearly)', price_minor=99900, duration_seconds=31536000),
}


def _require_staff(actor):
    if not (actor and actor.is_active and actor.is_staff and actor.is_verified):
        raise DomainError('forbidden', 'An active, verified staff account is required.', 403)


def count_audio_titles() -> int:
    return sum(1 for e in Edition.objects.filter(live_revision__isnull=False).select_related('live_revision')
               if e.live_revision.access_policy.get('audio') in ('free', 'paid'))


def ensure_founding_plans(actor):
    _require_staff(actor)
    plans, created = {}, []
    with transaction.atomic():
        for unit, spec in SPECS.items():
            plan = BillingPlan.objects.select_related('offer').filter(offer__code=spec['code']).first()
            if not plan:
                offer = Offer.objects.create(kind='one_time_pass', formats=['audio', 'reader'], currency='INR', terms_version='founding-pass-v1',
                                             approved=False, active=False, **spec)
                plan = BillingPlan.objects.create(offer=offer, interval_unit=unit)
                created.append(spec['code'])
            plans[unit] = plan
        if created:
            audit(actor, 'billing.founding_plans_created', plans['month'], {'codes': created})
    return plans


def activate_founding_plans(actor, *, audio_titles: int) -> None:
    _require_staff(actor)
    if audio_titles < MIN_AUDIO_TITLES:
        raise DomainError('FOUNDING_START_CONDITION', f'At least {MIN_AUDIO_TITLES} audio titles must be published first.', 409)
    with transaction.atomic():
        plans = list(BillingPlan.objects.select_for_update().select_related('offer').filter(offer__code__in=[s['code'] for s in SPECS.values()]))
        if len(plans) != len(SPECS) or any(p.merchant_approved_at is None for p in plans):
            raise DomainError('FOUNDING_MERCHANT_UNAPPROVED', 'Both founding plans need merchant approval first.', 409)
        Offer.objects.filter(pk__in=[p.offer_id for p in plans]).update(approved=True, active=True)
        audit(actor, 'billing.founding_plans_activated', plans[0], {'audio_titles': audio_titles})
