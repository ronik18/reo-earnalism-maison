"""First-party signup attribution and the aggregate acquisition funnel.

Campaign links point at a product page with allow-listed ``utm_source``, ``utm_campaign``
and ``utm_content`` values. The existing ``return_to`` chain carries that page's URL
through sign-in/sign-up and into ``register_member``, so attribution needs no cookie,
fingerprint or tracker. Unknown sources collapse to ``other``; free-text values are
dropped, never stored. Reports are aggregate counts with small cells suppressed.
"""
import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import TruncWeek

from .models import ATTRIBUTION_SOURCES, SignupAttribution, User

SLUG = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
LANDING = re.compile(r'^/(en|bn)/[A-Za-z0-9/_.-]{0,196}$')
STAGES = ('signed_up', 'verified', 'started_reading', 'completed_story', 'pass_started')


def _slug(values):
    value = (values or [''])[0].strip().lower()
    return value if SLUG.fullmatch(value) else ''


def parse(return_path):
    """Return the allow-listed attribution carried by a local return path, or None."""
    if not isinstance(return_path, str) or len(return_path) > 2048:
        return None
    parts = urlsplit(return_path)
    if parts.scheme or parts.netloc:
        return None
    query = parse_qs(parts.query, max_num_fields=20)
    raw_source = (query.get('utm_source') or [''])[0].strip().lower()
    if not raw_source:
        return None
    source = raw_source if raw_source in ATTRIBUTION_SOURCES else 'other'
    landing = parts.path if LANDING.fullmatch(parts.path) else ''
    return {'source': source, 'campaign': _slug(query.get('utm_campaign')),
            'content': _slug(query.get('utm_content')), 'landing_path': landing}


def record(user, return_path):
    """Store first-touch attribution once for a newly registered member; no-op otherwise."""
    values = parse(return_path)
    if values:
        SignupAttribution.objects.get_or_create(user=user, defaults=values)
    return values


def funnel(since, until, *, by_campaign=False, min_cell=5):
    """Weekly cohort funnel of self-registered members, grouped by source (and campaign).

    Counts below ``min_cell`` are reported as None ("fewer than min_cell") so the report
    cannot single out a member. Deleted (anonymised) and guardian-managed accounts are excluded.
    """
    from billing.subscription_models import Subscription
    from reader.models import Completion, Progress

    members = (User.objects.filter(date_joined__gte=since, date_joined__lt=until, is_active=True,
                                   guardian_managed=False, is_staff=False)
               .annotate(week=TruncWeek('date_joined'),
                         started=Exists(Progress.objects.filter(user=OuterRef('pk'))),
                         finished=Exists(Completion.objects.filter(user=OuterRef('pk'), is_complete=True)),
                         subscribed=Exists(Subscription.objects.filter(user=OuterRef('pk'), current_period_start__isnull=False)))
               .values('week', 'is_verified', 'started', 'finished', 'subscribed',
                       'signup_attribution__source', 'signup_attribution__campaign'))
    rows = {}
    for m in members.iterator(chunk_size=500):
        source = m['signup_attribution__source'] or 'direct'
        key = (m['week'].date().isoformat(), source, (m['signup_attribution__campaign'] or '') if by_campaign else None)
        counts = rows.setdefault(key, dict.fromkeys(STAGES, 0))
        counts['signed_up'] += 1
        counts['verified'] += m['is_verified']
        counts['started_reading'] += m['started']
        counts['completed_story'] += m['finished']
        counts['pass_started'] += m['subscribed']
    report = []
    for (week, source, campaign), counts in sorted(rows.items()):
        row = {'week': week, 'source': source}
        if by_campaign:
            row['campaign'] = campaign
        row.update({stage: (n if n >= min_cell else None) for stage, n in counts.items()})
        report.append(row)
    return report


def default_window(now, weeks):
    start = (now - timedelta(weeks=weeks)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now
