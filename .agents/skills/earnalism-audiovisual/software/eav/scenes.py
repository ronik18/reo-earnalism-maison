"""Plan film scenes (30-90 s) from a Maison source export."""
import math

from .text import estimate_seconds, sentences

MIN_S = 30.0
MAX_S = 90.0
KEYFRAME_S = 15.0
SERIES_S = 2400.0


def _keyframes(seconds: float) -> int:
    return max(1, math.ceil(round(seconds / KEYFRAME_S, 9)))


def _plan_unit_scenes(unit: dict, language: str, wpm: float, film_no: int) -> list:
    # Each item: (anchor_id, kind, sentence, is_paragraph_end)
    items = []
    for p in unit.get("paragraphs", []):
        sents = sentences(p["text"], language)
        for i, s in enumerate(sents):
            items.append((p["anchor_id"], p.get("kind", "paragraph"), s, i == len(sents) - 1))

    def secs(blocks):
        return estimate_seconds(_join(blocks), language, wpm)

    scenes = []  # each: list of blocks {"anchor_id","kind","sents":[...]}
    cur = []

    def cur_text_with(sent_text):
        return _join(cur + [{"anchor_id": None, "kind": None, "sents": [sent_text]}])

    def add(anchor, kind, s):
        if cur and cur[-1]["anchor_id"] == anchor:
            cur[-1]["sents"].append(s)
        else:
            cur.append({"anchor_id": anchor, "kind": kind, "sents": [s]})

    def close():
        nonlocal cur
        if cur:
            scenes.append(cur)
            cur = []

    for anchor, kind, s, para_end in items:
        s_secs = estimate_seconds(s, language, wpm)
        if cur:
            extra = estimate_seconds(" " + s, language, wpm)
            if secs(cur) + extra > MAX_S or s_secs > MAX_S:
                close()
        add(anchor, kind, s)
        if para_end and kind != "heading" and secs(cur) >= MIN_S:
            close()
    close()

    # Fold a short trailing scene into its predecessor when it still fits.
    if len(scenes) >= 2 and secs(scenes[-1]) < MIN_S:
        merged = _merge(scenes[-2], scenes[-1])
        if secs(merged) <= MAX_S:
            scenes[-2:] = [merged]

    out = []
    for n, blocks in enumerate(scenes, 1):
        text = _join(blocks)
        seconds = estimate_seconds(text, language, wpm)
        flag = None
        if seconds > MAX_S:
            flag = "over_90s_sentence"
        elif seconds < MIN_S:
            flag = "under_30s"
        anchors = []
        for b in blocks:
            if b["anchor_id"] not in anchors:
                anchors.append(b["anchor_id"])
        out.append({
            "scene_id": f"f{film_no:02d}s{n:03d}",
            "anchor_ids": anchors,
            "text": text,
            "seconds": seconds,
            "keyframes": _keyframes(seconds),
            "flag": flag,
            "blocks": [{"anchor_id": b["anchor_id"], "kind": b["kind"],
                        "text": " ".join(b["sents"])} for b in blocks],
        })
    return out


def _join(blocks) -> str:
    return "\n\n".join(" ".join(b["sents"]) for b in blocks)


def _merge(a, b):
    a = [dict(x, sents=list(x["sents"])) for x in a]
    for x in b:
        if a and a[-1]["anchor_id"] == x["anchor_id"]:
            a[-1]["sents"].extend(x["sents"])
        else:
            a.append(dict(x, sents=list(x["sents"])))
    return a


def plan_film(source: dict, wpm: float = 120) -> dict:
    language = source.get("language", "en")
    units = source.get("units", [])
    total = sum(estimate_seconds(p["text"], language, wpm)
                for u in units for p in u.get("paragraphs", []))
    series = total > SERIES_S
    if series:
        groups = [[u] for u in units]
    else:
        groups = [units]
    films = []
    for i, group in enumerate(groups, 1):
        scenes = []
        for u in group:
            for sc in _plan_unit_scenes(u, language, wpm, i):
                scenes.append(sc)
        # renumber scenes continuously within a film
        for n, sc in enumerate(scenes, 1):
            sc["scene_id"] = f"f{i:02d}s{n:03d}"
        films.append({"unit_ids": [u["unit_id"] for u in group], "scenes": scenes})
    return {"series": series, "films": films}
