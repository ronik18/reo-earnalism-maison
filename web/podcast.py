"""Public podcast feed: one item per cleared edition with free audio.

Audio bytes are served only through the authenticated player, so items carry no enclosure
and never expose storage URLs; each item links its title page with podcast campaign tags.

LIMITATION: The feed has no audio enclosures because full narration is members-only. Apple
Podcasts, Spotify and most directories require an audio enclosure per episode, so the feed will
likely be rejected or show no episodes until the owner approves public audio (e.g. a cleared
CDN-hosted preview or full episode)."""
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

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
        _text(item, 'description', revision.description)
        _text(item, 'guid', str(edition.id)).set('isPermaLink', 'false')
        _text(item, 'pubDate', revision.published_at.strftime('%a, %d %b %Y %H:%M:%S +0000'))
        _text(item, _it('explicit'), 'false')
    body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(rss, encoding='utf-8')
    response = HttpResponse(body, content_type='application/rss+xml; charset=utf-8')
    response['Cache-Control'] = 'public,max-age=0,must-revalidate'  # same as the other public page (offline_shell)
    response['Content-Language'] = locale
    return response
