"""Paper edit: the shot plan and its two-column AV script, checked before any GPU job is built (R11).

A scene is planned shot by shot by Claude and an independent reviewer. They write the planner input
(`film/film-NN/shots/<scene>.input.json`, see `eav plan-shots --help`); this module only lays it out
on the measured narration timing and checks it. It never invents a subject, framing, camera, sound
or reference.

Input (`scene` dict, merged with the plan.json scene fields `scene_id` and `text`):
  spine    one sentence: what the scene is about
  fidelity the reviewer's one-line R7 note (no frame contradicts this or the neighbouring scenes' text)
  motifs   motifs reused from earlier scenes, changed (R8)
  shots    [{beats: [first, last], subject, framing, motion: wan|glide|static, layer, transition_in,
             bible_refs, camera: {move, zoom, pan_x, ease} (required for glide), wan_res (required for
             wan), sound: {sfx, music}, plants: [earlier shot numbers] (the peak shot)}]
  peak     {shot, at}: the shot that carries the peak and the second it lands on
  length_s optional: the scene's length when it runs past its last word (the R4 tail that `scene-timing` measures);
           the last shot ends there, captions still end with the words
  shots[].actions  optional, wan shots only: one performed action text per clip of the shot's chain (the take and
           each continuation). R1 holds a wan shot to one action per 6 s, as qc's new_info measures it.
`timing` is the measured narration, one entry per clause: [{start, end, text}] in seconds of the
re-timed narration. `beats` are the 0-based indexes into the beats derived from it (`beats()`: a boundary after
punctuation is a cut point; an unpunctuated one only when its pause is at least 0.15 s, else the entries merge). Approval records the sha256 of the input file and `require_approved` refuses when the input or the stored plan changed.
Shots tile the beats in order; a cut
falls in the middle of the pause between two beats, the first shot starts at 0 and the last ends
where the narration ends.

Rule codes returned by `validate`: R1, R2, R3 (hard) and R11 (only with for_job=True). R7 and R8 are
soft: they are returned as "R7?" / "R8?" (a trailing question mark means "the reviewer must look at
this", never a refusal): R7? when the scene input has no `fidelity` note (the reviewer's statement that
no frame contradicts this or the neighbouring scenes' text), R8? when it declares no `motifs`.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

MOTIONS = ("wan", "glide", "static")
WAN_RES = ("1280x704", "896x512")
LAYERS = ("present", "memory", "imagined")
TRANSITIONS = ("cut", "dissolve", "match")
GAP_S = 6.0          # R1/R2: never more than 6 s of narration per shot-or-beat
SHOT_MAX_S = 8.0     # R2: longest shot without a Wan beat
SHOT_HARD_S = 12.0   # R2: longest shot at all
PEAK_LO, PEAK_HI, PEAK_MIN_S = 0.70, 0.85, 4.0
# Planning estimate only (spec 2026-11-27 compute: about 0.6 CU per 1280x704 Wan clip on an L4, scaled by
# pixel count for 896x512). The job's own forecast is still derived from the measured rates.json at build.
WAN_CU_1280 = 0.6
_PIXELS = {"1280x704": 1280 * 704, "896x512": 896 * 512}
# A Wan clip is 121 frames at 24 fps (colab_jobs.FILM_FRAMES / FILM_FPS); a continuation starts on the previous
# clip's last frame, which assembly drops, so a chain of k clips plays 120 k + 1 frames. A shot's render length is
# its span plus the halves of its transitions (film.edit_lengths; a dissolve is film.DISSOLVE_S, a cut one frame).
CLIP_FRAMES, FPS, DISSOLVE_S = 121, 24, 0.8
# N1: a planned chain covers its shot's render length plus this many frames, so frame rounding between the plan
# (render_frames) and assembly (film.edit_lengths) can never leave a chain one frame short.
CHAIN_MARGIN = 1
_WORDS = re.compile(r"\s+")
_MARKS = (",", ".", ";", ":", "!", "?", "\u0964", "\u0965", "\u2014", "\u2013", "\u2026")  # , . ; : ! ? । ॥ — – …
_CLOSERS = " \"'\u201c\u201d\u2018\u2019)]"
BREATH_MIN_S = 0.15  # an unpunctuated pause shorter than this is not a legal cut


class NotApproved(ValueError):
    """A scene's shot plan has no approval; no GPU job may be built from it (R11)."""


def _words(text: str) -> str:
    return _WORDS.sub("", text)


def _ends_punct(text: str) -> bool:
    return text.rstrip().rstrip(_CLOSERS).endswith(_MARKS)


def beats(scene_text: str, timing: list) -> list:
    """The narration beats with their measured times: [{n, start, end, text, pause_after, kind}].
    `timing` must spell exactly the scene text (spacing aside). Each boundary between two timing entries is
    "punct" when the text before it ends with sentence or clause punctuation, otherwise "breath". A "punct"
    boundary is always a legal cut point; a "breath" boundary only when its measured pause is at least
    BREATH_MIN_S, otherwise the two entries are merged into one beat. `kind` is the kind of the boundary that
    ends the beat ("end" for the last beat); `pause_after` is the measured pause that follows it."""
    if not timing:
        raise ValueError("timing is empty: import the narration first")
    out, prev_end = [], None
    for i, t in enumerate(timing):
        s, e, txt = t.get("start"), t.get("end"), t.get("text")
        if not isinstance(txt, str) or not txt.strip() or not all(isinstance(v, (int, float)) for v in (s, e)):
            raise ValueError(f"timing entry {i} needs start, end and text")
        if e <= s or (prev_end is not None and s < prev_end):
            raise ValueError(f"timing entry {i} is not in order ({s}-{e})")
        if out:
            gap = round(s - prev_end, 3)
            if _ends_punct(out[-1]["text"]):
                out[-1].update(kind="punct", pause_after=gap)
            elif gap >= BREATH_MIN_S - 1e-9:
                out[-1].update(kind="breath", pause_after=gap)
            else:  # an unpunctuated gap too short to cut on: one beat
                out[-1].update(end=float(e), text=out[-1]["text"] + " " + txt.strip())
                prev_end = e
                continue
            out.append({"n": len(out), "start": float(s), "end": float(e), "text": txt.strip(), "pause_after": 0.0, "kind": "end"})
        else:
            out.append({"n": 0, "start": float(s), "end": float(e), "text": txt.strip(), "pause_after": 0.0, "kind": "end"})
        prev_end = e
    if _words("".join(b["text"] for b in out)) != _words(scene_text):
        raise ValueError("timing words do not match the scene text: the shot plan never changes the book's words")
    return out


def _need(shot: dict, n: int, key: str, kind=str):
    v = shot.get(key)
    if not isinstance(v, kind) or (kind is str and not v.strip()):
        raise ValueError(f"shot {n} needs {key}")
    return v


GLIDE_EXTRAS = {"zoom0": "positive number", "pan_y": "number", "near_gain": "positive number",
                "flat": "true or false", "sweep": "down-left, down-right or null", "drain": "true or false"}
SWEEPS = ("down-left", "down-right")   # glide.SWEEPS


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _glide_extras(cam: dict, n: int) -> dict:
    """The optional glide.render fields a shot may carry (type-checked; absent means glide.render's default)."""
    out = {}
    for k, v in cam.items():
        if k not in GLIDE_EXTRAS:
            continue
        ok = ((_num(v) and v > 0) if k in ("zoom0", "near_gain") else _num(v) if k == "pan_y"
              else isinstance(v, bool) if k in ("flat", "drain") else v is None or v in SWEEPS)
        if not ok:
            raise ValueError(f"shot {n} camera {k} must be {GLIDE_EXTRAS[k]}, not {v!r}")
        out[k] = v
    return out


def _camera(shot: dict, n: int) -> dict:
    cam = shot.get("camera")
    if shot["motion"] == "glide":
        if not isinstance(cam, dict) or not all(k in cam for k in ("move", "zoom", "pan_x", "ease")):
            raise ValueError(f"shot {n} is a glide and needs camera {{move, zoom, pan_x, ease}}")
        return {**{k: cam[k] for k in ("move", "zoom", "pan_x", "ease")}, **_glide_extras(cam, n)}
    base = {"move": "none", "zoom": 0.0, "pan_x": 0.0, "ease": "none"}
    return {**base, **{k: cam[k] for k in base if k in cam}} if isinstance(cam, dict) else base


def chain_frames(clips: int) -> int:
    """Frames a chain of `clips` Wan clips plays (each continuation drops its first frame)."""
    return CLIP_FRAMES * clips - max(0, clips - 1)


def chain_covers(clips: int, frames: int) -> bool:
    """A chain of `clips` covers a shot that renders `frames`, with the CHAIN_MARGIN frame(s) to spare (N1)."""
    return chain_frames(clips) >= frames + CHAIN_MARGIN


def clips_for(frames: int) -> int:
    """The fewest chained clips that cover `frames` with the CHAIN_MARGIN to spare."""
    k = 1
    while not chain_covers(k, frames):
        k += 1
    return k


def _f(seconds: float) -> int:
    return int(round(seconds * FPS))


def render_frames(shots: list) -> dict:
    """{shot n: frames it renders}: its span plus half of each neighbouring transition, as film.edit_lengths lays
    them out (a dissolve DISSOLVE_S, a cut a 1-frame xfade). The scene's own edges count its first shot's
    transition_in and, for the last shot, a dissolve into the next scene (the worst case; that is unknown here)."""
    shots = sorted(shots, key=lambda s: s["start"])
    over = [(_f(DISSOLVE_S) if s.get("transition_in") == "dissolve" else 1) for s in shots] + [_f(DISSOLVE_S)]
    out = {}
    for i, s in enumerate(shots):
        span = _f(s["end"]) - _f(s["start"])
        out[s["n"]] = span + (over[i] - over[i] // 2) + over[i + 1] // 2
    return out


def wan_clips_needed(sp: dict) -> dict:
    """{wan shot n: chained clips its render length needs}."""
    need = render_frames(sp.get("shots") or [])
    return {s["n"]: clips_for(need[s["n"]]) for s in sp.get("shots") or [] if s["motion"] == "wan"}


def plan(scene: dict, timing: list, bible: dict) -> dict:
    """Lay the planner input out on the measured timing. Raises ValueError for input the layout cannot honour."""
    bt = beats(scene["text"], timing)
    chars = set((bible or {}).get("characters") or {})
    shots_in = scene.get("shots")
    if not isinstance(shots_in, list) or not shots_in:
        raise ValueError("the planner input has no shots")
    shots, nxt = [], 0
    for i, si in enumerate(shots_in, 1):
        b = si.get("beats")
        if (not isinstance(b, list) or len(b) != 2 or not all(isinstance(x, int) for x in b)
                or b[0] != nxt or b[1] < b[0] or b[1] >= len(bt)):
            raise ValueError(f"shot {i} beats {b!r} must continue from beat {nxt} (shots tile 0..{len(bt) - 1} in order)")
        nxt = b[1] + 1
        motion = si.get("motion")
        if motion not in MOTIONS:
            raise ValueError(f"shot {i} motion must be one of {', '.join(MOTIONS)}")
        res = si.get("wan_res")
        if motion == "wan" and res not in WAN_RES:
            raise ValueError(f"shot {i} is a wan shot and needs wan_res {' or '.join(WAN_RES)}")
        if motion != "wan" and res is not None:
            raise ValueError(f"shot {i} is not a wan shot: wan_res must be absent")
        if si.get("layer") not in LAYERS or si.get("transition_in") not in TRANSITIONS:
            raise ValueError(f"shot {i} needs layer ({'|'.join(LAYERS)}) and transition_in ({'|'.join(TRANSITIONS)})")
        refs = si.get("bible_refs")
        if not isinstance(refs, list):
            raise ValueError(f"shot {i} needs bible_refs (a list, empty when no bible character is on screen)")
        unknown = [r for r in refs if r not in chars]
        if unknown:
            raise ValueError(f"shot {i} bible_refs {unknown} are not in the world bible characters")
        sound = si.get("sound") or {}
        start = 0.0 if i == 1 else round((bt[b[0] - 1]["end"] + bt[b[0]]["start"]) / 2, 3)
        last = b[1] == len(bt) - 1
        end = bt[-1]["end"] if last else round((bt[b[1]]["end"] + bt[b[1] + 1]["start"]) / 2, 3)
        shot = {"n": i, "start": start, "end": end, "framing": _need(si, i, "framing"), "camera": _camera(si, i),
                "motion": motion, "wan_res": res, "subject": _need(si, i, "subject"), "bible_refs": list(refs),
                "sound": {"vo": " ".join(x["text"] for x in bt[b[0]:b[1] + 1]), "sfx": list(sound.get("sfx") or []),
                          "music": sound.get("music")},
                "layer": si["layer"], "transition_in": si["transition_in"]}
        if si.get("plants"):
            shot["plants"] = list(si["plants"])
        acts = si.get("actions")
        if acts is not None:
            if motion != "wan" or not isinstance(acts, list) or not all(isinstance(a, str) and a.strip() for a in acts):
                raise ValueError(f"shot {i} actions must be a list of action texts, and only on a wan shot (one "
                                 "performed action per clip of its chain: the take and each continuation)")
            shot["actions"] = [a.strip() for a in acts]
        shots.append(shot)
    if nxt != len(bt):
        raise ValueError(f"shots end at beat {nxt - 1} but the narration has beats up to {len(bt) - 1}: beats must be covered")
    seconds = bt[-1]["end"]
    total = scene.get("length_s")
    if total is not None:   # the scene runs past its last word: the R4 tail of room tone (scene-timing)
        if not _num(total) or total < seconds - 1e-9:
            raise ValueError(f"scene length_s {total!r} must be a number at least the last clause's end {seconds:g}")
        seconds = float(total)
        shots[-1]["end"] = seconds
    wan = [s for s in shots if s["motion"] == "wan"]
    sp = {"scene_id": scene["scene_id"], "spine": scene.get("spine") or "",
          "seconds": seconds, "shots": shots, "peak": scene.get("peak"),
          "motifs": list(scene.get("motifs") or []), "fidelity": scene.get("fidelity") or ""}
    if total is not None:
        sp["speech_end"] = bt[-1]["end"]
    clips = wan_clips_needed(sp)   # continuations count (F15): each clip of a chain is generated
    sp["compute"] = {"stills": len(shots), "wan_shots": len(wan), "wan_clips": sum(clips.values()),
                     "cu": round(sum(clips[s["n"]] * WAN_CU_1280 * _PIXELS[s["wan_res"]] / _PIXELS["1280x704"]
                                     for s in wan), 3)}
    return sp


def check(sp: dict, for_job: bool = False) -> list:
    """[(code, message)] for every violated rule; codes ending in '?' are soft warnings."""
    out, shots = [], sorted(sp.get("shots") or [], key=lambda s: s["start"])
    secs = max([s["end"] for s in shots] + [sp.get("seconds") or 0.0])
    # R1: never more than 6 s with neither a new shot nor a Wan beat
    prev = 0.0
    for s in shots:
        if s["start"] - prev > GAP_S + 1e-9:
            out.append(("R1", f"{prev:.1f}-{s['start']:.1f} s has no shot"))
        d = s["end"] - s["start"]
        if s["motion"] != "wan" and d > GAP_S + 1e-9:
            out.append(("R1", f"shot {s['n']} holds {d:.1f} s without a new shot or a Wan beat"))
        elif s["motion"] == "wan" and d > GAP_S + 1e-9:   # one performed action per 6 s, as qc new_info measures it
            need = math.ceil(round(d, 6) / GAP_S)
            have = len(s.get("actions") or [])
            if have < need:
                out.append(("R1", f"wan shot {s['n']} runs {d:.1f} s with {have} declared action(s); over {GAP_S:g} s it "
                                  f"needs {need} (a continuation with its own action text in \"actions\"), else "
                                  "the frame stays the same picture and qc new_info fails it"))
        prev = s["end"]
    if secs - prev > GAP_S + 1e-9:
        out.append(("R1", f"{prev:.1f}-{secs:.1f} s has no shot"))
    # R2: shot count and length
    need = math.ceil(round(secs, 6) / GAP_S)
    if len(shots) < need:
        out.append(("R2", f"{len(shots)} shots for {secs:.1f} s; at least {need} (ceil(seconds / 6))"))
    for s in shots:
        d = s["end"] - s["start"]
        if d > SHOT_HARD_S + 1e-9:
            out.append(("R2", f"shot {s['n']} is {d:.1f} s (over {SHOT_HARD_S:g})"))
        elif d > SHOT_MAX_S + 1e-9 and s["motion"] != "wan":
            out.append(("R2", f"shot {s['n']} is {d:.1f} s without motion wan (over {SHOT_MAX_S:g})"))
    # R3: one peak at 70-85 %, at least 4 s, planted earlier
    pk = sp.get("peak")
    by_n = {s["n"]: s for s in shots}
    if not isinstance(pk, dict) or pk.get("shot") not in by_n or not isinstance(pk.get("at"), (int, float)):
        out.append(("R3", "no peak shot marked (peak: {shot, at})"))
    else:
        ps, at = by_n[pk["shot"]], pk["at"]
        if not PEAK_LO - 1e-9 <= at / secs <= PEAK_HI + 1e-9:
            out.append(("R3", f"peak at {at:g} s is {at / secs:.0%} of the scene, not 70-85 %"))
        if not ps["start"] - 1e-9 <= at <= ps["end"] + 1e-9:
            out.append(("R3", f"peak at {at:g} s is outside its shot {ps['n']} ({ps['start']:g}-{ps['end']:g})"))
        if ps["end"] - ps["start"] < PEAK_MIN_S - 1e-9:
            out.append(("R3", f"peak shot {ps['n']} is {ps['end'] - ps['start']:.1f} s, under {PEAK_MIN_S:g}"))
        if not [p for p in ps.get("plants") or [] if p in by_n and p < ps["n"]]:
            out.append(("R3", f"peak shot {ps['n']} has no planted earlier shot (plants: [shot numbers])"))
    # soft: R7 needs the reviewer's fidelity note, R8 needs a declared motif
    if not (sp.get("fidelity") or "").strip():
        out.append(("R7?", "no fidelity note: the reviewer checks every frame against this and the neighbouring scenes' text"))
    if not sp.get("motifs"):
        out.append(("R8?", "no motif declared from an earlier scene"))
    if for_job and not _approved(sp):
        out.append(("R11", "the shot plan is not approved"))
    return out


def validate(shotplan: dict, for_job: bool = False) -> list:
    """The violated rule codes, each once, in rule order. 'R7?'/'R8?' are soft warnings; R11 only with for_job=True."""
    seen = []
    for code, _ in check(shotplan, for_job):
        if code not in seen:
            seen.append(code)
    return sorted(seen, key=lambda c: int(c.strip("R?")))


def _approved(sp: dict) -> bool:
    a = sp.get("approved")
    return (isinstance(a, dict) and all(isinstance(a.get(k), str) and a[k].strip() for k in ("by", "at", "reviewer"))
            and a["by"].strip().lower() != a["reviewer"].strip().lower())


def input_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def approve(sp: dict, by: str, reviewer: str, at: str = None, input_sha256: str = None,
            timing_sha256: str = None) -> dict:
    """A copy of the plan carrying {approved: {by, at, reviewer, input_sha256}}. Refused when the two are the same
    person (owner decision 3: Claude plus an independent reviewer) or when a hard rule is violated."""
    if not by.strip() or not reviewer.strip() or by.strip().lower() == reviewer.strip().lower():
        raise ValueError("approval needs two names: --by and an independent --reviewer who is not the same")
    hard = [f"{c}: {m}" for c, m in check(sp) if not c.endswith("?")]
    if hard:
        raise ValueError("the plan violates " + "; ".join(hard))
    return {**sp, "approved": {"by": by.strip(), "at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "reviewer": reviewer.strip(), **({"input_sha256": input_sha256} if input_sha256 else {}),
                               **({"timing_sha256": timing_sha256} if timing_sha256 else {})}}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def av_markdown(shotplan: dict) -> str:
    """The two-column AV script (audio | visual) with a time column, one row per shot."""
    sp = shotplan
    c = sp.get("compute") or {}
    lines = [f"# {sp['scene_id']}: AV script", "", f"Spine: {sp.get('spine', '')}", "",
             f"{len(sp['shots'])} shots, {sp.get('seconds', 0):.1f} s, {c.get('wan_clips', 0)} Wan clip(s), "
             f"about {c.get('cu', 0)} CU (planning estimate).", "",
             "| Time | Audio | Visual |", "| --- | --- | --- |"]
    pk = sp.get("peak") or {}
    for s in sp["shots"]:
        audio = [f"VO: {s['sound']['vo']}"] + [f"SFX: {x}" for x in s["sound"].get("sfx") or []]
        if s["sound"].get("music"):
            audio.append(f"Music: {s['sound']['music']}")
        cam = s["camera"]
        look = f"{s['motion']}" + (f" {s['wan_res']}" if s.get("wan_res") else "") + (
            f", {cam['move']} zoom {cam['zoom']:g} pan {cam['pan_x']:g} ease {cam['ease']}" if s["motion"] == "glide" else "")
        vis = [f"{s['subject']} ({s['framing']})", f"{look}; {s['layer']}; in: {s['transition_in']}"]
        if s.get("bible_refs"):
            vis.append("Bible: " + ", ".join(s["bible_refs"]))
        if pk.get("shot") == s["n"]:
            vis.append(f"PEAK at {pk['at']:g} s" + (f"; plants shot {', '.join(map(str, s['plants']))}" if s.get("plants") else ""))
        lines.append(f"| {s['n']} {s['start']:.2f}-{s['end']:.2f} | {_cell('<br>'.join(audio))} | {_cell('<br>'.join(vis))} |")
    appr = sp.get("approved")
    lines += ["", f"Approved by {appr['by']} with {appr['reviewer']} at {appr['at']}." if appr else "NOT APPROVED."]
    return "\n".join(lines) + "\n"


def paths(film_dir, scene_id: str) -> dict:
    d = Path(film_dir) / "shots"
    return {"dir": d, "input": d / f"{scene_id}.input.json", "plan": d / f"{scene_id}.json", "av": d / f"{scene_id}.av.md"}


def write(film_dir, sp: dict) -> dict:
    p = paths(film_dir, sp["scene_id"])
    p["dir"].mkdir(parents=True, exist_ok=True)
    p["plan"].write_text(json.dumps(sp, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    p["av"].write_text(av_markdown(sp), encoding="utf-8")
    return p


def require_approved(film_dir, scene_id: str) -> dict:
    """R11: the one refusal every shot-plan-driven job (stills now, film_clips next) calls before building."""
    p = paths(film_dir, scene_id)["plan"]
    hint = f"Write the planner input, run `plan-shots --scene {scene_id}` and then `plan-shots --scene {scene_id} --approve --by <name> --reviewer <name>`"
    if not p.is_file():
        raise NotApproved(f"scene {scene_id} has no shot plan ({p}); no job is built before the paper edit is approved. {hint}")
    sp = json.loads(p.read_text(encoding="utf-8"))
    if not _approved(sp):
        raise NotApproved(f"the shot plan of scene {scene_id} is not approved (needs approved: by, at and an independent "
                          f"reviewer); no job is built before the paper edit is approved. {hint}")
    inp = paths(film_dir, scene_id)["input"]
    want = sp["approved"].get("input_sha256")
    if not want or not inp.is_file() or input_sha256(inp) != want:
        raise NotApproved(f"the planner input of scene {scene_id} changed since approval (or the approval records no "
                          f"input hash); re-approve: {hint}")
    tsha = sp["approved"].get("timing_sha256")
    tf = Path(film_dir) / "shots" / f"{scene_id}.timing.json"
    if tsha and (not tf.is_file() or input_sha256(tf) != tsha):
        raise NotApproved(f"the measured timing of scene {scene_id} ({tf.name}) changed since approval; re-approve: {hint}")
    hard = [f"{c}: {m}" for c, m in check(sp) if not c.endswith("?")]
    if hard:
        raise NotApproved(f"the approved shot plan of scene {scene_id} now violates " + "; ".join(hard) + f"; re-approve: {hint}")
    return sp
