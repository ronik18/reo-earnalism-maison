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


def _split_points(text: str):
    """Indices of the spaces a unit may be split at: after clause punctuation, then any space."""
    spaces = [i for i, c in enumerate(text) if c == " "]
    clause = [i for i in spaces if text[:i].rstrip(_CLOSERS)[-1:] in tuple(CLAUSE_MARKS)]
    return clause, spaces


def split_unit(text: str, limit: int = MAX_UNIT_CHARS) -> list:
    """Split a sentence into parts of at most `limit` characters, never inside a word.

    Prefers clause punctuation, then whitespace; picks the split point closest to the middle that
    leaves both parts within the limit, else the one closest to the middle, and recurses. Joining
    the parts with single spaces reproduces the whitespace-normalised text exactly.
    """
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text] if text else []
    middle = len(text) / 2
    tiers = _split_points(text)
    if not tiers[1]:
        raise ValueError(f"a {len(text)}-character run has no space to split at; it cannot fit "
                         f"the {limit}-character voice-unit limit: {text[:40]!r}...")
    for tier in tiers:
        fits = [i for i in tier if i <= limit and len(text) - i - 1 <= limit]
        if fits:
            i = min(fits, key=lambda k: abs(k - middle))
            return [text[:i], text[i + 1:]]
    i = min(tiers[0] or tiers[1], key=lambda k: abs(k - middle))
    return split_unit(text[:i], limit) + split_unit(text[i + 1:], limit)


def block_parts(text: str, language: str = "en") -> list:
    """[(unit text, ends its sentence)] for one block, in order."""
    out = []
    for s in sentences(text, language):
        parts = split_unit(s)
        out += [(p, k == len(parts) - 1) for k, p in enumerate(parts)]
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
        for i, (text, sentence_end) in enumerate(parts):
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
