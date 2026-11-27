"""A film's measured timing map: where each paragraph (or sentence) of the unit is narrated on the film timeline.

The film skill (`eav film --shots`) places the same v4 narration on the film after the title card, scene by scene,
with frame-aligned scene starts; it knows each clause's film time. The film bundle carries that as one JSON file per
unit (shape: docs/interface-notes/2026-11-27-film-timing-map.md), anchored to the LIVE revision the film was made
from. The film importer stages the film on a clone of that revision, whose anchors are new, so this module:

  read_film_timing(raw, unit_id=, mp4_sha256=, text_sha256=)   bounded parse and exact-shape check, bound to the
                                                                bundle's unit, film bytes and live text
  anchor_map_by_ordinal(live_unit, draft_unit)                  live anchor -> clone anchor, by paragraph ordinal
  film_timing_maps(revision, video, parsed, anchor_map)         unsaved TimingMap rows on the film asset, each
                                                                checked by library.timing.validated_segments

Film maps are the same TimingMap rows as audio maps (asset kind video), so /content/switch-position composes
reader anchor <-> film time, and audio <-> film through the text. They are never listed by /content/mappings.
"""
import json
import re

from .sentences import split_sentences

SCHEMA = "earnalism.audiovisual-film-timing.v1"
MAX_BYTES = 1_048_576
MAX_SEGMENTS = 2000
DOC_KEYS = {"schema", "unit_id", "mp4_sha256", "text_sha256", "measurement_evidence_ref", "maps"}
MAP_KEYS = {"precision", "segments"}
SEGMENT_KEYS = {"anchor_id", "start_offset_chars", "end_offset_chars", "start_ms", "end_ms"}
HEX64 = re.compile(r"[a-f0-9]{64}")


class FilmTimingError(ValueError):
    """The film timing file is malformed or not bound to this film, text or unit; nothing is written."""


def _int(value, low):
    return type(value) is int and value >= low


def read_film_timing(raw, *, unit_id, mp4_sha256, text_sha256):
    """Parse and check one unit's film timing file. Returns {"measurement_evidence_ref", "maps": [(precision,
    segments)]} with the paragraph map first; anchors are still the live revision's."""
    if not isinstance(raw, (bytes, bytearray)) or not 1 <= len(raw) <= MAX_BYTES:
        raise FilmTimingError(f"film timing must be 1..{MAX_BYTES} bytes of JSON.")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise FilmTimingError("film timing is not JSON.") from None
    if not isinstance(doc, dict) or set(doc) != DOC_KEYS or doc["schema"] != SCHEMA:
        raise FilmTimingError(f'film timing must be {{"schema": "{SCHEMA}", {", ".join(sorted(DOC_KEYS - {"schema"}))}}}.')
    if doc["unit_id"] != str(unit_id):
        raise FilmTimingError("film timing unit_id differs from the film's unit.")
    if not isinstance(doc["mp4_sha256"], str) or not HEX64.fullmatch(doc["mp4_sha256"]) or doc["mp4_sha256"] != mp4_sha256:
        raise FilmTimingError("film timing mp4_sha256 differs from the film.")
    if doc["text_sha256"] != text_sha256:
        raise FilmTimingError("film timing text_sha256 differs from the live text the film narrates.")
    ref = doc["measurement_evidence_ref"]
    if not isinstance(ref, str) or not ref.strip() or len(ref) > 500:
        raise FilmTimingError("film timing needs a non-blank measurement_evidence_ref (at most 500 characters).")
    maps = doc["maps"]
    if not isinstance(maps, list) or not 1 <= len(maps) <= 2:
        raise FilmTimingError("film timing maps must hold a paragraph map and at most one sentence map.")
    parsed = {}
    for i, row in enumerate(maps):
        if not isinstance(row, dict) or set(row) != MAP_KEYS or row["precision"] not in {"paragraph", "sentence"}:
            raise FilmTimingError(f'maps[{i}] must be {{"precision": "paragraph"|"sentence", "segments": [...]}}.')
        if row["precision"] in parsed:
            raise FilmTimingError(f"maps[{i}] repeats precision {row['precision']}.")
        segments = row["segments"]
        if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
            raise FilmTimingError(f"maps[{i}] needs 1..{MAX_SEGMENTS} segments.")
        sentence = row["precision"] == "sentence"
        for k, seg in enumerate(segments):
            keys = set(seg) if isinstance(seg, dict) else set()
            if (keys not in (SEGMENT_KEYS, SEGMENT_KEYS | {"sentence_index"}) or (keys != SEGMENT_KEYS and not sentence)
                    or not isinstance(seg["anchor_id"], str)
                    or not all(_int(seg[key], 0) for key in ("start_offset_chars", "start_ms"))
                    or not all(_int(seg[key], 1) for key in ("end_offset_chars", "end_ms"))
                    or ("sentence_index" in seg and not _int(seg["sentence_index"], 0))):
                raise FilmTimingError(f"maps[{i}].segments[{k}] must be {{{', '.join(sorted(SEGMENT_KEYS))}"
                                      f"{', sentence_index' if sentence else ''}}} with integer numbers.")
        parsed[row["precision"]] = segments
    if "paragraph" not in parsed:
        raise FilmTimingError("film timing needs a paragraph map.")
    return {"measurement_evidence_ref": ref.strip(),
            "maps": [(p, parsed[p]) for p in ("paragraph", "sentence") if p in parsed]}


