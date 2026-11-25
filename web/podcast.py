"""Public podcast feed: one item per cleared edition with free audio.

Owner decision D10: the episode is the title's public audio preview (a bounded, separately
prepared clip), never full narration. An enclosure is emitted only when
library.audio_preview.prepared_clip accepts the revision's ready preview_audio asset; it points
at the public territory-checked preview route, never at storage or full audio. Items without a
prepared clip stay link-only."""
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

ITUNES = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ET.register_namespace('itunes', ITUNES)


def _it(tag):
    return '{%s}%s' % (ITUNES, tag)


def _text(parent, tag, value):
    el = ET.SubElement(parent, tag)
    el.text = value
    return el


PREVIEW_NOTE = 'Preview \u2014 listen to the full story on Earnalism.'


def _prepared_preview(revision):
    """The revision's accepted preview clip asset, or None."""
    from core.api import DomainError
    from library.audio_preview import prepared_clip
    proof = revision.validation_evidence.get('audio_preview')
    asset_id = proof.get('asset_id') if isinstance(proof, dict) else None
    if not asset_id:
        return None
    try:
        asset = revision.assets.get(pk=asset_id, kind='preview_audio', state='ready')
        asset.revision = revision
        prepared_clip(asset)
    except (DomainError, ValueError, ValidationError, ObjectDoesNotExist):
        return None
    return asset


def _enclosure_url(request, asset):
    base = (settings.PUBLIC_BASE_URL or '').rstrip('/')
    path = '/api/v1/content/audio-previews/%s' % asset.id
    return base + path if base else request.build_absolute_uri(path)


@require_GET
def feed(request, locale):
    if locale not in ('en', 'bn'):
        raise Http404
    from library.store_export import audio_cleared_everywhere
    from library.models import Edition
    rss = ET.Element('rss', {'version': '2.0'})
    channel = ET.SubElement(rss, 'channel')
    site = request.build_absolute_uri(reverse('web:home', args=['en']))
    _text(channel, 'title', 'Earnalism')
    _text(channel, 'link', site)
    _text(channel, 'description', 'Narrated stories from Earnalism.')
    _text(channel, 'language', locale)
    _text(channel, _it('author'), 'Earnalism')
    _text(channel, _it('explicit'), 'false')
    arts = ET.SubElement(channel, _it('category'), {'text': 'Arts'})
    ET.SubElement(arts, _it('category'), {'text': 'Books'})
    editions = (Edition.objects.select_related('live_revision', 'work')
                .filter(locale=locale, live_revision__state='live', live_revision__published_at__isnull=False)
                .order_by('-live_revision__published_at', 'slug'))
    for edition in editions:
        revision = edition.live_revision
        if revision.access_policy.get('audio') != 'free' or not audio_cleared_everywhere(revision):
            continue
        link = request.build_absolute_uri(reverse('web:title', args=['en', edition.slug])) + '?' + urlencode(
            {'utm_source': 'podcast', 'utm_medium': 'feed', 'utm_campaign': edition.slug})
        item = ET.SubElement(channel, 'item')
        _text(item, 'title', revision.title)
        _text(item, 'link', link)
        preview = _prepared_preview(revision)
        description = revision.description
        if preview:
            description = (description + ' ' if description else '') + PREVIEW_NOTE + ' ' + link
        _text(item, 'description', description)
        _text(item, 'guid', str(edition.id)).set('isPermaLink', 'false')
        _text(item, 'pubDate', revision.published_at.strftime('%a, %d %b %Y %H:%M:%S +0000'))
        _text(item, _it('explicit'), 'false')
        if preview:
            ET.SubElement(item, 'enclosure', {'url': _enclosure_url(request, preview), 'length': str(preview.bytes),
                                              'type': 'audio/mpeg'})
            _text(item, _it('duration'), str(round(preview.duration_ms / 1000)))
            _text(item, _it('episodeType'), 'full')
    body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding='utf-8')
    response = HttpResponse(body, content_type='application/rss+xml; charset=utf-8')
    response['Cache-Control'] = 'public,max-age=0,must-revalidate'  # same as the other public page (offline_shell)
    response['Content-Language'] = locale
    return response
