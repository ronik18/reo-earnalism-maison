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
    """Start condition D2 (spec 6.2): live Bengali editions with complete narration, cleared everywhere.

    Every unit of the live revision has a ready audio_chapter asset, and audio is cleared in every publication
    territory (library.store_export.audio_cleared_everywhere). English narration is not a start condition.
    """
    from library.store_export import audio_cleared_everywhere
    count = 0
    for edition in Edition.objects.filter(locale='bn', live_revision__state='live').select_related('live_revision'):
        revision = edition.live_revision
        units = list(revision.units.values_list('pk', flat=True))
        voiced = set(revision.assets.filter(kind='audio_chapter', state='ready', unit__isnull=False).values_list('unit_id', flat=True))
        if units and set(units) <= voiced and audio_cleared_everywhere(revision):
            count += 1
    return count


def latest_founding_plans(lock=False) -> dict:
    """{unit: BillingPlan or None} for the LATEST offer version of each founding code."""
    plans = {}
    for unit, spec in SPECS.items():
        offer = Offer.objects.filter(code=spec['code']).order_by('-version').first()
        query = BillingPlan.objects.select_related('offer').filter(offer=offer) if offer else BillingPlan.objects.none()
        plans[unit] = (query.select_for_update() if lock else query).first()
    return plans


def ensure_founding_plans(actor):
    _require_staff(actor)
    plans, created = {}, []
    with transaction.atomic():
        latest = latest_founding_plans()
        for unit, spec in SPECS.items():
            plan = latest[unit]
            if plan is None and Offer.objects.filter(code=spec['code']).exists():
                raise DomainError('FOUNDING_PLAN_MISSING', f"The latest {spec['code']} offer has no billing plan.", 409)
            if plan is None:
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
        plans = list(latest_founding_plans(lock=True).values())
        if any(p is None or p.merchant_approved_at is None for p in plans):
            raise DomainError('FOUNDING_MERCHANT_UNAPPROVED', 'Both founding plans need merchant approval first.', 409)
        Offer.objects.filter(pk__in=[p.offer_id for p in plans]).update(approved=True, active=True)
        audit(actor, 'billing.founding_plans_activated', plans[0], {'audio_titles': audio_titles})


def founding_plans_open() -> bool:
    """True when the latest offer version of each founding code has a merchant-approved plan and is approved, active
    and not test_only: a price is shown only when it can actually be bought in production."""
    plans = latest_founding_plans().values()
    return all(p is not None and p.merchant_approved_at is not None and p.offer.approved and p.offer.active
               and not p.offer.test_only for p in plans)
