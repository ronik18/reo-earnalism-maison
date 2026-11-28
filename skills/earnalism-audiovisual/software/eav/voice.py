"""Earnalism Voice units: sentence-level TTS units with pauses, each short enough for Parler-TTS."""
from .text import sentences, words

SENTENCE_PAUSE_MS = 400
PARAGRAPH_PAUSE_MS = 800
HEADING_PAUSE_MS = 1200
REEL_LINE_PAUSE_MS = 400  # Squint pacing between reel lines (block kind "line")
CLAUSE_PAUSE_MS = 150  # after a part of a sentence split to fit MAX_UNIT_CHARS
MAX_CLAUSE_WORDS = 12
# Indic Parler-TTS stops at a hard ~30 s per generate(); at the measured ~11 characters/second
# 200 characters is about 18 s, well under the cap (applies to every language).
MAX_UNIT_CHARS = 200
CLAUSE_MARKS = ";:,—–।॥"
_CLOSERS = "\"'”’)]»"
_RUN = CLAUSE_MARKS + _CLOSERS  # a clause split falls after the whole punctuation run, e.g. ";—"


def _has_word(s: str) -> bool:
    return any(c.isalnum() for c in s)


def _clause_points(text: str) -> list:
    """(end of left part, start of right part) after each clause-punctuation run, whether or not
    a space follows it (",আর", "গেল;—এখানে"); never between digits (1,000 or 10:30)."""
    points, i = [], 0
    while i < len(text):
        if text[i] not in CLAUSE_MARKS:
            i += 1
            continue
        j = i
        while j < len(text) and text[j] in _RUN:
            j += 1
        k = j
        while k < len(text) and text[k].isspace():
            k += 1
        digits = k == j and i > 0 and j < len(text) and text[i - 1].isdigit() and text[j].isdigit()
        if not digits and _has_word(text[:j]) and _has_word(text[k:]):
            points.append((j, k))
        i = j
    return points


def _space_points(text: str) -> list:
    """(end of left part, start of right part) at each whitespace run between words."""
    points, i = [], 0
    while i < len(text):
        if not text[i].isspace():
            i += 1
            continue
        k = i
        while k < len(text) and text[k].isspace():
            k += 1
        if _has_word(text[:i]) and _has_word(text[k:]):
            points.append((i, k))
        i = k
    return points


def split_unit(text: str, limit: int = MAX_UNIT_CHARS) -> list:
    """Split a sentence into [(part, separator after it)] with every part at most `limit` characters.

    Clause punctuation only, while the text has any: the point closest to the middle that leaves
    both pieces within the limit, else the one closest to the middle, recursing on each piece.
    Whitespace (closest to the middle, likewise) only for a piece with no clause mark at all;
    never inside a word. Parts keep their exact characters: "".join(part + separator) is `text`
    byte for byte (the separator is "" after punctuation with no space, and for the last part).
    """
    if len(text) <= limit:
        return [(text, "")] if text else []
    points = _clause_points(text) or _space_points(text)
    if not points:
        raise ValueError(f"a {len(text)}-character run has no space or clause mark to split at; it "
                         f"cannot fit the {limit}-character voice-unit limit: {text[:40]!r}...")
    middle = len(text) / 2
    fits = [p for p in points if p[0] <= limit and len(text) - p[1] <= limit]
    j, k = min(fits or points, key=lambda p: abs(p[0] - middle))
    left, right = split_unit(text[:j], limit), split_unit(text[k:], limit)
    return left[:-1] + [(left[-1][0], text[j:k])] + right


def block_parts(text: str, language: str = "en") -> list:
    """[(unit text, ends its sentence, joiner)] for one block, in order; "".join(text + joiner)
    is the block's whitespace-normalised text (sentences are joined by one space)."""
    out = []
    sents = sentences(text, language)
    for n, s in enumerate(sents):
        parts = split_unit(s)
        for k, (p, sep) in enumerate(parts):
            last = k == len(parts) - 1
            out.append((p, last, (" " if n < len(sents) - 1 else "") if last else sep))
    return out


def voice_units(scene: dict, preset: dict, clause=None, language: str = "en") -> list:
    description = preset["description"]
    if clause:
        if words(clause) > MAX_CLAUSE_WORDS:
            raise ValueError(f"clause longer than {MAX_CLAUSE_WORDS} words")
        description = description + " " + clause

    blocks = scene.get("blocks")
    if not blocks:
        blocks = [{"kind": "paragraph", "text": t}
                  for t in scene["text"].split("\n\n")]
    units = []
    for block in blocks:
        parts = block_parts(block["text"], language)
        for i, (text, sentence_end, _) in enumerate(parts):
            if not sentence_end:
                pause = CLAUSE_PAUSE_MS
            elif i < len(parts) - 1:
                pause = SENTENCE_PAUSE_MS
            elif block.get("kind") == "heading":
                pause = HEADING_PAUSE_MS
            elif block.get("kind") == "line":
                pause = REEL_LINE_PAUSE_MS
            else:
                pause = PARAGRAPH_PAUSE_MS
            units.append({
                "unit_key": f"{scene['scene_id']}-{len(units) + 1:03d}",
                "text": text,
                "description": description,
                "pause_after_ms": pause,
            })
    return units


def unit_boundaries(scene: dict, language: str = "en") -> list:
    """What ends each voice unit of the scene, in voice_units order (the same rules that choose
    its pause_after_ms): "clause" (a part of a split sentence), "sentence" (a sentence inside its
    block), "heading", "line" (a reel line) or "paragraph" (the end of any other block). The
    expressive layer (eav.expressive) reads it; voice_units itself is unchanged."""
    blocks = scene.get("blocks")
    if not blocks:
        blocks = [{"kind": "paragraph", "text": t}
                  for t in scene["text"].split("\n\n")]
    out = []
    for block in blocks:
        parts = block_parts(block["text"], language)
        for i, (_, sentence_end, _) in enumerate(parts):
            if not sentence_end:
                out.append("clause")
            elif i < len(parts) - 1:
                out.append("sentence")
            elif block.get("kind") in ("heading", "line"):
                out.append(block["kind"])
            else:
                out.append("paragraph")
    return out
