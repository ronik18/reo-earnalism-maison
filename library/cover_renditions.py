"""Fixed public cover renditions on content-addressed paths (owner decision, 26 Nov 2026).

A public cover is served at ``/api/v1/content/covers/{asset_id}/{sha256}/w{width}.jpg``
for the reviewed widths only (no arbitrary resize service). The path names the
exact verified original bytes, so it changes whenever the cover changes and can
be cached by browsers as immutable. Renditions are derived on request from the
verified original with Pillow and kept in a small bounded in-process cache; the
CDN and browsers hold them afterwards. The 800x1200 original is never altered:
a width at or above the original's width serves the original bytes unchanged.
"""
import io
import re
import threading
from collections import OrderedDict

COVER_WIDTHS = (160, 320, 480, 800)
DEFAULT_WIDTH = 800
IMMUTABLE_CACHE_CONTROL = 'public, max-age=31536000, immutable'
UNVERSIONED_CACHE_CONTROL = 'public, max-age=86400, stale-while-revalidate=604800'
JPEG_QUALITY = 82
_MEMO_BYTES = 32 * 1024 * 1024
_memo = OrderedDict()
_memo_size = 0
_lock = threading.Lock()
_RENDITION_URL = re.compile(r'^(?P<prefix>.*/api/v1/content/covers/[0-9a-f-]{36}/[0-9a-f]{64}/)w\d+\.jpg$')


def rendition_path(asset_id, sha256, width=DEFAULT_WIDTH):
    if width not in COVER_WIDTHS:
        raise ValueError('Unsupported cover width')
    return f'/api/v1/content/covers/{asset_id}/{sha256}/w{width}.jpg'


def rendition_url(url, width):
    """Same cover at another reviewed width; non-rendition URLs are returned unchanged."""
    match = _RENDITION_URL.match(url or '')
    if not match or width not in COVER_WIDTHS:
        return url
    return f"{match['prefix']}w{width}.jpg"


def is_rendition_url(url):
    return bool(_RENDITION_URL.match(url or ''))


def _derive(raw, width):
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as image:
        if image.width <= width:
            return None
        height = max(1, round(image.height * width / image.width))
        image.draft('RGB', (width, height))  # JPEG decoders may shrink by a power of two first.
        if image.mode in ('RGBA', 'LA', 'P', 'PA'):
            image = image.convert('RGBA')
            flat = Image.new('RGB', image.size, (255, 255, 255))
            flat.paste(image, mask=image.getchannel('A'))
            image = flat
        else:
            image = image.convert('RGB')
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
        return out.getvalue()


def rendition(asset, width, read_original):
    """Return (bytes, content_type) of a reviewed width of a verified cover asset."""
    global _memo_size
    if width not in COVER_WIDTHS:
        raise ValueError('Unsupported cover width')
    key = (str(asset.pk), asset.sha256, width)
    with _lock:
        hit = _memo.get(key)
        if hit:
            _memo.move_to_end(key)
            return hit
    raw = read_original(asset)
    derived = _derive(raw, width)
    result = (raw, asset.content_type) if derived is None else (derived, 'image/jpeg')
    if derived is not None:
        with _lock:
            if key not in _memo:
                _memo[key] = result
                _memo_size += len(derived)
                while _memo_size > _MEMO_BYTES and _memo:
                    _, (old, _type) = _memo.popitem(last=False)
                    _memo_size -= len(old)
    return result


def clear_memo():
    global _memo_size
    with _lock:
        _memo.clear()
        _memo_size = 0
