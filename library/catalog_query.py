"""Rights-aware bounded catalog queries, before keyset pagination.

No content, evidence, private object key or paid Reader body is selected for a
card. Entitlements are checked separately when opening member content.
"""
import math
import re
from datetime import timedelta

from django.conf import settings
from django.db.models import BooleanField, Exists, F, OuterRef, Prefetch, Q, Subquery, Sum, Value, BigIntegerField
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.api import DomainError
from core.pagination import paginate_queryset
from .models import Asset, Edition, Rights, Unit
from .search import normalize_search_text, search_editions

FORMATS = {'reader': 'reader_package', 'audio': 'audio_chapter', 'video': 'video'}


def _fixture_rights_enabled():
    return bool(getattr(settings, 'LOCAL', False) and getattr(settings, 'MAISON_LOCAL_FIXTURES', False))


def _rights_query(territory, at):
    # Same fail-closed shape checks as services.current_right, including malformed
    # rows inserted outside model validation. CASE protects non-array JSON.
    valid_json = RawSQL("""
        jsonb_typeof(territories) = 'array'
        AND jsonb_array_length(CASE WHEN jsonb_typeof(territories)='array' THEN territories ELSE '[]'::jsonb END) > 0
        AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(territories)='array' THEN territories ELSE '[]'::jsonb END) AS region(value)
          WHERE jsonb_typeof(value) <> 'string' OR (value #>> '{}') !~ '^(\\*|[A-Z]{2})$'
        )
    """, [], output_field=BooleanField())
    rights = Rights.objects.filter(approved=True, action='read', starts_at__lte=at, ends_at__gt=at).filter(
        Q(territories__contains=[territory]) | Q(territories__contains=['*']),
    ).alias(_valid_territories=valid_json).filter(_valid_territories=True)
    if not _fixture_rights_enabled():
        rights = rights.filter(test_only=False)
    return rights


def _numeric_filters(filters):
    values = dict(filters)
    for key, lower, upper in [('recency_days', 1, 3650), ('duration_min', 0, 1440), ('duration_max', 0, 1440)]:
        raw = values.get(key)
        if raw in (None, ''):
            continue
        if (type(raw) is not int and (not isinstance(raw, str) or not re.fullmatch(r'[0-9]{1,5}', raw))):
            raise DomainError('invalid_filter', f'{key} must be between {lower} and {upper}.', 422)
        value = int(raw)
        if not lower <= value <= upper:
            raise DomainError('invalid_filter', f'{key} must be between {lower} and {upper}.', 422)
        values[key] = value
    if values.get('duration_min') not in (None, '') and values.get('duration_max') not in (None, '') and values['duration_min'] > values['duration_max']:
        raise DomainError('invalid_filter', 'Minimum duration cannot exceed maximum duration.', 422)
    return values


def catalog_queryset(locale=None, territory='IN', query='', house='', format='', **filters):
    from .services import content_locale
    locale=content_locale(locale)
    query = normalize_search_text(query)
    if len(query) > 120:
        raise DomainError('invalid_query', 'Search query is limited to 120 characters.', 422)
    filters = _numeric_filters(filters)
    if format not in {'', *FORMATS} or (house and house not in {'classics','golpo','learn','interview','series','collections'}):
        raise DomainError('invalid_filter', 'Invalid locale, format or House.', 422)
    access = filters.get('access')
    if access not in (None, '', 'all', 'free', 'paid', 'pass_required'):
        raise DomainError('invalid_filter', 'Invalid access filter.', 422)
    territory = territory.upper()
    at = timezone.now()
    rights = _rights_query(territory, at)
    editions = Edition.objects.filter(live_revision__state='live').select_related('work', 'live_revision').annotate(catalog_title=F('work__title'))
    if locale is not None:editions=editions.filter(locale=locale)
    if territory not in settings.MAISON_PUBLICATION_TERRITORIES:
        return editions.none()
    if query:
        editions = search_editions(editions, query, locale)
    else:
        editions = editions.order_by('catalog_title', 'id')
    if house:
        editions = editions.filter(work__house=house)
    for key in ('topic', 'level'):
        if filters.get(key):
            editions = editions.filter(**{'work__'+key: filters[key]})
    if filters.get('author'):
        editions = editions.filter(work__creators__icontains=filters['author'])
    if filters.get('recency_days'):
        editions = editions.filter(live_revision__published_at__gte=at-timedelta(days=filters['recency_days']))
    offered = Q(pk__in=[])
    free = Q(pk__in=[])
    for fmt, kind in FORMATS.items():
        right = rights.filter(revision_id=OuterRef('live_revision_id'), format=fmt)
        asset = Asset.objects.filter(revision_id=OuterRef('live_revision_id'), state='ready', kind=kind,
                                     provider='stream' if fmt == 'video' else 'r2')
        editions = editions.annotate(**{'catalog_right_'+fmt: Exists(right), 'catalog_asset_'+fmt: Exists(asset)})
        fmt_offered = Q(**{'catalog_right_'+fmt: True, 'catalog_asset_'+fmt: True,
                          'live_revision__access_policy__'+fmt+'__in': ['free', 'paid']})
        offered |= fmt_offered
        free |= fmt_offered & Q(**{'live_revision__access_policy__'+fmt: 'free'})
        if fmt == format:
            editions = editions.filter(fmt_offered)
    if getattr(settings,'FREE_ACCESS_ENABLED',False):free=offered
    editions = editions.filter(offered).annotate(catalog_free=free)
    if access == 'free':
        editions = editions.filter(catalog_free=True)
    elif access in {'paid', 'pass_required'}:
        editions = editions.filter(catalog_free=False)
    if filters.get('duration_min') not in (None, '') or filters.get('duration_max') not in (None, ''):
        duration = Unit.objects.filter(revision_id=OuterRef('live_revision_id')).order_by().values('revision_id').annotate(total=Sum('duration_ms')).values('total')
        editions = editions.annotate(catalog_duration=Coalesce(Subquery(duration, output_field=BigIntegerField()), Value(0, output_field=BigIntegerField())))
        if filters.get('duration_min') not in (None, ''):
            editions = editions.filter(catalog_duration__gte=filters['duration_min']*60000)
        if filters.get('duration_max') not in (None, ''):
            editions = editions.filter(catalog_duration__lte=filters['duration_max']*60000)
    # Prefetch runs only AFTER the outer LIMIT. It makes card and deadline
    # serialization independent of page size without extra per-edition SELECTs.
    return editions.prefetch_related(
        Prefetch('live_revision__assets', queryset=Asset.objects.filter(kind='cover', state='ready').only('id', 'revision_id'), to_attr='_catalog_covers'),
        Prefetch('live_revision__rights', queryset=rights.only('id', 'revision_id', 'format', 'ends_at').order_by('-ends_at'), to_attr='_catalog_rights'),
    )


