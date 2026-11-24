"""Earnalism Voice units: TTS units with pauses, and (opt-in) the storyteller style.

Default style (style=None): one unit per sentence, the preset description byte-for-byte, fixed
400/800/1200 ms pauses. Every job built before 2026-11-24 used it and keeps it.

Storyteller style (owner 2026-11-24, "the voiceover seems mechanical"), each part opt-in:
  group  -- consecutive short sentences of one paragraph and one speaker turn become one unit
            (<= MAX_GROUP_WORDS words, <= MAX_GROUP_SECONDS estimated), so Parler carries one
            intonation contour across them instead of resetting at every full stop. Never across
            paragraphs, headings, reel lines or a turn between narration and quoted speech, and a
            sentence is never split. The unit texts joined by one space are exactly the source.
  pauses -- punctuation- and turn-aware pauses after paragraph units (question/exclamation,
            ellipsis/dash, dialogue turn, paragraph, scene end). Reel lines keep 400 ms.
  direct -- each unit's description is the preset plus "<Speaker> speaks in a <emotion> tone."
            (Indic Parler-TTS emotion words), then one optional clause of <= 12 words. Default
            emotion: Conversation for quoted speech, Narration otherwise; a directions map
            {unit_key: {"emotion", "clause"}} written from the context map overrides it.

Continuous-take style (owner 2026-11-24, ElevenLabs narration; eav.take, `import-take`):
  continuous -- one Eleven v3 take per scene (per reel) sliced at its own silences, so every
            sentence unit already carries its natural pause. The units are the default sentence
            units (never grouped); no pause is added inside a scene or between reel lines, and
            only TAKE_SCENE_PAUSE_MS after a film scene's last unit. Excludes the other modes.
"""
from .text import estimate_seconds, sentences, words

SENTENCE_PAUSE_MS = 400
PARAGRAPH_PAUSE_MS = 800
HEADING_PAUSE_MS = 1200
REEL_LINE_PAUSE_MS = 400  # Squint pacing between reel lines (block kind "line")
MAX_CLAUSE_WORDS = 12

# Storyteller style
STYLE_KEYS = ("group", "pauses", "direct", "continuous")
EXPRESSIVE = {"group": True, "pauses": True, "direct": True}
CONTINUOUS = {"continuous": True}
TAKE_SCENE_PAUSE_MS = 1200  # between two scene takes of a film (continuous style)
MAX_GROUP_WORDS = 28
MAX_GROUP_SECONDS = 18.0
GROUP_WPM = 100  # conservative speaking rate for the length cap (Bengali words are long)
QUESTION_PAUSE_MS = 550      # after ? or !
DIALOGUE_TURN_PAUSE_MS = 600  # between narration and quoted speech, or two speeches
SUSPENSE_PAUSE_MS = 700      # after an ellipsis or a dash: the held breath
SCENE_PAUSE_MS = 1500        # after the last unit of a scene
# Emotion words Indic Parler-TTS was trained with (model card ai4bharat/indic-parler-tts).
EMOTIONS = ("Command", "Anger", "Narration", "Conversation", "Disgust", "Fear", "Happy",
            "Neutral", "News", "Sad", "Surprise")
DIRECTION_KEYS = ("emotion", "clause")

_OPEN_Q = ("“", '"', "«", "‘")
_CLOSE_Q = ("”", '"', "»", "’")
_DOUBLE_Q = ("“", "”", '"', "«", "»")
_TRAIL = "”’\"')» "


def _style(style) -> dict:
    if not style:
        return {}
    if not isinstance(style, dict):
        raise ValueError("voice style must be an object")
    unknown = sorted(set(style) - set(STYLE_KEYS))
    if unknown:
        raise ValueError(f"unknown voice style key(s): {', '.join(unknown)}")
    if any(not isinstance(v, bool) for v in style.values()):
        raise ValueError("voice style values must be true or false")
    on = {k: v for k, v in style.items() if v}
    if on.get("continuous") and len(on) > 1:
        raise ValueError("the continuous-take style (imported ElevenLabs takes) excludes group, "
                         "pauses and direct")
    return on


