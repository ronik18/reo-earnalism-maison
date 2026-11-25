"""Licensing catalogue: editor-revised translations only (AI-only translations are never listed)."""
from django.conf import settings
from django.db.models import Sum

from . import services as svc
from .models import Asset, Edition, Unit

COLUMNS = ['edition_slug', 'title', 'language', 'source_edition_slug', 'source_language',
           'editor_credit', 'audio_duration_ms', 'cover_url', 'territories']


def licensing_rows():
    editions = (Edition.objects.filter(translation_method='ai_edited', translated_from__isnull=False,
                                       live_revision__state='live')
                .exclude(translation_credit='').select_related('live_revision', 'translated_from').order_by('slug'))
    territories = ' '.join(settings.MAISON_PUBLICATION_TERRITORIES)
    rows = []
    for e in editions:
        rev = e.live_revision
        audio_units = Asset.objects.filter(revision=rev, kind='audio_chapter', state='ready',
                                           unit__isnull=False).values('unit')
        total = Unit.objects.filter(revision=rev, pk__in=audio_units,
                                    duration_ms__isnull=False).aggregate(t=Sum('duration_ms'))['t']
        cover = svc._cover(rev)
        rows.append({'edition_slug': e.slug, 'title': rev.title, 'language': e.locale,
                     'source_edition_slug': e.translated_from.slug, 'source_language': e.translated_from.locale,
                     'editor_credit': e.translation_credit, 'audio_duration_ms': total if total else '',
                     'cover_url': cover['url'] if cover else '', 'territories': territories})
    return rows