def anchor_map_by_ordinal(live_unit, draft_unit):
    """{live anchor: draft anchor} for one unit and its clone (clone_revision keeps paragraph ordinals and text)."""
    from .models import Paragraph
    live = dict(Paragraph.objects.filter(unit=live_unit).values_list("ordinal", "anchor_id"))
    draft = dict(Paragraph.objects.filter(unit=draft_unit).values_list("ordinal", "anchor_id"))
    if set(live) != set(draft):
        raise FilmTimingError("the clone's paragraphs differ from the live unit's.")
    return {str(live[n]): str(draft[n]) for n in live}


def _check_sentences(segments, texts):
    """A sentence map gives each anchor either its whole-paragraph segment, or exactly library.sentences'
    split with sentence_index 0..n-1 (the reader's sentence highlight uses the same split)."""
    by_anchor = {}
    for seg in segments:
        by_anchor.setdefault(seg["anchor_id"], []).append(seg)
    for anchor, rows in by_anchor.items():
        if all("sentence_index" not in r for r in rows):
            continue
        spans = split_sentences(texts.get(anchor, ""))
        got = [(r.get("sentence_index"), r["start_offset_chars"], r["end_offset_chars"]) for r in rows]
        if got != [(i, a, b) for i, (a, b) in enumerate(spans)]:
            raise FilmTimingError(f"sentence segments of anchor {anchor} differ from the text's sentences {spans}.")


def film_timing_maps(revision, video, parsed, anchor_map):
    """Unsaved, fully checked TimingMap rows for `video` (a kind=video asset of the draft `revision`). The caller
    saves them inside its own transaction. Every live anchor must map into the film's unit."""
    from django.core.exceptions import ValidationError
    from core.api import DomainError
    from .models import Paragraph, TimingMap
    from .timing import validated_segments
    if video.kind != "video" or video.revision_id != revision.id or not video.unit_id:
        raise FilmTimingError("film timing belongs to a film asset of this revision with a unit.")
    paragraphs = {str(p.anchor_id): p for p in Paragraph.objects.filter(unit_id=video.unit_id)}
    texts = {anchor: p.text for anchor, p in paragraphs.items()}
    rows = []
    for precision, segments in parsed["maps"]:
        mapped = []
        for seg in segments:
            if seg["anchor_id"] not in anchor_map or anchor_map[seg["anchor_id"]] not in paragraphs:
                raise FilmTimingError(f"{precision} map anchor {seg['anchor_id']} is not a paragraph of the film's unit.")
            mapped.append({**seg, "anchor_id": anchor_map[seg["anchor_id"]]})
        if precision == "sentence":
            _check_sentences(mapped, texts)
        mapping = TimingMap(revision=revision, asset=video, text_sha256=revision.content_sha256,
                            asset_sha256=video.sha256, precision=precision, measured=True, segments=mapped)
        try:
            mapping.full_clean()
            validated_segments(mapping, paragraphs)
        except DomainError as exc:
            raise FilmTimingError(f"{precision} film map: {exc.message}") from None
        except ValidationError as exc:
            raise FilmTimingError(f"{precision} film map: {exc}") from None
        rows.append(mapping)
    return rows