def _dialogue(text: str) -> bool:
    return any(q in text for q in _DOUBLE_Q) or text.startswith("‘")


def _turn_break(prev: str, cur: str) -> bool:
    """A change of speaker turn between two adjacent sentences of one paragraph."""
    if _dialogue(prev) != _dialogue(cur):
        return True
    return prev.rstrip().endswith(_CLOSE_Q) or cur.lstrip().startswith(_OPEN_Q)


def _fits(texts: list, language: str) -> bool:
    joined = " ".join(texts)
    return (words(joined) <= MAX_GROUP_WORDS
            and estimate_seconds(joined, language, GROUP_WPM) <= MAX_GROUP_SECONDS)


def _groups(sents: list, language: str, group: bool) -> list:
    if not group:
        return [[s] for s in sents]
    out = []
    for s in sents:
        if out and not _turn_break(out[-1][-1], s) and _fits(out[-1] + [s], language):
            out[-1].append(s)
        else:
            out.append([s])
    return out


def _ending(text: str) -> str:
    return text.rstrip(_TRAIL)


def _segments(scene: dict, language: str, style: dict) -> list:
    """[(block, text, pause_after_ms)] for every unit of the scene, in order."""
    blocks = scene.get("blocks")
    if not blocks:
        blocks = [{"kind": "paragraph", "text": t} for t in scene["text"].split("\n\n")]
    segs = []
    for block in blocks:
        kind = block.get("kind")
        sents = sentences(block["text"], language)
        groups = _groups(sents, language, style.get("group") and kind == "paragraph")
        for i, g in enumerate(groups):
            text = " ".join(g)
            last = i == len(groups) - 1
            if not last:
                pause = SENTENCE_PAUSE_MS
            elif kind == "heading":
                pause = HEADING_PAUSE_MS
            elif kind == "line":
                pause = REEL_LINE_PAUSE_MS
            else:
                pause = PARAGRAPH_PAUSE_MS
            if style.get("pauses") and kind == "paragraph":
                end = _ending(text)
                if end.endswith(("?", "!")):
                    pause = max(pause, QUESTION_PAUSE_MS)
                if end.endswith(("...", "…", "—", "–", "-")):
                    pause = max(pause, SUSPENSE_PAUSE_MS)
                if not last and _turn_break(g[-1], groups[i + 1][0]):
                    pause = max(pause, DIALOGUE_TURN_PAUSE_MS)
            segs.append((block, text, pause))
    if style.get("continuous"):  # the take holds its own pauses; only a film scene end is added
        return [(block, text, TAKE_SCENE_PAUSE_MS if i == len(segs) - 1 and block.get("kind") != "line"
                 else 0) for i, (block, text, _) in enumerate(segs)]
    if style.get("pauses") and segs and segs[-1][0].get("kind") == "paragraph":
        block, text, pause = segs[-1]
        segs[-1] = (block, text, max(pause, SCENE_PAUSE_MS))
    return segs


def _check_clause(clause, where="clause"):
    if not isinstance(clause, str) or not clause.strip():
        raise ValueError(f"{where} must be non-empty text")
    if words(clause) > MAX_CLAUSE_WORDS:
        raise ValueError(f"{where} longer than {MAX_CLAUSE_WORDS} words")


def _emotion(value) -> str:
    match = next((e for e in EMOTIONS if isinstance(value, str) and value.strip().lower() == e.lower()),
                 None)
    if match is None:
        raise ValueError(f"emotion {value!r} is not one of the model's emotion words: "
                         + ", ".join(EMOTIONS))
    return match


