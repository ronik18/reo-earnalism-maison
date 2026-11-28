"""Multi-voice narration casting (owner decision, 28 Nov 2026).

A title opts in with <root>/specs/cast.json (schema eav.cast/1): the narrator's gender, the
characters and their genders, and for every voice unit with speech the unit's text cut into
narrator / character segments that join back to the unit text exactly. Titles without it are
narrated by the single plan voice exactly as before.

Voices come from references/voices.json: two male and two female Indic Parler-TTS speakers the
owner picks from the audition, [primary, secondary] per gender. Per story the narrator takes its
gender's primary (or `narrator_voice: "secondary"` in cast.json, so stories can alternate). A
character never shares the narrator's voice: a character of the narrator's gender takes the other
voice of that gender; a character of the opposite gender takes that gender's primary.

Expressive layer (owner request, 28 Nov 2026; eav.expressive, references/expressive.json): a cast
with the optional `tone` {pace, expressivity, atmosphere, rationale}, `narration_moods`
{unit_key: mood} and `emotion` on every character segment gets composed, emotion-aware
descriptions, punctuation-aware pauses and room tone. A cast without `tone` is unchanged.
"""
import json
from pathlib import Path

from . import expressive

SCHEMA = "eav.cast/1"
VOICES_SCHEMA = "eav.voices/1"
VOICES = Path(__file__).resolve().parents[2] / "references" / "voices.json"
GENDERS = ("male", "female")
SLOTS = ("primary", "secondary")
# Indic Parler-TTS Bengali named speakers (ai4bharat/indic-parler-tts model card).
SPEAKERS = {"male": ("Arjun", "Tapan", "Arnav"), "female": ("Aditi", "Rashmi", "Riya")}
NOT_CHOSEN = "voices not chosen yet — run the audition"


class VoicesNotChosen(ValueError):
    """references/voices.json still holds the placeholder (the owner has not picked)."""


def cast_path(root) -> Path:
    return Path(root) / "specs" / "cast.json"


def validate(cast: dict, title: str, revision: str, sha256: str, units: list) -> list:
    """Every reason the cast does not fit the CURRENT source; [] when it does. units: the title's
    voice units [{unit_key, text}] as job narration builds them now (every film of the plan)."""
    errors = []
    if not isinstance(cast, dict):
        return ["cast.json is not a JSON object"]
    if cast.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    for k, want in (("title", title), ("source_revision", revision), ("source_sha256", sha256)):
        if cast.get(k) != want:
            errors.append(f"{k} is {cast.get(k)!r}, the current source has {want!r}")
    nar = cast.get("narrator") if isinstance(cast.get("narrator"), dict) else {}
    if nar.get("gender") not in GENDERS:
        errors.append("narrator.gender must be male or female")
    if not str(nar.get("rationale") or "").strip():
        errors.append("narrator.rationale is required")
    if cast.get("narrator_voice", "primary") not in SLOTS:
        errors.append("narrator_voice must be \"primary\" or \"secondary\"")
    chars = cast.get("characters") if isinstance(cast.get("characters"), dict) else {}
    for name, c in chars.items():
        if not isinstance(c, dict) or c.get("gender") not in GENDERS:
            errors.append(f"character {name!r}: gender must be male or female")
    text = {u["unit_key"]: u["text"] for u in units}
    tone = "tone" in cast
    if tone:
        errors += expressive.tone_errors(cast["tone"])
    moods = cast.get("narration_moods", {})
    if "narration_moods" in cast and not tone:
        errors.append("narration_moods needs tone (the expressive layer)")
    if not isinstance(moods, dict):
        errors.append("narration_moods must be an object unit_key -> mood")
        moods = {}
    for key, m in moods.items():
        if key not in text:
            errors.append(f"narration_moods {key}: not a voice unit of the current source")
        if m not in expressive.NARRATION_MOODS:
            errors.append(f"narration_moods {key}: {m!r} is not one of "
                          f"{', '.join(expressive.NARRATION_MOODS)} (calm is the default; omit it)")
    if units and len(moods) > expressive.MAX_MOOD_SHARE * len(units):
        errors.append(f"narration_moods covers {len(moods)} of {len(units)} lines; keep it to clear "
                      "departures from calm narration")
    given = cast.get("units")
    if not isinstance(given, dict):
        return errors + ["units must be an object unit_key -> segments"]
    for key, segs in given.items():
        if key not in text:
            errors.append(f"{key}: not a voice unit of the current source")
            continue
        if not isinstance(segs, list) or not segs or not all(isinstance(s, dict) for s in segs):
            errors.append(f"{key}: segments must be a non-empty list of objects")
            continue
        if "".join(str(s.get("text", "")) for s in segs) != text[key]:
            errors.append(f"{key}: segment texts do not join to the unit text exactly")
        roles = []
        for i, s in enumerate(segs):
            r = s.get("role")
            if r not in ("narrator", "character"):
                errors.append(f"{key}[{i}]: role must be narrator or character")
            if r == "character" and s.get("speaker") not in chars:
                errors.append(f"{key}[{i}]: speaker {s.get('speaker')!r} not in characters")
            t = str(s.get("text", ""))
            if not t.strip():
                errors.append(f"{key}[{i}]: empty segment")
            elif not any(ch.isalpha() for ch in t):
                errors.append(f"{key}[{i}]: segment has no letters (attach punctuation to a neighbour)")
            if r == "character" and tone and s.get("emotion") not in expressive.SPEECH_EMOTIONS:
                errors.append(f"{key}[{i}]: a character segment needs emotion, one of "
                              f"{', '.join(expressive.SPEECH_EMOTIONS)}")
            elif "emotion" in s and not tone:
                errors.append(f"{key}[{i}]: emotion needs tone (the expressive layer)")
            elif "emotion" in s and r != "character":
                errors.append(f"{key}[{i}]: narrator segments take their mood from narration_moods, "
                              "not emotion")
            roles.append((r, s.get("speaker") if r == "character" else None))
        for a, b in zip(roles, roles[1:]):
            if a == b:
                errors.append(f"{key}: adjacent segments with the same voice must be merged")
        if roles and all(r == "narrator" for r, _ in roles):
            errors.append(f"{key}: lists only narrator segments; omit the unit instead")
    return errors


def load_voices(path=None) -> dict:
    path = path or VOICES
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != VOICES_SCHEMA:
        raise ValueError(f"{path}: schema must be {VOICES_SCHEMA}")
    return data


def audition_description(voices: dict, speaker: str) -> str:
    """The template description for any of the six speakers (the audition reads every one)."""
    if speaker not in voices["speakers"]["male"] + voices["speakers"]["female"]:
        raise ValueError(f"{speaker!r} is not a listed speaker")
    return voices["description_template"].format(speaker=speaker)


def chosen(voices: dict) -> dict:
    """gender -> [primary, secondary] as {speaker, description}; VoicesNotChosen until the owner
    has picked, ValueError for a choice that breaks the rules."""
    if voices.get("status") != "chosen" or not voices.get("male") or not voices.get("female"):
        raise VoicesNotChosen(NOT_CHOSEN)
    out = {}
    for g in GENDERS:
        pair = voices.get(g)
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(v, dict) for v in pair):
            raise ValueError(f"voices.json {g} must be [primary, secondary]")
        names = [v.get("speaker") for v in pair]
        if len(set(names)) != 2 or not all(n in voices["speakers"][g] for n in names):
            raise ValueError(f"voices.json {g} must be two different {g} speakers from "
                             f"{', '.join(voices['speakers'][g])}")
        for v in pair:
            d = v.get("description")
            if not isinstance(d, str) or not d.startswith(v["speaker"] + " "):
                raise ValueError(f"voices.json {g} {v['speaker']}: the description must start "
                                 "with the speaker's name")
        out[g] = [{"speaker": v["speaker"], "description": v["description"]} for v in pair]
    return out


def resolve(cast: dict, voices: dict) -> dict:
    """The voice of the narrator and of every character for this story."""
    pairs = chosen(voices)
    g = cast["narrator"]["gender"]
    slot = SLOTS.index(cast.get("narrator_voice", "primary"))
    narrator = {"gender": g, "slot": SLOTS[slot], **pairs[g][slot]}
    characters = {}
    for name, c in cast["characters"].items():
        cg = c["gender"]
        i = 1 - slot if cg == g else 0  # never the narrator's voice
        characters[name] = {"gender": cg, "slot": SLOTS[i], **pairs[cg][i]}
    return {"narrator": narrator, "characters": characters}


def job_cast(cast: dict, voices: dict, cast_sha256: str, table=None) -> dict:
    """What job narration carries (spec["cast"]): the resolved voices and the segments of every
    cast unit with each segment's voice and description. With `tone` (the expressive layer) every
    description is composed by eav.expressive from the table (references/expressive.json): a
    narrator segment from its unit's narration mood (calm by default), a character segment from
    its emotion; spec["cast"]["expressive"] then carries the tone, the moods, the narrator's
    description per mood and the table the pauses and room tone come from."""
    who = resolve(cast, voices)
    tone = cast.get("tone")
    if tone is not None:
        # the reviewed file (its sha256 recorded), or a table given directly (its JSON digest)
        digest = expressive.table_sha256() if table is None else _table_digest(table)
        table = table or expressive.load()
        moods = dict(cast.get("narration_moods") or {})
    segments = {}
    for key, segs in cast["units"].items():
        rows = []
        for s in segs:
            v = who["narrator"] if s["role"] == "narrator" else who["characters"][s["speaker"]]
            row = {"text": s["text"], "role": s["role"],
                   "speaker": s.get("speaker") if s["role"] == "character" else None,
                   "voice": v["speaker"], "description": v["description"]}
            if tone is not None:
                if s["role"] == "narrator":
                    row["mood"] = moods.get(key, expressive.CALM)
                    row["description"] = expressive.describe(table, v["speaker"], tone, "narrator",
                                                             row["mood"])
                else:
                    row["emotion"] = s.get("emotion") or "conversation"
                    row["description"] = expressive.describe(table, v["speaker"], tone, "character",
                                                             row["emotion"])
            rows.append(row)
        segments[key] = rows
    out = {"cast_sha256": cast_sha256, "narrator": who["narrator"],
           "characters": who["characters"], "segments": segments}
    if tone is not None:
        name = who["narrator"]["speaker"]
        out["expressive"] = {
            "table_sha256": digest, "tone": dict(tone), "narration_moods": moods, "table": table,
            "narrator_descriptions": {m: expressive.describe(table, name, tone, "narrator", m)
                                      for m in (expressive.CALM,) + expressive.NARRATION_MOODS}}
    return out


def _table_digest(table: dict) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(table, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def summary(job_cast_: dict) -> dict:
    """The job.json / provenance record of the cast (no descriptions repeated)."""
    out = {"cast_sha256": job_cast_["cast_sha256"],
           "narrator": {k: job_cast_["narrator"][k] for k in ("gender", "slot", "speaker")},
           "characters": {n: v["speaker"] for n, v in sorted(job_cast_["characters"].items())}}
    ex = job_cast_.get("expressive")
    if ex:
        out["expressive"] = {"table_sha256": ex["table_sha256"], "tone": ex["tone"],
                             "narration_moods": len(ex["narration_moods"]),
                             "room_tone": expressive.room_settings(ex["table"])}
    return out


def apply(units: list, job_cast_: dict, clause=None, boundaries=None) -> list:
    """Voice units with the cast applied: every unit gets the narrator's description and voice;
    a cast unit also gets its segments. The optional direction clause is appended to every
    description as voice_units appends it to the preset. With the expressive layer the narrator's
    description follows the unit's narration mood, and every unit gets its pause from the table
    (boundaries: [(boundary, scene_end)] per unit, required), its pause_rule and room_tone."""
    def direct(d):
        return d + " " + clause if clause else d
    ex = job_cast_.get("expressive")
    out = []
    for u in units:
        nd = (ex["narrator_descriptions"][ex["narration_moods"].get(u["unit_key"], expressive.CALM)]
              if ex else job_cast_["narrator"]["description"])
        u = dict(u, description=direct(nd), voice=job_cast_["narrator"]["speaker"])
        if ex:
            u["mood"] = ex["narration_moods"].get(u["unit_key"], expressive.CALM)
        segs = job_cast_["segments"].get(u["unit_key"])
        if segs:
            if "".join(s["text"] for s in segs) != u["text"]:
                raise ValueError(f"{u['unit_key']}: cast segments do not join to the unit text")
            u["segments"] = [dict(s, description=direct(s["description"])) for s in segs]
        out.append(u)
    if ex:
        if boundaries is None:
            raise ValueError("the expressive layer needs each unit's boundary (eav.voice.unit_boundaries)")
        out = expressive.apply_pauses(out, boundaries, ex["table"])
    return out


AUDITION_PASSAGES = ("narration", "male-line", "female-line")


def audition_passages(cast: dict, units: list) -> list:
    """Three short passages of the real story for the audition, in source order: the first
    narration-only unit of 60-160 characters, and the first male and the first female character
    line of 20-160 characters (else the longest one of that gender)."""
    def fits(t, lo):
        return lo <= len(t) <= 160 and any(c.isalpha() for c in t)
    order = [u["unit_key"] for u in units]
    narration = next((u for u in units if u["unit_key"] not in cast["units"]
                      and fits(u["text"].strip(), 60)), None)
    out = []
    if narration is None:
        segs = [(k, s["text"].strip()) for k in order for s in cast["units"].get(k, [])
                if s["role"] == "narrator" and len(s["text"].strip()) <= 160]
        if not segs:
            raise ValueError("the source has no narration passage of at most 160 characters")
        k, t = max(segs, key=lambda x: len(x[1]))
        out.append({"passage": "narration", "unit_key": k, "text": t})
    else:
        out.append({"passage": "narration", "unit_key": narration["unit_key"],
                    "text": narration["text"].strip()})
    for g in GENDERS:
        lines = [(k, s["speaker"], s["text"].strip()) for k in order
                 for s in cast["units"].get(k, []) if s["role"] == "character"
                 and cast["characters"][s["speaker"]]["gender"] == g
                 and len(s["text"].strip()) <= 160 and any(c.isalpha() for c in s["text"])]
        if not lines:
            raise ValueError(f"the cast has no {g} line of dialogue of at most 160 characters; "
                             "audition from another title's cast")
        k, who, t = next((x for x in lines if fits(x[2], 20)), max(lines, key=lambda x: len(x[2])))
        out.append({"passage": f"{g}-line", "unit_key": k, "speaker": who, "text": t})
    return out


def audition_units(voices: dict, passages: list) -> list:
    """Every Bengali speaker reads every passage: unit <speaker>-<passage> (e.g. arjun-male-line),
    each with the template description of that speaker."""
    rows = []
    for g in GENDERS:
        for speaker in voices["speakers"][g]:
            for p in passages:
                rows.append({"unit_key": f"{speaker.lower()}-{p['passage']}", "text": p["text"],
                             "description": audition_description(voices, speaker),
                             "pause_after_ms": 400, "voice": speaker})
    return rows


def pieces(units: list) -> int:
    """Parler generations a narration job makes: one per segment, else one per unit."""
    return sum(len(u.get("segments") or [None]) for u in units)


STYLE_MOODS = ("sad", "fear")  # the narration mood the style audition prefers to show


def style_audition(cast: dict, units: list, voices: dict, table=None) -> tuple:
    """(passages, rows) of the expressive-layer audition (`audition --style-audition`): four of the
    story's own lines in its chosen voices with their composed descriptions: a calm narration
    line, a narration line with a mood (sad or fear preferred), and two character lines with
    different emotions (a non-default emotion first). Unit keys <voice>-style-<passage>."""
    if "tone" not in cast:
        raise ValueError("the cast has no tone: the style audition is for an expressive cast "
                         "(tone, narration_moods, character emotions)")
    jc = job_cast(cast, voices, "", table)
    ex = jc["expressive"]
    moods = ex["narration_moods"]

    def fits(t, lo=20):
        return lo <= len(t) <= 160 and any(c.isalpha() for c in t)
    plain = [u for u in units if u["unit_key"] not in cast["units"]]
    narrator = jc["narrator"]["speaker"]
    out = []
    calm = next((u for u in plain if u["unit_key"] not in moods and fits(u["text"].strip(), 60)),
                None) or next((u for u in plain if u["unit_key"] not in moods
                               and fits(u["text"].strip())), None)
    if calm is None:
        raise ValueError("the story has no calm narration line of 20-160 characters")
    out.append({"passage": "style-calm", "unit_key": calm["unit_key"], "text": calm["text"].strip(),
                "role": "narrator", "mood": expressive.CALM, "voice": narrator,
                "description": ex["narrator_descriptions"][expressive.CALM]})
    lines = [(u["unit_key"], u["text"].strip()) for u in plain if u["unit_key"] in moods]
    lines += [(k, s["text"].strip()) for k in (u["unit_key"] for u in units)
              for s in jc["segments"].get(k, []) if k in moods and s["role"] == "narrator"]
    lines = [x for x in lines if fits(x[1])]
    pick = next((x for m in STYLE_MOODS for x in lines if moods[x[0]] == m), None) \
        or (lines[0] if lines else None)
    if pick is None:
        raise ValueError("the cast marks no narration mood on a line of 20-160 characters")
    m = moods[pick[0]]
    out.append({"passage": f"style-{m}", "unit_key": pick[0], "text": pick[1], "role": "narrator",
                "mood": m, "voice": narrator, "description": ex["narrator_descriptions"][m]})
    speech = [(k, s) for k in (u["unit_key"] for u in units) for s in jc["segments"].get(k, [])
              if s["role"] == "character" and fits(s["text"].strip())]
    first = next((x for x in speech if x[1]["emotion"] not in ("conversation", "neutral")),
                 speech[0] if speech else None)
    second = first and next((x for x in speech if x[1]["emotion"] != first[1]["emotion"]), None)
    if not second:
        raise ValueError("the cast has no two character lines of 20-160 characters with different "
                         "emotions")
    for k, s in (first, second):
        out.append({"passage": f"style-line-{s['emotion']}", "unit_key": k, "text": s["text"].strip(),
                    "role": "character", "speaker": s["speaker"], "emotion": s["emotion"],
                    "voice": s["voice"], "description": s["description"]})
    rows = [{"unit_key": f"{p['voice'].lower()}-{p['passage']}", "text": p["text"],
             "description": p["description"], "pause_after_ms": 400, "voice": p["voice"]}
            for p in out]
    return out, rows
