"""Expressive narration layer (owner request, 28 Nov 2026): emotion-aware Parler descriptions,
punctuation- and structure-aware pauses, and room tone instead of digital silence.

It applies only to a title whose specs/cast.json carries `tone` (eav.cast/1 optional fields:
`tone`, `narration_moods`, and `emotion` on character segments). Every other title, with or without
a cast file, is narrated exactly as before. All wording, pause lengths and room-tone settings are
data in references/expressive.json; this module only composes them, deterministically.
"""
import hashlib
import json
import unicodedata
from pathlib import Path

SCHEMA = "eav.expressive/1"
TABLE = Path(__file__).resolve().parents[2] / "references" / "expressive.json"
PACES = ("slow", "moderate")
EXPRESSIVITIES = ("slightly expressive", "expressive")
# Indic Parler-TTS Bengali emotion prompts (model card), plus "conversation" as the speech default.
SPEECH_EMOTIONS = ("conversation", "happy", "sad", "anger", "fear", "surprise", "disgust",
                   "command", "neutral")
NARRATION_MOODS = ("happy", "sad", "anger", "fear", "surprise", "disgust")  # calm is the default
CALM = "calm"
MAX_MOOD_SHARE = 0.4  # narration_moods marks clear departures only
TONE_KEYS = ("pace", "expressivity", "atmosphere", "rationale")


def load(path=None) -> dict:
    path = Path(path or TABLE)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema must be {SCHEMA}")
    missing = [m for m in (CALM,) + NARRATION_MOODS if m not in data["narration_moods"]]
    missing += [e for e in SPEECH_EMOTIONS if e not in data["speech_emotions"]]
    if missing:
        raise ValueError(f"{path}: no phrase for {', '.join(missing)}")
    return data


def table_sha256(path=None) -> str:
    return hashlib.sha256(Path(path or TABLE).read_bytes()).hexdigest()


def tone_errors(tone) -> list:
    """Why a cast.json `tone` is not usable; [] when it is."""
    if not isinstance(tone, dict):
        return ["tone must be an object {pace, expressivity, atmosphere, rationale}"]
    errors = []
    if tone.get("pace") not in PACES:
        errors.append("tone.pace must be slow or moderate")
    if tone.get("expressivity") not in EXPRESSIVITIES:
        errors.append("tone.expressivity must be 'slightly expressive' or 'expressive'")
    atm = tone.get("atmosphere")
    if not isinstance(atm, str) or not 2 <= len(atm.split()) <= 6 or not atm.isascii() \
            or any(c in atm for c in "{}\n"):
        errors.append("tone.atmosphere must be 2-6 English words")
    if not str(tone.get("rationale") or "").strip():
        errors.append("tone.rationale is required")
    extra = sorted(set(tone) - set(TONE_KEYS))
    if extra:
        errors.append(f"tone has unexpected keys: {', '.join(extra)}")
    return errors


def describe(table: dict, speaker: str, tone: dict, role: str, emotion=None) -> str:
    """The Parler description of one line. role "narrator": emotion is the narration mood (None or
    "calm" = calm storytelling); role "character": emotion is the speech emotion (None =
    "conversation"). Only pace, expressivity, atmosphere and the mood/emotion phrase vary; the
    quality clause is the approved wording unchanged. Starts with the speaker's name."""
    if role == "narrator":
        entry = table["narration_moods"][emotion or CALM]
        template = table["narrator_template"]
    elif role == "character":
        entry = table["speech_emotions"][emotion or "conversation"]
        template = table["character_template"]
    else:
        raise ValueError(f"role must be narrator or character, not {role!r}")
    text = template.format(
        speaker=speaker, atmosphere=" ".join(tone["atmosphere"].split()),
        expressivity=entry.get("expressivity") or tone["expressivity"],
        pace=entry.get("pace") or tone["pace"],
        mood=entry["phrase"], emotion=entry["phrase"], quality=table["quality_clause"])
    return " ".join(text.split())


def unit_seed(key: str, salt: str = "") -> int:
    """A stable 32-bit seed from a unit key (sha256), for jitter and room tone."""
    return int(hashlib.sha256((salt + key).encode("utf-8")).hexdigest()[:8], 16)