def validate_directions(directions, units: list) -> None:
    """Refuse unknown unit keys, unknown emotions, clauses over 12 words and any other field."""
    if not isinstance(directions, dict):
        raise ValueError("directions must be an object {unit_key: {emotion, clause}}")
    known = {u["unit_key"] for u in units}
    for key, d in directions.items():
        if key not in known:
            raise ValueError(f"direction for unknown unit {key!r} (list this job's units first)")
        if not isinstance(d, dict) or "emotion" not in d:
            raise ValueError(f"direction {key!r} needs an emotion")
        extra = sorted(set(d) - set(DIRECTION_KEYS))
        if extra:
            raise ValueError(f"direction {key!r} has unsupported field(s) {', '.join(extra)}; Parler "
                             "takes an emotion word and one short clause only")
        _emotion(d["emotion"])
        if "clause" in d:
            _check_clause(d["clause"], f"direction {key!r} clause")


def speaker_name(preset: dict) -> str:
    name = preset.get("speaker")
    if name:
        return name
    first = (preset.get("description") or "").split()
    return first[0].rstrip(",.'’s") if first else "The narrator"


def voice_units(scene: dict, preset: dict, clause=None, language: str = "en", style=None,
                directions=None) -> list:
    style = _style(style)
    description = preset["description"]
    if clause:
        _check_clause(clause)
    if directions is not None and not style.get("direct"):
        raise ValueError("directions need the direction mode (--expressive)")
    directions = directions or {}

    units = []
    for block, text, pause in _segments(scene, language, style):
        key = f"{scene['scene_id']}-{len(units) + 1:03d}"
        if style.get("direct"):
            d = directions.get(key) or {}
            emotion = _emotion(d["emotion"]) if d else (
                "Conversation" if _dialogue(text) else "Narration")
            desc = f"{description} {speaker_name(preset)} speaks in a {emotion.lower()} tone."
            extra = d.get("clause") or clause
            if extra:
                _check_clause(extra)
                desc += " " + extra
        else:
            desc = description + " " + clause if clause else description
        units.append({"unit_key": key, "text": text, "description": desc, "pause_after_ms": pause})
    return units


def unit_anchors(scene: dict, language: str = "en", style=None) -> list:
    """The anchor_id of the block each unit comes from (units never cross blocks)."""
    return [block.get("anchor_id") for block, _, _ in _segments(scene, language, _style(style))]


AUDITION_PASSAGES = ("narration", "dialogue", "emotional")
MAX_AUDITION_WORDS = 80


def audition_units(passages: dict, variants: list, language: str, directions=None) -> list:
    """The same passages in every variant: unit_key = <variant>__<passage>-NNN.

    variants: [(name, preset, style)]; a variant with style None renders as production does today
    (the control). Directions are keyed by the passage unit key (e.g. emotional-001) and apply to
    every variant in the direction mode."""
    if not isinstance(passages, dict) or sorted(passages) != sorted(AUDITION_PASSAGES):
        raise ValueError("an audition needs exactly the passages " + ", ".join(AUDITION_PASSAGES))
    for key, text in passages.items():
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"audition passage {key!r} is empty")
        if words(text) > MAX_AUDITION_WORDS:
            raise ValueError(f"audition passage {key!r} is over {MAX_AUDITION_WORDS} words; keep it short")
    names = [n for n, _, _ in variants]
    if len(set(names)) != len(names) or any("__" in n for n in names):
        raise ValueError("audition variant names must be unique and contain no '__'")
    scenes = [{"scene_id": key, "text": passages[key]} for key in AUDITION_PASSAGES]
    if directions:
        validate_directions(directions, [u for sc in scenes for u in
                                         voice_units(sc, {"description": ""}, None, language, EXPRESSIVE)])
    units = []
    for name, preset, style in variants:
        for sc in scenes:
            direct = _style(style).get("direct")
            for u in voice_units(sc, preset, None, language, style,
                                 directions if direct and directions else None):
                units.append(dict(u, unit_key=f"{name}__{u['unit_key']}"))
    return units
