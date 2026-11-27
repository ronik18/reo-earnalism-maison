"""Eleven v4 narration in passages: split a scene, check each passage's script, join the retimed takes.

The operator generates one take per passage of 15-30 s (`split_passages` cuts only at sentence or paragraph
ends and never alters a character, so the passages concatenated are the scene text). `check_passage_scripts`
holds the tagged scripts to the voice rules: the words are the book's, at most one audio tag per sentence,
no passage opens on a bare `[softly]`, and a mood tag still in force at the end of a passage is carried
into the next one. After `retime` and `voicecheck` of each passage, `join_passages` builds the scene wav:
each seam is the take's own room tone (never digital zero) joined by 40 ms equal-power crossfades (the binding
30-50 ms), and the scene gets its R9 lead-in (room tone so the first word lands LEAD_IN_S in) and an R4 tail of room
tone (TAIL_S) for the J/L-cut into the next scene.
Needs numpy and ffmpeg (through eav.retime).
"""
import random
import re
import statistics
import zlib
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
XF_S = 0.040            # crossfade at each join: the binding 30-50 ms (spec section 9, global constraints)
EDGE_KEEP_S = 0.080     # take edge kept beyond the last/first audible sample at a seam (2 x the crossfade)
LEAD_IN_S = 0.85        # R9: 0.5-1 s of breath before the first word (the reference scene's 0.85 s)
LEAD_IN_RANGE = (0.5, 1.0)
TAIL_S = 2.0            # R4: room tone after the last word, the room a J/L-cut into the next scene needs
EDGE_DB = -50.0         # below this a sample is take edge silence, not speech
PAUSE_TAGS = {"pause", "short pause", "long pause"}   # tags that do not set a mood
MIN_RUN = 3             # passages a run needs for its own measured rate (below: the --cps estimate, warning only)
JITTER = retime.JITTER  # seams vary like retime's pauses
_PARA = re.compile(r"\n[ \t]*\n\s*")


def _chunks(text: str) -> list[tuple[str, bool]]:
    """(chunk, ends_paragraph): the sentences of eav.text.sentences (the one sentence definition) with their
    trailing whitespace, so the chunks join back to text; a blank line ends a paragraph."""
    out: list[tuple[str, bool]] = []
    pieces, pos = [], 0
    for m in _PARA.finditer(text):
        pieces.append((text[pos:m.start()], m.group()))
        pos = m.end()
    pieces.append((text[pos:], ""))
    for body, sep in pieces:
        words_from = 0
        sents = sentences(body)
        if not sents:
            if out:
                out[-1] = (out[-1][0] + body + sep, True)
            elif body + sep:
                out.append((body + sep, True))
            continue
        cur = 0
        for k, sent in enumerate(sents):
            for word in sent.split():
                j = body.index(word, words_from)
                words_from = j + len(word)
            end = len(body) if k == len(sents) - 1 else words_from
            while end < len(body) and body[end].isspace() and k != len(sents) - 1:
                end += 1
            chunk = body[cur:end] + (sep if k == len(sents) - 1 else "")
            out.append((chunk, k == len(sents) - 1))
            cur = end
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
    cuts, acc = set(), ""
    for chunk, _ in _chunks(scene_text):
        acc = _norm(acc + " " + chunk)
        cuts.add(acc)
    plain, carried, done = [], None, ""
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
        done = _norm(done + " " + text)
        if i < len(tagged) and done not in cuts:
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


def seam_lengths(plains: list[str], ids: list[str], headings=()) -> list[float]:
    """Seconds of room tone between a scene's passages, from the punctuation that ends each passage
    (retime.TARGETS: । and ? 0.8-1.0 s, ! 1.4-1.6 s; a passage that starts a heading is preceded by the heading
    pause 2.5-3.0 s), each varied +-15 % by a draw seeded with the passage id, as retime does for pauses."""
    heads = [_norm(h) for h in headings]
    out = []
    for i in range(len(plains) - 1):
        kinds = retime._kinds(plains[i])
        kind = "heading_before" if any(plains[i + 1].startswith(h) for h in heads) else (kinds[-1] if kinds else "sentence")
        rng = random.Random(zlib.crc32(ids[i].encode()))
        lo, hi = retime.TARGETS[kind]
        out.append(round(rng.uniform(lo, hi) * rng.uniform(1 - JITTER, 1 + JITTER), 3))
    return out


def expected_durations(chars: list[int], durations: list[float], cps: float = CPS_BN) -> tuple[list[float], bool]:
    """(expected seconds per passage, measured): with MIN_RUN or more passages, characters divided by the run's
    own median measured rate (characters per second of the retimed passages), so only a passage out of pace
    with its run (truncated, runaway) misses; with fewer, characters / cps and measured is False (the caller
    reports `duration` as a warning)."""
    if len(chars) >= MIN_RUN:
        rate = statistics.median(c / d for c, d in zip(chars, durations) if d > 0)
        return [c / rate for c in chars], True
    return [c / cps for c in chars], False


def join_passages(takes: list[Path], out: Path, seams: list[float] | None = None, seam_s: float = SEAM_S,
                  lead_in_s: float | None = None, tail_s: float | None = None) -> dict:
    """Join the retimed passage wavs into one scene wav at `out`. Each seam is the take's own room tone
    (retime.room_tone of the passage before it, -62...-68 dBFS) of `seams[i]` seconds (default `seam_s`), joined
    to both sides by 40 ms equal-power crossfades; the take edges beside a seam are cut back to 80 ms of the
    audible speech, so no raw edge silence (or digital zero) is left in the seam. With `lead_in_s` the scene opens
    on room tone so its first audible sample lands at that second (R9), and with `tail_s` it ends that long after
    the last audible sample (R4); without them the outer ends are the takes' own.
    Returns {"passages", "duration", "crossfade_ms", "seams": [{"at", "length_s"}], "offsets": [seconds of each
    passage's sample 0 on the scene timeline], "speech_start", "speech_end", "lead_in_s", "tail_s"}."""
    takes = [Path(t) for t in takes]
    if not takes:
        raise ValueError("no passages to join")
    seams = list(seams) if seams is not None else [seam_s] * (len(takes) - 1)
    if len(seams) != len(takes) - 1:
        raise ValueError("one seam length per join")
    xs = [retime.read(t) for t in takes]
    xf, keep = int(XF_S * SR), int(EDGE_KEEP_S * SR)
    acc, marks, offsets = np.zeros(0, np.float32), [], []
    first_a = _bounds(xs[0])[0]
    head = 0
    if lead_in_s is not None:   # cut the first take's own edge silence, then lay room tone up to the lead-in
        head = max(0, first_a - keep)
        pad = int(round(lead_in_s * SR)) - (first_a - head)
        if pad > 0:
            acc = retime.room_tone(xs[0], pad + xf)
    for i, x in enumerate(xs):
        a, b = _bounds(x)
        lo = max(0, a - keep) if i > 0 else head
        last = i == len(xs) - 1
        hi = min(len(x), b + keep) if (not last or tail_s is not None) else len(x)
        piece = x[lo:hi].copy()
        if lo < a:            # the kept take edge carries room tone too: no digital zero at a seam or lead-in
            piece[:a - lo] += retime.room_tone(x, a - lo)
        if hi > b and (not last or tail_s is not None):
            piece[b - lo:] += retime.room_tone(x, hi - b)
        if i == 0:
            start = max(0, len(acc) - xf) if len(acc) else 0
            acc = retime._crossfade(acc, piece, xf) if len(acc) else piece.copy()
            offsets.append((start - lo) / SR)
            continue
        n = int(seams[i - 1] * SR) + 2 * xf
        before = len(acc)
        acc = retime._crossfade(acc, retime.room_tone(xs[i - 1], n), xf)
        seam_end = len(acc) - xf
        offsets.append((len(acc) - xf - lo) / SR)
        acc = retime._crossfade(acc, piece, xf)
        marks.append({"at": round((before + seam_end) / 2 / SR, 3),     # the seam's pure room tone, between
                      "length_s": round((seam_end - before) / SR, 3)})    # its two crossfades
    b_last = _bounds(xs[-1])[1]
    speech_end = offsets[-1] + b_last / SR
    if tail_s is not None:
        want = int(round((speech_end + tail_s) * SR))
        if want > len(acc):
            acc = retime._crossfade(acc, retime.room_tone(xs[-1], want - len(acc) + xf), xf)
        acc = acc[:want]
    retime.write(Path(out), acc)
    speech_start = offsets[0] + first_a / SR
    return {"passages": len(takes), "duration": round(len(acc) / SR, 3), "crossfade_ms": round(XF_S * 1000),
            "seams": marks, "offsets": [round(o, 4) for o in offsets], "speech_start": round(speech_start, 3),
            "speech_end": round(speech_end, 3), "lead_in_s": lead_in_s, "tail_s": tail_s}
