"""Small, I/O-free clearance reads for public surfaces such as the podcast feed."""
from django.conf import settings


def audio_cleared(revision):
    """True only when the live revision's recorded legal clearance passed for the exact text
    and covers the audio format across every whitelisted publication territory."""
    clearance = (revision.validation_evidence or {}).get('publication_clearance', {})
    return (revision.state == 'live' and bool(revision.published_at) and isinstance(clearance, dict)
            and clearance.get('status') == 'pass'
            and clearance.get('sha256') == revision.content_sha256
            and isinstance(clearance.get('formats'), list) and 'audio' in clearance['formats']
            and isinstance(clearance.get('territories'), list)
            and set(settings.MAISON_PUBLICATION_TERRITORIES) <= set(clearance['territories'])
            and isinstance(clearance.get('evidence_ref'), str) and bool(clearance['evidence_ref'].strip()))
