"""Earnalism Voice units: sentence-level TTS units with pauses."""
from .text import sentences, words

SENTENCE_PAUSE_MS = 400
PARAGRAPH_PAUSE_MS = 800
HEADING_PAUSE_MS = 1200
REEL_LINE_PAUSE_MS = 400  # Squint pacing between reel lines (block kind "line")
MAX_CLAUSE_WORDS = 12


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
        sents = sentences(block["text"], language)
        for i, s in enumerate(sents):
            if i < len(sents) - 1:
                pause = SENTENCE_PAUSE_MS
            elif block.get("kind") == "heading":
                pause = HEADING_PAUSE_MS
            elif block.get("kind") == "line":
                pause = REEL_LINE_PAUSE_MS
            else:
                pause = PARAGRAPH_PAUSE_MS
            units.append({
                "unit_key": f"{scene['scene_id']}-{len(units) + 1:03d}",
                "text": s,
                "description": description,
                "pause_after_ms": pause,
            })
    return units
