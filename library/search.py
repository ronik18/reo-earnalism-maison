"""PostgreSQL-only public metadata search; never indexes paid Reader text.

The index is derived and can be rebuilt independently of immutable revisions.
Publisher callers refresh it in the same transaction as the live-pointer change.
"""
import unicodedata

from django.contrib.postgres.lookups import TrigramSimilar
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity
from django.db import transaction
from django.db.models import Case, F, FloatField, Q, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.api import DomainError
from .models import Revision
from .search_models import SearchAlias, SearchDocument

INDEX = 'live_revision__search_index__'


def normalize_search_text(value):
    if not isinstance(value, str):
        raise DomainError('invalid_query', 'Search query must be text.', 422)
    # Preserve Bengali vowel signs, virama and joiners; NFC is not transliteration.
    return unicodedata.normalize('NFC', ' '.join(value.split())).casefold()


@transaction.atomic
def refresh_revision_search(revision):
    """Upsert public metadata only, without touching Revision.version/content.

    Draft indexes are safe to prepare, but search_editions always requires the
    current live pointer. A live-only rebuild command supplies the repair path.
    """
    if not isinstance(revision, Revision):
        revision = Revision.objects.select_related('edition__work').get(pk=revision)
    work = revision.edition.work
    creators = work.creators if isinstance(work.creators, list) else []
    title = normalize_search_text(revision.title)
    metadata = normalize_search_text(' '.join([
        work.title, revision.description, work.topic,
        ' '.join(value for value in creators if isinstance(value, str)),
    ]))
    row, _ = SearchDocument.objects.update_or_create(
        revision=revision,
        defaults={'title_normalized': title, 'text_normalized': metadata, 'locale': revision.edition.locale},
    )
    config = 'english' if revision.edition.locale == 'en' else 'simple'
    SearchDocument.objects.filter(pk=row.pk).update(document=(
        SearchVector('title_normalized', config=config, weight='A') +
        SearchVector('text_normalized', config=config, weight='B')
    ))
    return row


def search_editions(queryset, query, locale='en'):
    """Rank live editions exact > prefix > reviewed alias > FTS > title typo.

    Candidate predicates use the GIN text/vector and trigram indexes. Fuzzy
    matching is disabled for very short input; no per-session threshold changes
    are made, which keeps pooled Postgres connections safe. Score+UUID supports
    a deterministic keyset cursor (no COUNT or full catalog materialization).
    """
    query = normalize_search_text(query)
    if locale not in {'en', 'bn'} or len(query) > 120:
        raise DomainError('invalid_query', 'Search supports en/bn and at most 120 characters.', 422)
    queryset = queryset.filter(locale=locale, live_revision__state='live',
                               live_revision__search_index__locale=locale)
    if not query:
        return queryset.order_by('work__title', 'id')
    title = INDEX + 'title_normalized'
    exact = Q(**{title: query})
    prefix = Q(**{title + '__startswith': query})
    meaningful = sum(char.isalnum() or unicodedata.category(char).startswith('M') for char in query)
    if meaningful < 3:
        return queryset.filter(prefix).annotate(search_score=Case(
            When(exact, then=Value(5.0)), default=Value(4.0), output_field=FloatField(),
        )).order_by('-search_score', '-id')

    # Only explicitly reviewed, currently active aliases participate. One bounded
    # lookup covers a whole query and its first 12 tokens; no recursive expansion.
    alias_keys = list(dict.fromkeys([query, *query.split()[:12]]))
    targets = list(SearchAlias.objects.filter(
        locale=locale, active=True, reviewed_at__lte=timezone.now(),
        alias_normalized__in=alias_keys,
    ).order_by('alias_normalized').values_list('target_normalized', flat=True)[:16])
    config = 'english' if locale == 'en' else 'simple'
    vector_query = SearchQuery(query, config=config, search_type='plain')
    alias_match = Q(pk__in=[])
    for target in targets:
        alias_match |= Q(**{title: target}) | Q(**{title + '__startswith': target})
        vector_query |= SearchQuery(target, config=config, search_type='plain')
    fts = Q(**{INDEX + 'document': vector_query})
    fuzzy = Q(TrigramSimilar(F(title), Value(query)))
    rank = Coalesce(SearchRank(F(INDEX + 'document'), vector_query, normalization=32), Value(0.0))
    similarity = TrigramSimilarity(F(title), Value(query))
    return queryset.filter(exact | prefix | alias_match | fts | fuzzy).annotate(
        search_score=Case(
            When(exact, then=Value(5.0)), When(prefix, then=Value(4.0)),
            When(alias_match, then=Value(3.0)), When(fts, then=Value(2.0)),
            default=Value(1.0), output_field=FloatField(),
        ) + rank * Value(0.1) + similarity * Value(0.01),
    ).order_by('-search_score', '-id')