def jitter(key: str, fraction: float) -> float:
    """A deterministic factor in [-fraction, +fraction] seeded by the unit key."""
    return (unit_seed(key, "pause:") / 0xFFFFFFFF * 2 - 1) * fraction


def _closing(text: str, closers: str) -> str:
    t = text.rstrip()
    while t and t[-1] in closers:
        t = t[:-1].rstrip()
    return t


def sentence_rule(text: str, p: dict):
    """(rule, ms) of a sentence end by its last mark (closing quotes/brackets set aside)."""
    t = _closing(text, p["closers"])
    if any(t.endswith(m) for m in p["trailing_marks"]):
        return "trailing", p["trailing_ms"]
    if t and t[-1] in p["question_exclaim_marks"]:
        return "question_exclaim", p["question_exclaim_ms"]
    return "sentence", p["sentence_ms"]


def pause_rule(text: str, boundary: str, scene_end: bool, voice_change: bool, key: str,
               p: dict) -> dict:
    """The pause after one unit: {"ms", "rule", "base_ms", "dialogue_ms", "jitter"}."""
    candidates = []
    if boundary == "clause":
        candidates.append(("clause", p["clause_ms"]))
    else:
        candidates.append(sentence_rule(text, p))
        if boundary in ("paragraph", "line"):
            candidates.append(("paragraph", p["paragraph_ms"]))
        if boundary == "heading":
            candidates.append(("heading", p["heading_ms"]))
    if scene_end:
        candidates.append(("scene", p["scene_ms"]))
    rule, base = max(candidates, key=lambda c: c[1])
    extra = p["dialogue_extra_ms"] if voice_change else 0
    j = jitter(key, p["jitter_fraction"])
    return {"ms": int(round((base + extra) * (1 + j))), "rule": rule + ("+dialogue" if extra else ""),
            "base_ms": base, "dialogue_ms": extra, "jitter": round(j, 4)}


def _punct(ch: str) -> bool:
    """A punctuation mark (danda, comma, quote, dash...); never a Bengali vowel sign or letter."""
    return bool(ch) and unicodedata.category(ch).startswith("P")


def segment_gaps(segments: list, table: dict) -> list:
    """The room-tone gap (ms) between each pair of a joined unit's segments."""
    g = table["segment_gaps"]
    out = []
    for a, b in zip(segments, segments[1:]):
        left, right = a["text"].rstrip(), b["text"].lstrip()
        punct = _punct(left[-1:]) or _punct(right[:1])
        out.append(g["punctuated_ms"] if punct else g["unpunctuated_ms"])
    return out


def room_settings(table: dict) -> dict:
    r = table["room_tone"]
    return {"method": r["method"], "dbfs": float(r["dbfs"]), "fade_ms": r["fade_ms"],
            "smooth_ms": r["smooth_ms"]}


def _voice_at(unit: dict, end: bool):
    segs = unit.get("segments")
    if not segs:
        return ("narrator", None)
    s = segs[-1] if end else segs[0]
    return (s["role"], s.get("speaker"))


def apply_pauses(units: list, boundaries: list, table: dict) -> list:
    """Units (already carrying their cast segments) with pause_after_ms and pause_rule from the
    table; boundaries: [(boundary, scene_end)] per unit (eav.voice.unit_boundaries). A joined
    unit also gets segment_gaps_ms; every unit gets room_tone (its own seed)."""
    if len(boundaries) != len(units):
        raise ValueError("one boundary per voice unit is required")
    p = table["pauses"]
    room = room_settings(table)
    out = []
    for i, (u, (boundary, scene_end)) in enumerate(zip(units, boundaries)):
        nxt = units[i + 1] if i + 1 < len(units) else None
        change = nxt is not None and _voice_at(u, True) != _voice_at(nxt, False)
        rule = pause_rule(u["text"], boundary, scene_end, change, u["unit_key"], p)
        u = dict(u, pause_after_ms=rule["ms"], pause_rule=rule,
                 room_tone={**room, "seed": unit_seed(u["unit_key"], "room:")})
        if u.get("segments"):
            u["segment_gaps_ms"] = segment_gaps(u["segments"], table)
        out.append(u)
    return out


def gap_seed(key: str) -> int:
    """The room-tone seed of the pause after unit `key` in an assembled track."""
    return unit_seed(key, "gap:")
