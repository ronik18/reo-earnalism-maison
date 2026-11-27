"""Reel quality checks: contact sheet and loop-closure SSIM (ffmpeg subprocess)."""
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path


def _duration(video) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(video)], check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


def speech_onset(audio, threshold_db=-40.0, rate=16000):
    """Seconds before the first sample louder than threshold_db (None if it never is)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(rate),
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    samples = np.abs(np.frombuffer(raw, np.float32))
    loud = np.nonzero(samples >= 10 ** (threshold_db / 20))[0]
    return round(float(loud[0]) / rate, 4) if loud.size else None


def contact_sheet(video, out, every_s=1.0, cols=5, thumb_h=320, max_tiles=100):
    """Tile one thumbnail per `every_s` seconds into a single image; a long video is sampled
    more sparsely so the sheet holds at most `max_tiles` thumbnails (JPEG caps at 65500 px)."""
    duration = _duration(video)
    every_s = max(every_s, duration / max_tiles)
    n = max(1, int(math.ceil(duration / every_s)))
    rows = math.ceil(n / cols)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
                    f"fps=1/{every_s},scale=-2:{thumb_h},tile={min(cols, n)}x{rows}",
                    "-frames:v", "1", "-update", "1", str(out)], check=True)
    return Path(out)


def loop_score(video) -> float:
    """SSIM between the last and the first frame, clamped to [0, 1]."""
    with tempfile.TemporaryDirectory() as td:
        first, last = Path(td) / "first.png", Path(td) / "last.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-frames:v", "1",
                        str(first)], check=True)
        # -update keeps overwriting one file, so it ends on the final frame
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.5", "-i", str(video),
                        "-update", "1", str(last)], check=True)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(last), "-i", str(first),
                            "-lavfi", "ssim", "-f", "null", "-"], check=True,
                           capture_output=True, text=True)
    m = re.search(r"All:(-?[\d.]+|nan|inf)", r.stderr)
    if not m:
        raise RuntimeError("could not parse ssim output")
    return min(1.0, max(0.0, float(m.group(1))))


# ====================================================================== cinematic-film gates
# Edit gates (R1, R10, holds, black bars, hitches), audio gates, sound-on-picture (R4) and the written
# captions (R5), run by `eav qc` on a finished shot-based film (`film --shots`).
NEW_INFO_SIM = 0.9       # R1: a frame this similar to the span's anchor (after alignment) adds no new information
NEW_INFO_FPS = 4.0       # R1 samples this many frames a second
NEW_INFO_MAX_S = 6.0     # R1: no more than this long without new information (a Wan beat)
FLASH_JUMP = 0.25        # R10: a luminance jump over 25% of full scale is a flash edge
FLASH_MAX_PER_S = 3      # R10
HITCH_RATIO = 2.0        # a luma step more than 2x both neighbours inside a dissolve
HITCH_MIN_STEP = 0.3     # luma levels (0-255) a step must move to belong to a dissolve
BAR_FRAC = 0.02          # a black band of at least 2% of the frame height/width from an edge
BAR_BLACK, BAR_INTERIOR = 24, 40
MARGIN_RANGE = (16.0, 18.0)    # voice over music, dB in speech (cue.MARGIN_RANGE)
ZERO_RUN_S = 0.05        # digital zero: any run of exact-zero samples longer than this
LUFS_TARGET, LUFS_TOL = -16.0, 1.0
TP_MAX_LEGACY = -1.0     # old films; a shot-based film uses film.SHOT_TP_MAX (-1.5)


def _fps(video) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=avg_frame_rate", "-of", "csv=p=0", str(video)],
                       check=True, capture_output=True, text=True).stdout.strip()
    num, _, den = r.partition("/")
    return float(num) / float(den or 1)


def _gray_frames(video, w, h, fps=None):
    """Yield (index, uint8 (h, w) frame) decoded by ffmpeg, at `fps` (or the native rate); streamed."""
    import numpy as np
    vf = (f"fps={fps}," if fps else "") + f"scale={w}:{h}:flags=area,format=gray"
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", vf, "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE)
    try:
        i = 0
        while True:
            buf = p.stdout.read(w * h)
            if len(buf) < w * h:
                break
            yield i, np.frombuffer(buf, np.uint8).reshape(h, w)
            i += 1
    finally:
        p.stdout.close()
        p.wait()


def _align_similarity(anchor, frame) -> float:
    """Zero-mean correlation of `frame` with `anchor` after a zoom/shift-compensating alignment: ORB matches
    with a RANSAC similarity transform (scale, rotation, translation), ECC affine when too few matches, the
    identity otherwise. A glide's zoom and pan are undone, so only content that really changed lowers it."""
    import cv2
    import numpy as np
    h, w = anchor.shape
    warp = np.eye(2, 3, dtype=np.float32)
    orb = cv2.ORB_create(400)
    ka, da = orb.detectAndCompute(anchor, None)
    kf, df = orb.detectAndCompute(frame, None)
    found = False
    if da is not None and df is not None and len(ka) >= 8 and len(kf) >= 8:
        m = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, df)
        if len(m) >= 8:
            src = np.float32([ka[x.queryIdx].pt for x in m])
            dst = np.float32([kf[x.trainIdx].pt for x in m])
            M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0)
            if M is not None and inl is not None and int(inl.sum()) >= 8 and 0.5 < np.hypot(M[0, 0], M[0, 1]) < 2.0:
                warp, found = M.astype(np.float32), True
    if not found:
        try:
            ecc = np.eye(2, 3, dtype=np.float32)
            crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-4)
            _, ecc = cv2.findTransformECC(frame.astype(np.float32), anchor.astype(np.float32), ecc,
                                          cv2.MOTION_AFFINE, crit, None, 5)
            warp = cv2.invertAffineTransform(ecc)
        except cv2.error:
            pass
    a = cv2.warpAffine(anchor, warp, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    mask = cv2.warpAffine(np.full((h, w), 255, np.uint8), warp, (w, h), flags=cv2.INTER_NEAREST) > 0
    mask = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    if mask.sum() < 0.25 * h * w:
        return 0.0
    a = cv2.GaussianBlur(a, (5, 5), 0).astype(np.float32)[mask]
    b = cv2.GaussianBlur(frame, (5, 5), 0).astype(np.float32)[mask]
    a, b = a - a.mean(), b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if den < 1e-6:                       # two flat frames: the same unless their level moved
        return 1.0 if abs(float(np.mean(anchor)) - float(np.mean(frame))) < 8 else 0.0
    return float((a * b).sum() / den)


def new_info_gaps(video: Path, threshold: float, fps: float = NEW_INFO_FPS, max_s: float = NEW_INFO_MAX_S) -> list:
    """R1: spans (start, end seconds) longer than `max_s` whose content stays similar (zero-mean correlation of
    the zoom/pan-aligned frame with the span's first frame, above `threshold`): a glide over one still with no
    Wan beat adds no new information however it zooms. Sampled at `fps` frames a second (160x90 grey)."""
    gaps, anchor, t0, last = [], None, 0.0, 0.0
    for i, frame in _gray_frames(video, 160, 90, fps):
        t = i / fps
        if anchor is None or _align_similarity(anchor, frame) < threshold:
            if anchor is not None and last + 1 / fps - t0 > max_s:
                gaps.append((round(t0, 3), round(last + 1 / fps, 3)))
            anchor, t0 = frame, t
        last = t
    if anchor is not None and last + 1 / fps - t0 > max_s:
        gaps.append((round(t0, 3), round(last + 1 / fps, 3)))
    return gaps


def hold_hashes(shot_plan_dir: Path, stills_dir: Path = None) -> list:
    """Scenes whose shots reuse one still file (same sha256) with no Wan shot between the two: a hold, not a new
    picture. Reads the approved plans `<scene>.json` in `shot_plan_dir` (not `*.input.json`/`*.av.md`) and the
    stills `<scene>-<n>.<ext>` of `stills_dir` (default: the sibling `stills` folder). A shot without a still
    file (a Wan shot) is skipped."""
    import hashlib
    shot_plan_dir = Path(shot_plan_dir)
    stills = Path(stills_dir) if stills_dir else shot_plan_dir.parent / "stills"
    held = []
    for plan in sorted(shot_plan_dir.glob("*.json")):
        if plan.name.endswith(".input.json"):
            continue
        sp = json.loads(plan.read_text(encoding="utf-8"))
        sid, seen = sp.get("scene_id") or plan.stem, {}
        for shot in sorted(sp.get("shots") or [], key=lambda s: s["n"]):
            if shot.get("motion") == "wan":
                seen.clear()                   # a Wan beat: new information, reuse before it no longer counts
                continue
            f = next((p for p in sorted(stills.glob(f"{sid}-{shot['n']}.*"))
                      if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")), None)
            if f is None:
                continue
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            if h in seen:
                held.append(sid)
                break
            seen[h] = shot["n"]
    return held


def black_bars(video: Path, fps: float = 2.0) -> list:
    """Seconds (sampled at `fps`) of frames with a black band (every pixel of the outer BAR_FRAC of the height
    or width at most luma 24) while the picture inside is visible (mean luma above 40, so a fade is no bar)."""
    import numpy as np
    out = []
    for i, f in _gray_frames(video, 320, 180, fps):
        kh, kw = max(2, math.ceil(BAR_FRAC * f.shape[0])), max(2, math.ceil(BAR_FRAC * f.shape[1]))
        bands = (f[:kh], f[-kh:], f[:, :kw], f[:, -kw:])
        if any(b.max() <= BAR_BLACK for b in bands) and float(f[kh:-kh, kw:-kw].mean()) > BAR_INTERIOR:
            out.append(round(i / fps, 3))
    return out


def _luma_series(video):
    """(mean luma 0-255 per frame as a float array, fps) at the native rate, from 64x36 grey frames."""
    import numpy as np
    return np.array([float(f.mean()) for _, f in _gray_frames(video, 64, 36)]), _fps(video)


def frame_hitches(video: Path) -> list:
    """Seconds of a single-frame luma step more than 2x both neighbouring steps, inside a dissolve (a run of
    steps all moving the same way, each at least 0.3 luma levels): the picture jumps once within a smooth fade."""
    import numpy as np
    luma, fps = _luma_series(video)
    d = np.diff(luma)
    out = []
    for i in range(1, len(d) - 1):
        a, b, c = d[i - 1], d[i], d[i + 1]
        if min(abs(a), abs(b), abs(c)) >= HITCH_MIN_STEP and np.sign(a) == np.sign(b) == np.sign(c) \
                and abs(b) > HITCH_RATIO * max(abs(a), abs(c)):
            out.append(round((i + 1) / fps, 3))
    return out


def flashes(video: Path, cuts: list = None) -> dict:
    """R10. A flash edge is a mean-luma jump over 25% of full scale between two frames; a flash is a rise and a
    fall, so the rate in any 1 s window is max(rises, falls). Returns {"max_per_s", "at" (window start of the
    worst), "jumps": [times], "unplanned": [times of jumps further than one frame from a planned cut] or None
    when no `cuts` are given (no plan to judge against)}."""
    import numpy as np
    luma, fps = _luma_series(video)
    d = np.diff(luma) / 255.0
    idx = np.nonzero(np.abs(d) > FLASH_JUMP)[0]
    times = [round((i + 1) / fps, 3) for i in idx]
    worst, at = 0, 0.0
    for j, t in enumerate(times):
        win = [k for k, u in zip(idx, times) if t <= u < t + 1.0]
        n = max(sum(d[k] > 0 for k in win), sum(d[k] < 0 for k in win))
        if n > worst:
            worst, at = n, t
    unplanned = None
    if cuts is not None:
        tol = 1 / fps + 1e-6
        unplanned = [t for t in times if not any(abs(t - c) <= tol for c in cuts)]
    return {"max_per_s": int(worst), "at": at, "jumps": times, "unplanned": unplanned}


def planned_cuts(plans: list) -> list:
    """Seconds, on the finished film, of every planned hard edit: the end of the title card, each shot boundary
    of the scenes (in order, frame-aligned like film.edit_lengths) and the start of the credits and of the END
    card. `plans` are the approved shot plans in film order."""
    from . import film
    fps = film.SHOT_FPS
    lead, cum, cuts = film.TITLE_S, 0.0, [film.TITLE_S]
    for sp in plans:
        for s in sorted(sp["shots"], key=lambda s: s["start"]):
            cuts.append(round(lead + film._frames(cum + s["end"], fps) / fps, 6))
        cum += sp["seconds"]
    cuts.append(round(lead + film._frames(cum, fps) / fps + film.CREDITS_S, 6))
    return cuts


def audio_gates(mix: Path, voice: Path, shots: bool = False) -> dict:
    """Audio gates on a finished film mix. `shots` selects the cinematic film's limits (true peak at most
    film.SHOT_TP_MAX = -1.5 dBTP; -1.0 for an older film); loudness is -16 +-1 LUFS either way.
    Voice over music: the music is not available here, so it is estimated as the residual of the mix after a
    least-squares fit of the voice into it (one gain over both channels), and the margin is the rms of the fitted
    voice over the rms of that residual, over the frames where the voice speaks (10 ms frames above 30 dB under the
    95th-percentile level, cue._active). The residual holds the ambience and foley as well, so the figure reads at
    most a little low. Must be 16-18 dB (cue.MARGIN_DB = 17). Digital zero: a run of exact-zero samples (every
    channel) longer than 50 ms anywhere fails. `mix` and `voice` must start together."""
    import numpy as np
    from . import cue, film, mix as mixmod
    m = cue.read(mix, ch=2)
    v = cue.read(voice, ch=1)[:, 0]
    n = min(len(m), len(v))
    m, v = m[:n], v[:n]
    hop = cue.SR // 100
    _, act = cue._active(v, hop)
    sp = np.repeat(act, hop)
    sp = np.pad(sp, (0, n - len(sp)))[:n]
    margin = None
    if sp.any():
        vs, ms = v[sp], m[sp]
        g = float((ms * vs[:, None]).sum() / (2 * (vs * vs).sum() + 1e-18))
        resid = ms - g * vs[:, None]
        margin = round(float(20 * np.log10(abs(g) * np.sqrt(np.mean(vs ** 2)) / (np.sqrt(np.mean(resid ** 2)) + 1e-12))), 1)
    zero = np.all(m == 0.0, axis=1)
    runs, k = [], 0
    edges = np.flatnonzero(np.diff(np.concatenate(([0], zero.astype(np.int8), [0]))))
    for a, b in zip(edges[::2], edges[1::2]):
        if (b - a) / cue.SR > ZERO_RUN_S:
            runs.append((round(a / cue.SR, 3), round(b / cue.SR, 3)))
    meas = mixmod.measure(mix)
    tp_max = film.SHOT_TP_MAX if shots else TP_MAX_LEGACY
    out = {"margin_db": margin, "margin_ok": margin is not None and MARGIN_RANGE[0] <= margin <= MARGIN_RANGE[1],
           "digital_zero": runs, "digital_zero_ok": not runs, "lufs": meas["lufs"], "true_peak": meas["true_peak"],
           "true_peak_max": tp_max, "true_peak_ok": meas["true_peak"] <= tp_max,
           "loudness_ok": abs(meas["lufs"] - LUFS_TARGET) <= LUFS_TOL}
    return out


def sound_on_picture(shot_plan: dict, fx: list) -> list:
    """R4: every sfx a shot's plan lists under sound.sfx needs a placed ambience/foley entry over that shot.
    `fx` is the cue's entries [{path, at, dur?, ...}] (scene seconds); an entry matches a name when its `sfx`/`name`
    field equals it or the name is in its file stem, and it overlaps the shot when it plays at any point of
    [start, end) (`dur` from the entry, else the file's length when it exists, else an instant at `at`).
    Returns ["shot N: name", ...] for what is missing."""
    spans = []
    for e in fx:
        dur = e.get("dur")
        if dur is None and Path(e["path"]).is_file():
            dur = _duration(e["path"]) - float(e.get("start", 0.0))
        spans.append((e, float(e["at"]), float(e["at"]) + float(dur or 0.0)))
    missing = []
    for shot in sorted(shot_plan.get("shots") or [], key=lambda s: s["n"]):
        for name in (shot.get("sound") or {}).get("sfx") or []:
            def hit(e, a, b):
                named = name in (e.get("sfx"), e.get("name")) or name.lower() in Path(e["path"]).stem.lower()
                return named and a < shot["end"] and (b > shot["start"] or shot["start"] <= a)
            if not any(hit(*s) for s in spans):
                missing.append(f"shot {shot['n']}: {name}")
    return missing


_CUE_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[.,](\d{3})\s*-->\s*(\d+):(\d\d):(\d\d)[.,](\d{3})")


def check_captions(text: str, lang: str) -> list:
    """R5: re-check written captions (WebVTT or SRT) against film.captions' limits (film.CAP_*): at most 2 lines
    of 42 visible characters, 1-7 s per cue, at most film.CAP_CPS[lang] characters/s (15 for bn), cues in order.
    Returns the problems found, empty when none."""
    from . import film
    cps = film.CAP_CPS.get(lang, film.CAP_CPS_DEFAULT)
    problems, prev_end = [], 0.0
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        k = next((i for i, ln in enumerate(lines) if _CUE_TIME.search(ln)), None)
        if k is None:
            continue
        g = [int(x) for x in _CUE_TIME.search(lines[k]).groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = [ln for ln in lines[k + 1:] if ln.strip()]
        where = f"cue at {start:.3f} s"
        dur = end - start
        if not film.CAP_MIN_S - 1e-9 <= dur <= film.CAP_MAX_S + 1e-9:
            problems.append(f"{where}: duration {dur:.2f} s is outside {film.CAP_MIN_S:g}-{film.CAP_MAX_S:g} s")
        if len(body) > film.CAP_LINES:
            problems.append(f"{where}: {len(body)} lines, at most {film.CAP_LINES}")
        for ln in body:
            if film._visible_len(ln) > film.CAP_LINE_CHARS:
                problems.append(f"{where}: a line of {film._visible_len(ln)} characters, at most {film.CAP_LINE_CHARS}")
        chars = sum(film._visible_len(ln) for ln in body)
        if dur > 0 and chars / dur > cps + 1e-6:
            problems.append(f"{where}: {chars / dur:.1f} characters/s, at most {cps:g}")
        if start < prev_end - 1e-9:
            problems.append(f"{where}: starts before the previous cue ends")
        prev_end = end
    return problems


def film_gates(video: Path, film_dir: Path, scene_ids: list, lang: str) -> tuple:
    """Run every cinematic-film gate on the finished `video` of the shot-based film in `film_dir`
    (film/film-NN: shots/<scene>.json plans, stills/, voice/<scene>.wav, audio/film.mix.wav, audio/<scene>.mix.json
    with its "fx", and <film-NN>.vtt). Returns (checks {name: bool}, detail {name: ...}, not_run [reasons]):
    a gate whose inputs are not on disk is listed in not_run, never passed silently."""
    import tempfile
    from . import film
    film_dir = Path(film_dir)
    plans = [json.loads((film_dir / "shots" / f"{s}.json").read_text(encoding="utf-8")) for s in scene_ids]
    checks, detail, not_run = {}, {}, []
    gaps = new_info_gaps(video, NEW_INFO_SIM)
    held = hold_hashes(film_dir / "shots")
    bars, hitches = black_bars(video), frame_hitches(video)
    fl = flashes(video, planned_cuts(plans))
    detail.update(new_info_gaps=gaps, holds=held, black_bars=bars, hitches=hitches, flashes=fl)
    checks.update(new_info=not gaps, holds=not held, black_bars=not bars, hitches=not hitches,
                  flashes=fl["max_per_s"] <= FLASH_MAX_PER_S and not fl["unplanned"])
    missing = []
    for sid, sp in zip(scene_ids, plans):
        mj = film_dir / "audio" / f"{sid}.mix.json"
        fx_doc = json.loads(mj.read_text(encoding="utf-8")).get("fx") if mj.is_file() else None
        if fx_doc is None:
            if any((s.get("sound") or {}).get("sfx") for s in sp["shots"]):
                not_run.append(f"sound_on_picture: no cue fx recorded for scene {sid} (rerun cue)")
            continue
        base = Path(fx_doc.get("base", "."))
        fx = [{**e, "path": str(base / e["path"])} for k in ("ambience", "foley") for e in fx_doc.get(k, [])]
        missing += [f"{sid} {m}" for m in sound_on_picture(sp, fx)]
    if not any("sound_on_picture" in r for r in not_run):
        checks["sound_on_picture"] = not missing
        detail["sound_on_picture"] = missing
    vtt = film_dir / f"{film_dir.name}.vtt"
    if vtt.is_file():
        problems = check_captions(vtt.read_text(encoding="utf-8"), lang)
        checks["captions"], detail["captions"] = not problems, problems
    else:
        not_run.append(f"captions: {vtt.name} is not on disk")
    mixed, voices = film_dir / "audio" / "film.mix.wav", [film_dir / "voice" / f"{s}.wav" for s in scene_ids]
    if mixed.is_file() and all(v.is_file() for v in voices):
        with tempfile.TemporaryDirectory() as td:
            joined = film.join_scene_mixes(voices, film.scene_frames([sp["seconds"] for sp in plans]),
                                           Path(td) / "voice.wav")
            a = audio_gates(mixed, joined, shots=True)
        detail["audio"] = a
        checks.update(margin=a["margin_ok"], digital_zero=a["digital_zero_ok"])
    else:
        not_run.append("margin, digital_zero: the film mix or a scene voice is not on disk")
    return checks, detail, not_run