def card_from_edition(edition):
    revision = edition.live_revision
    formats = [fmt for fmt in FORMATS if getattr(edition, 'catalog_right_'+fmt, False)
               and getattr(edition, 'catalog_asset_'+fmt, False) and revision.access_policy.get(fmt) in {'free', 'paid'}]
    if not formats:
        raise DomainError('content_unavailable', 'Edition is not currently available.', 404)
    cover = None
    metadata = revision.validation_evidence.get('cover_pair', {}).get('front', {})
    selected = metadata.get('asset_id')
    assets = revision._catalog_covers
    asset = next((row for row in assets if str(row.pk) == str(selected)), None) if selected else next(iter(assets), None)
    if asset:
        base = getattr(settings, 'PUBLIC_BASE_URL', 'http://127.0.0.1:8008' if getattr(settings, 'LOCAL', False) else '').rstrip('/')
        if not base:
            raise DomainError('configuration_required', 'Public application origin is not configured.', 503)
        cover = {'url': f'{base}/api/v1/content/covers/{asset.pk}', 'width': metadata.get('width',600),
                 'height': metadata.get('height',900), 'alt': revision.title+' — cover'}
    return {'work_id': str(edition.work_id), 'edition_id': str(edition.pk), 'title': revision.title,
            'subtitle': None, 'creators': edition.work.creators, 'locale': edition.locale, 'house': edition.work.house,
            'formats': formats, 'cover': cover, 'access_label': 'free' if edition.catalog_free else 'pass_required',
            'availability': 'available'}


def page_ttl(editions, class_seconds=30):
    now = timezone.now()
    ends = []
    for edition in editions:
        revision = edition.live_revision
        # current_right chooses the longest valid grant per format; the shortest
        # of those deadlines caps the whole page's shared-cache lifetime.
        for fmt in FORMATS:
            if getattr(edition, 'catalog_right_'+fmt, False) and revision.access_policy.get(fmt) in {'free','paid'}:
                right = next((row for row in revision._catalog_rights if row.format == fmt), None)
                if right:
                    ends.append(right.ends_at)
    return max(0, min(class_seconds, math.floor((min(ends)-now).total_seconds()))) if ends else class_seconds


def catalog_page(request, locale=None, territory='IN', query='', house='', format='', **filters):
    """Return (public pagination DTO, cache TTL); SQL candidates capped limit+1."""
    from .services import content_locale
    locale=content_locale(locale)
    query = normalize_search_text(query)
    rows = catalog_queryset(locale, territory, query, house, format, **filters)
    ordering = '-search_score' if query else 'catalog_title'
    is_search = request.path.endswith('/search')
    page = paginate_queryset(request, rows, 'public-catalog:'+(locale or 'all')+':'+territory, ordering=ordering, maximum=50 if is_search else 100)
    ttl = page_ttl(page['items'])
    score = getattr(page['items'][0], 'search_score', None) if page['items'] else None
    mode = 'none' if not page['items'] else ('prefix' if score is None else 'exact' if score >= 5 else 'prefix' if score >= 4 else 'alias' if score >= 3 else 'full_text' if score >= 2 else 'fuzzy')
    page['items'] = [card_from_edition(row) for row in page['items']]
    if is_search:
        page.update({'query': query, 'locale': locale, 'territory': territory, 'match_mode': mode})
    return page, ttl


def catalog_cards_bounded(locale=None, territory='IN', query='', house='', format='', *, limit=100, **filters):
    """Small SSR/Home candidate list, never an unbounded catalog scan."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('Catalog candidate limit must be 1–500.')
    return [card_from_edition(row) for row in catalog_queryset(locale, territory, query, house, format, **filters)[:limit]]
