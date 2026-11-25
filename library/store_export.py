"""Google Play Books export bundle (local files only; no network or provider calls).

The bundle carries metadata.json, cover.jpg and an audio/ listing of private storage
keys + sha256 so the owner's upload step can fetch the bytes. Private audio is not copied.
"""
import json
from pathlib import Path

from django.conf import settings

from core.api import DomainError
from .models import Edition
from .services import FORMATS, publication_clearance_matches
from .storage import read_verified

NARRATION = {'type': 'ai', 'disclosure': 'Narrated with an AI voice.'}


def audio_cleared_everywhere(revision):
    """Same private evidence validate_revision reads (exact asset_sha256 included); 'audio' must be a cleared format."""
    if revision.access_policy.get('audio', 'deny') == 'deny':
        return False
    ready = list(revision.assets.filter(state='ready'))
    regions = list(settings.MAISON_PUBLICATION_TERRITORIES)
    offered = [f for f in FORMATS if revision.access_policy.get(f, 'deny') != 'deny']
    return 'audio' in offered and publication_clearance_matches(revision, ready, offered, regions)


def _front_cover(revision):
    covers = revision.assets.filter(kind='cover', state='ready').order_by('id')
    front_id = revision.validation_evidence.get('cover_pair', {}).get('front', {}).get('asset_id')
    return covers.filter(pk=front_id).first() if front_id else covers.first()


def export_play_books(edition_id, out_dir):
    edition = Edition.objects.select_related('work', 'live_revision').filter(pk=edition_id).first()
    revision = edition.live_revision if edition else None
    if revision is None or revision.state != 'live':
        raise DomainError('NOT_PUBLISHED', 'The edition has no live revision.', 409)
    if revision.access_policy.get('audio', 'deny') == 'deny' or not audio_cleared_everywhere(revision):
        raise DomainError('STORE_FORMAT_NOT_CLEARED', 'Audio is not cleared in every publication territory.', 409)
    cover = _front_cover(revision)
    if cover is None:
        raise DomainError('STORE_COVER_MISSING', 'A ready front cover is required.', 409)
    chapters = []
    for unit in revision.units.order_by('ordinal'):
        asset = revision.assets.filter(kind='audio_chapter', state='ready', unit=unit).order_by('id').first()
        if asset is None:
            raise DomainError('STORE_AUDIO_INCOMPLETE', f'Chapter {unit.ordinal} has no ready audio.', 409)
        chapters.append({'ordinal': unit.ordinal, 'title': unit.title, 'duration_ms': asset.duration_ms or unit.duration_ms,
                         'file': f'audio/{unit.ordinal:03d}.mp3', 'storage_key': asset.storage_key,
                         'sha256': asset.sha256, 'bytes': asset.bytes})
    if not chapters:
        raise DomainError('STORE_AUDIO_INCOMPLETE', 'No audio chapters.', 409)
    translation = None
    if edition.translation_method:
        translation = {'method': edition.translation_method, 'credit': edition.translation_credit,
                       'model': edition.translation_model}
    manifest = {
        'title': revision.title, 'authors': list(edition.work.creators), 'language': edition.locale,
        'publisher': 'Earnalism', 'territories': list(settings.MAISON_PUBLICATION_TERRITORIES),
        'narration': dict(NARRATION), 'translation': translation, 'description': revision.description,
        'chapters': chapters,
    }
    cover_bytes = read_verified(cover)
    if cover.content_type != 'image/jpeg' or cover_bytes[:3] != b'\xff\xd8\xff':
        raise DomainError('STORE_COVER_NOT_JPEG', 'The front cover must be a JPEG.', 409)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'audio').mkdir(exist_ok=True)
    (out / 'cover.jpg').write_bytes(cover_bytes)
    (out / 'audio' / 'listing.json').write_text(json.dumps(
        [{k: c[k] for k in ('file', 'storage_key', 'sha256', 'bytes')} for c in chapters], indent=2))
    (out / 'metadata.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest
