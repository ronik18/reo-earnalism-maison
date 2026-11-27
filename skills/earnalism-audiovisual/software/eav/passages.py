"""Eleven v4 narration in passages: split a scene, check each passage's script, join the retimed takes.

The operator generates one take per passage of 15-30 s (`split_passages` cuts only at sentence or paragraph
ends and never alters a character, so the passages concatenated are the scene text). `check_passage_scripts`
holds the tagged scripts to the voice rules: the words are the book's, at most one audio tag per sentence,
no passage opens on a bare `[softly]`, and a mood tag still in force at the end of a passage is carried
into the next one. After `retime` and `voicecheck` of each passage, `join_passages` builds the scene wav:
each seam is the take's own room tone (never digital zero) joined by 10 ms equal-power crossfades.
Needs numpy and ffmpeg (through eav.retime).
"""
import re
from pathlib import Path

import numpy as np

from . import retime
from .retime import SR
from .take import TAG, strip_tags
from .text import sentences

# Narration rate, characters per second (spaces counted, tags not): about 120 words/min (the plan's default
# narration rate) at ~6.5 characters per Bengali word with its space. A documented estimate, not a measurement:
# no measured v4 take exists in the record yet; pass `cps` (CLI `--cps`) from the first real takes.
CPS_BN = 13.0
MIN_S, MAX_S = 15.0, 30.0
SEAM_S = 0.9            # room tone between two passages: the middle of the sentence pause (0.8-1.0 s)
XF_S = 0.010            # crossfade at each join
EDGE_KEEP_S = 0.020     # take edge kept beyond the last/first audible sample at a seam (2 x the crossfade)
EDGE_DB = -50.0         # below this a sample is take edge silence, not speech
PAUSE_TAGS = {"pause", "short pause", "long pause"}   # tags that do not set a mood
_BREAK = re.compile(r"[.?!।][\"'”’)]*\s+|\n[ \t]*\n\s*")
_END = re.compile(r"[.?!।][\"'”’)]*$")


def _chunks(text: str) -> list[tuple[str, bool]]:
    """(chunk, ends_paragraph): sentences with their trailing whitespace, so the chunks join back to text."""
    out, pos = [], 0
    for m in _BREAK.finditer(text):
        out.append((text[pos:m.end()], "\n" in m.group() and m.group().count("\n") >= 2))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], True))
    return out


def split_passages(scene_text: str, cps: float = CPS_BN, min_s: float = MIN_S, max_s: float = MAX_S) -> list[str]:
    """Passages of min_s..max_s seconds (length estimated at `cps` characters/second), cut only at a sentence
    or paragraph end; a paragraph end closes a passage that already holds min_s. A single sentence longer than
    max_s stays one passage. Passages keep their whitespace: "".join(split_passages(t)) == t. A scene (or
    tail) shorter than min_s stays as it is, after moving whole sentences from the passage before it when
    that keeps both within range."""
    def secs(chunks):
        return len("".join(c for c, _ in chunks).strip()) / cps

    groups: list[list[tuple[str, bool]]] = []
    cur: list[tuple[str, bool]] = []
    for ch in _chunks(scene_text):
        if cur and secs(cur) >= min_s and secs(cur + [ch]) > max_s:
            groups.append(cur)
            cur = []
        cur.append(ch)
        if secs(cur) >= min_s and ch[1]:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    while len(groups) > 1 and secs(groups[-1]) < min_s:
        prev, last = groups[-2], groups[-1]
        if len(prev) > 1 and secs(prev[:-1]) >= min_s and secs([prev[-1]] + last) <= max_s:
            groups[-1] = [prev.pop()] + last
        elif secs(prev + last) <= max_s:
            groups[-2:] = [prev + last]
        else:
            break
    return ["".join(c for c, _ in g) for g in groups]


def _norm(t: str) -> str:
    return " ".join((t or "").split())


def _mood(tag: str) -> str | None:
    name = tag.strip("[] ").lower()
    return None if name in PAUSE_TAGS else name


def check_passage_scripts(scene_text: str, tagged: list[str]) -> list[str]:
    """Check the tagged scripts of a scene's passages, in order; return each passage's plain text.

    Refused (ValueError naming the passage): words that are not the scene text's in order and in full (tags
    may only be inserted between words); a passage other than the last that does not end at a sentence end;
    more than one audio tag in a sentence; a passage opening on `[softly]` that is not the mood carried over
    from the passage before (the voice rules: never open on a bare [softly]); a passage that opens on words
    or a pause tag after one that ended in a mood tag (the mood is carried across the join by repeating the
    tag at the start; a different mood tag there is a deliberate change). A [pause] tag sets no mood."""
    rest = _norm(scene_text)
    if not rest:
        raise ValueError("the scene has no text")
    if not tagged:
        raise ValueError("no passage scripts")
    plain, carried = [], None
    for i, script in enumerate(tagged, 1):
        who = f"passage {i}"
        if any(not t.strip("[] ") for t in TAG.findall(script)):
            raise ValueError(f"{who}: empty audio tag []")
        text = strip_tags(script, rest)
        if not text:
            raise ValueError(f"{who} has no words")
        if not (rest == text or rest.startswith(text + " ")):
            k = next((j for j, (a, b) in enumerate(zip(text, rest)) if a != b), min(len(text), len(rest)))
            raise ValueError(f"{who}: words differ from the scene text at character {k} of the passage "
                             f"(or the passage is out of order, or text is missing before it): scene "
                             f"{rest[max(0, k - 20):k + 20]!r}, script {text[max(0, k - 20):k + 20]!r}; "
                             "tags may only be inserted between words")
        rest = rest[len(text):].lstrip()
        if i < len(tagged) and not _END.search(text):
            raise ValueError(f"{who} ends mid-sentence ({text[-20:]!r}); passages end at a sentence end")
        book = TAG.findall(text)  # square brackets that are the book's own words are not tags
        for s_ in sentences(script):
            tags = TAG.findall(s_)
            for t in book:
                if t in tags:
                    tags.remove(t)
            if len(tags) > 1:
                raise ValueError(f"{who}: more than one audio tag in the sentence {s_[:40]!r}; at most one "
                                 "audio tag per sentence")
        opening = re.match(r"\s*(\[[^\[\]\n]*\])", script)
        opens = _mood(opening.group(1)) if opening else None
        if opens == "softly" and carried != "softly":
            raise ValueError(f"{who} opens on a bare [softly]; start on the words, or on a mood tag the whole "
                             "passage keeps")
        if carried and opens is None:
            raise ValueError(f"{who} drops the mood [{carried}] of the passage before; carry it across the "
                             f"join by opening with [{carried}] (or a deliberate new mood tag)")
        moods = [m for m in (_mood(t) for t in TAG.findall(script)) if m]
        carried = moods[-1] if moods else None
        plain.append(text)
    if rest:
        raise ValueError(f"the scene text continues after the last passage: {rest[:40]!r}")
    return plain


def _bounds(x: np.ndarray) -> tuple[int, int]:
    """First and one past the last audible sample (above EDGE_DB); the whole take when none is."""
    idx = np.flatnonzero(np.abs(x) > 10 ** (EDGE_DB / 20))
    return (int(idx[0]), int(idx[-1]) + 1) if len(idx) else (0, len(x))


def join_passages(takes: list[Path], out: Path, seam_s: float = SEAM_S) -> dict:
    """Join the retimed passage wavs into one scene wav at `out`. Each seam is the take's own room tone
    (retime.room_tone of the passage before it, -62...-68 dBFS) of about `seam_s`, joined to both sides by
    10 ms equal-power crossfades; the take edges beside a seam are cut back to 20 ms of the audible speech, so
    no raw edge silence (or digital zero) is left in the seam. The outer ends are the takes' own. Returns
    {"passages", "duration", "crossfade_ms", "seam_s", "seams": [{"at", "length_s"}]} (seconds in the scene)."""
    takes = [Path(t) for t in takes]
    if not takes:
        raise ValueError("no passages to join")
    xs = [retime.read(t) for t in takes]
    xf, keep = int(XF_S * SR), int(EDGE_KEEP_S * SR)
    acc, seams = np.zeros(0, np.float32), []
    for i, x in enumerate(xs):
        a, b = _bounds(x)
        piece = x[max(0, a - keep) if i > 0 else 0:min(len(x), b + keep) if i < len(xs) - 1 else len(x)]
        if i == 0:
            acc = piece.copy()
            continue
        n = int(seam_s * SR) + 2 * xf
        before = len(acc)
        acc = retime._crossfade(acc, retime.room_tone(xs[i - 1], n), xf)
        seam_end = len(acc) - xf
        acc = retime._crossfade(acc, piece, xf)
        seams.append({"at": round((before - xf + seam_end) / 2 / SR, 3), "length_s": round((seam_end - before + xf) / SR, 3)})
    retime.write(Path(out), acc)
    return {"passages": len(takes), "duration": round(len(acc) / SR, 3), "crossfade_ms": round(XF_S * 1000),
            "seam_s": seam_s, "seams": seams}
