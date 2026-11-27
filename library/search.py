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
from .romanize import normalize_latin_query, romanize_bn
from .search_models import SearchAlias, SearchDocument

INDEX = 'live_revision__search_index__'


def romanized_title_ids(queryset, query):
    """Pks of already-published editions whose Bengali title reads as the Latin query.

    Computed per request from the caller's (published/locale-scoped) queryset, so a
    draft title can never match; no table or cache. Cost is linear in the number of
    published Bengali titles and deliberately uncapped, so a published title can never
    silently drop out of the scan; at catalogue scale precompute the
    variants on SearchDocument at refresh time and index them instead.
    """
    key = normalize_latin_query(query)
    if len(key) < 3:
        return []
    rows = queryset.filter(**{INDEX + 'title_normalized__regex': '[\u0980-\u09ff]'}).values_list(
        'pk', INDEX + 'title_normalized').iterator()
    return [pk for pk, title in rows if any(form.startswith(key) for form in romanize_bn(title))]


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


def search_editions(queryset, query, locale=None):
    """Rank live editions exact > prefix > reviewed alias > romanized Bengali title > FTS > title typo.

    Candidate predicates use the GIN text/vector and trigram indexes. Fuzzy
    matching is disabled for very short input; no per-session threshold changes
    are made, which keeps pooled Postgres connections safe. Score+UUID supports
    a deterministic keyset cursor (no COUNT or full catalog materialization).
    """
    from .services import content_locale
    locale=content_locale(locale)
    query = normalize_search_text(query)
    if len(query) > 120:
        raise DomainError('invalid_query', 'Search supports at most 120 characters.', 422)
    queryset = queryset.filter(live_revision__state='live',live_revision__search_index__locale=F('locale'))
    if locale is not None:queryset=queryset.filter(locale=locale)
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
    aliases=SearchAlias.objects.filter(active=True,reviewed_at__lte=timezone.now(),alias_normalized__in=alias_keys)
    if locale is not None:aliases=aliases.filter(locale=locale)
    targets=list(aliases.order_by('locale','alias_normalized').values_list('locale','target_normalized')[:16])
    romanized_match=Q(pk__in=romanized_title_ids(queryset,query))
    simple_query=SearchQuery(query,config='simple',search_type='plain')
    languages={locale} if locale is not None else {'en'}
    languages.update(language for language,_ in targets)
    per_language={language:SearchQuery(query,config='english' if language=='en' else 'simple',search_type='plain') for language in languages}
    alias_match=Q(pk__in=[])
    for language,target in targets:
        alias_match |= Q(locale=language) & (Q(**{title:target}) | Q(**{title+'__startswith':target}))
        per_language[language] |= SearchQuery(target,config='english' if language=='en' else 'simple',search_type='plain')
    # Keep every @@ RHS a real SearchQuery: Django otherwise wraps a Case tsquery
    # in plainto_tsquery(tsquery). Each language branch also retains alias scope.
    fts=~Q(locale__in=list(per_language)) & Q(**{INDEX+'document':simple_query})
    ranking=[]
    for language,vector_query in sorted(per_language.items()):
        fts |= Q(locale=language) & Q(**{INDEX+'document':vector_query})
        ranking.append(When(locale=language,then=SearchRank(F(INDEX+'document'),vector_query,normalization=32)))
    fuzzy = Q(TrigramSimilar(F(title), Value(query)))
    rank = Coalesce(Case(*ranking,default=SearchRank(F(INDEX+'document'),simple_query,normalization=32),output_field=FloatField()),Value(0.0))
    similarity = TrigramSimilarity(F(title), Value(query))
    return queryset.filter(exact | prefix | alias_match | romanized_match | fts | fuzzy).annotate(
        search_score=Case(
            When(exact, then=Value(5.0)), When(prefix, then=Value(4.0)),
            When(alias_match, then=Value(3.0)), When(romanized_match, then=Value(2.5)), When(fts, then=Value(2.0)),
            default=Value(1.0), output_field=FloatField(),
        ) + rank * Value(0.1) + similarity * Value(0.01),
    ).order_by('-search_score', '-id')
