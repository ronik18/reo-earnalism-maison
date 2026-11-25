"""Owner cover pair: derive 800x1200 delivery JPEGs with provenance."""
import hashlib
import io
import json
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

CLOUD = "dzlrhlfpu"
SCHEMA = "earnalism.cover-provenance.v2"
STATUS = "OWNER_PROVIDED_ARTWORK"
SIZE = (800, 1200)
QUALITY = 90
DERIVATION = "Pillow LANCZOS resize to 800x1200, JPEG quality 90, metadata not copied"
DEFAULT_OWNER_STATEMENT = {
    "date": "2026-11-25",
    "text": 'Owner: "You may find the book covers already designed by me and uploaded in cloudinary account for the next story books."',
}
DEFAULT_BASIS = (
    "Owner-created artwork with owner-held copyright, the same basis recorded for "
    "বিচারক (legacy-owner_artwork_declaration.json). Selected by Claude by reading "
    "the cover title and author lettering; front and back share the Cloudinary asset id."
)
SCOPE = "Cover display only; grants no text, audio or publication authorization."
_TIMEOUT = 30


class CoverError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def original_url(listing):
    return (
        f"https://res.cloudinary.com/{CLOUD}/image/upload/"
        f"v{listing['version']}/{listing['public_id']}.{listing['format']}"
    )


def _derive_side(raw, listing):
    if len(raw) != listing["bytes"]:
        raise CoverError("COVER_BYTES_MISMATCH", f"{len(raw)} != {listing['bytes']}")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise CoverError("COVER_UNREADABLE", str(exc)) from exc
    decoded_format = (image.format or "").lower().replace("jpg", "jpeg")
    if (
        (image.width, image.height) != (listing["width"], listing["height"])
        or decoded_format != str(listing["format"]).lower().replace("jpg", "jpeg")
    ):
        raise CoverError(
            "COVER_LISTING_MISMATCH",
            f"decoded {image.width}x{image.height} {decoded_format}",
        )
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    if width * 3 != height * 2:
        raise CoverError("COVER_RATIO", f"{width}x{height}")
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        base.alpha_composite(rgba)
        image = base
    rgb = image.convert("RGB").resize(SIZE, Image.LANCZOS)
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=QUALITY)
    original = {
        "url": original_url(listing),
        "public_id": listing["public_id"],
        "asset_id": listing["asset_id"],
        "version": listing["version"],
        "created_at": listing["created_at"],
        "format": listing["format"],
        "width": width,
        "height": height,
        "bytes": len(raw),
        "sha256": _sha(raw),
    }
    return out.getvalue(), original


def derive_pair(front_raw, back_raw, originals, *, slug="", owner_statement=None, basis=None):
    f_l, b_l = originals["front"], originals["back"]
    if f_l["public_id"] == b_l["public_id"] or f_l["asset_id"] == b_l["asset_id"]:
        raise CoverError("COVER_PAIR_DUPLICATE", "front and back are the same asset")
    sides = {}
    outputs = {}
    for name, raw in (("front", front_raw), ("back", back_raw)):
        data, original = _derive_side(raw, originals[name])
        outputs[name] = data
        sides[name] = {
            "original": original,
            "delivery": {
                "path": f"{name}.jpg",
                "width": SIZE[0],
                "height": SIZE[1],
                "format": "JPEG",
                "bytes": len(data),
                "sha256": _sha(data),
                "derivation": DERIVATION,
            },
        }
    if sides["front"]["original"]["sha256"] == sides["back"]["original"]["sha256"]:
        raise CoverError("COVER_PAIR_DUPLICATE", "front and back bytes are identical")
    provenance = {
        "schema": SCHEMA,
        "slug": slug,
        "status": STATUS,
        "owner_statement": owner_statement or dict(DEFAULT_OWNER_STATEMENT),
        "basis": basis or DEFAULT_BASIS,
        "scope": SCOPE,
        "sides": sides,
    }
    return outputs["front"], outputs["back"], provenance


def _get(url):
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:  # noqa: S310
        return response.read()


def fetch_listing(public_id):
    url = f"https://api.cloudinary.com/v1_1/{CLOUD}/resources/image/upload/{public_id}"
    try:
        data = json.loads(_get(url))
        return {
            key: data[key]
            for key in ("public_id", "asset_id", "version", "format", "width", "height", "bytes", "created_at")
        }
    except Exception as exc:
        raise CoverError("COVER_LISTING_FAILED", f"{public_id}: {exc}") from exc


def download_original(listing):
    try:
        return _get(original_url(listing))
    except Exception as exc:
        raise CoverError("COVER_DOWNLOAD_FAILED", str(exc)) from exc


def build_packet(slug, front_id, back_id, folder, *, replace=False, owner_statement=None, basis=None):
    folder = Path(folder)
    targets = [folder / n for n in ("front.jpg", "back.jpg", "cover_provenance.json")]
    if not replace and any(t.exists() for t in targets):
        raise CoverError("COVER_EXISTS", "use --replace to overwrite")
    listings = {"front": fetch_listing(front_id), "back": fetch_listing(back_id)}
    raws = {k: download_original(v) for k, v in listings.items()}
    front, back, provenance = derive_pair(
        raws["front"], raws["back"], listings,
        slug=slug, owner_statement=owner_statement, basis=basis,
    )
    folder.mkdir(parents=True, exist_ok=True)
    targets[0].write_bytes(front)
    targets[1].write_bytes(back)
    targets[2].write_text(json.dumps(provenance, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return provenance
