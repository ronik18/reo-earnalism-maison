"""Speech-ducked score mastering (ffmpeg subprocess + numpy envelope)."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import retime

RATE = 48000
TRUE_PEAK_LIMIT = -1.5   # loudnorm ceiling; leaves headroom under the -1.0 dBTP gate
SCORE_GAIN_DB = -12.0    # score sits this far under speech before ducking
CROSSFADE_S = 1.0


def _run(args, **kw):
    return subprocess.run(["ffmpeg", "-y", "-hide_banner", *args], check=True,
                          capture_output=True, text=kw.pop("text", True), **kw)


def loudnorm_stats(stderr: str) -> dict:
    """Parse the print_format=json block emitted by ffmpeg's loudnorm filter on stderr.

    Locates the last "[Parsed_loudnorm" marker, then the first "{" after it, and decodes one
    JSON object, ignoring any trailing text (ffmpeg 8 appends an output summary)."""
    i = stderr.rfind("[Parsed_loudnorm")
    j = stderr.find("{", i) if i >= 0 else -1
    if j < 0:
        raise ValueError("no loudnorm JSON block found in ffmpeg stderr")
    try:
        return json.JSONDecoder().raw_decode(stderr[j:])[0]
    except json.JSONDecodeError as e:
        raise ValueError(f"unparseable loudnorm JSON block: {e}") from e


def measure(path) -> dict:
    """Integrated loudness and true peak via ebur128."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        "ebur128=peak=true", "-f", "null", "-"],
                       check=True, capture_output=True, text=True)
    summary = r.stderr.rsplit("Summary:", 1)[-1]
    lufs = re.search(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    peak = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    if not lufs or not peak:
        raise RuntimeError("could not parse ebur128 output")
    lra = re.search(r"LRA:\s+(-?[\d.]+)\s+LU", summary)
    return {"lufs": float(lufs.group(1)), "true_peak": float(peak.group(1)),
            "lra": float(lra.group(1)) if lra else None}


FRAME = RATE // 100          # 10 ms analysis frames
CHUNK_FRAMES = 3000          # 30 s of audio per chunk (stereo float32 ~ 11 MB)


def _stream(path, chunk_samples: int):
    """Yield (n, 2) float32 chunks decoded by ffmpeg; memory stays bounded."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "2", "-ar", str(RATE), "-"],
                         stdout=subprocess.PIPE)
    try:
        while True:
            buf = p.stdout.read(chunk_samples * 8)
            if not buf:
                break
            yield np.frombuffer(buf, dtype=np.float32).reshape(-1, 2)
    finally:
        p.stdout.close()
        if p.wait() != 0:
            raise RuntimeError(f"ffmpeg failed decoding {path}")


def _writer(path):
    return subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(RATE),
                             "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", str(path)],
                            stdin=subprocess.PIPE)


def _close(w):
    w.stdin.close()
    if w.wait() != 0:
        raise RuntimeError("ffmpeg failed writing audio")


def _frame_gain_db(speech: Path, duck_db: float) -> np.ndarray:
    """Per-10ms-frame gain in dB (0 in pauses, -duck_db while speech plays), float32."""
    levels = []
    for chunk in _stream(speech, CHUNK_FRAMES * FRAME):
        frames = len(chunk) // FRAME
        if frames:
            x = np.abs(chunk[:frames * FRAME]).max(axis=1).reshape(frames, FRAME)
            levels.append(np.sqrt((x * x).mean(axis=1)))
    rms = np.concatenate(levels) if levels else np.zeros(0, dtype=np.float32)
    active = (rms > 10 ** (-50 / 20)).astype(np.float32)
    # close (dilate 300 ms, erode 150 ms): bridges gaps under 300 ms, holds 150 ms
    dil = np.convolve(active, np.ones(30, dtype=np.float32), mode="same") > 0
    held = np.convolve(dil.astype(np.float32), np.ones(15, dtype=np.float32),
                       mode="same") >= 15
    held = held | (active > 0)
    target = np.where(held, -duck_db, 0.0).astype(np.float32)
    k = 15  # 150 ms ramps
    pad = np.pad(target, (k // 2, k - k // 2 - 1), mode="edge")
    smooth = np.convolve(pad, np.ones(k, dtype=np.float32) / k, mode="valid")
    smooth = np.where(held, np.minimum(smooth, target), smooth)
    return smooth.astype(np.float32)


def _gain_for(start: int, n: int, frame_db: np.ndarray) -> np.ndarray:
    """Linear float32 gain for samples [start, start+n), interpolated from frame gains."""
    if not len(frame_db):
        return np.ones(n, dtype=np.float32)
    centers = np.arange(len(frame_db), dtype=np.float32) * FRAME + FRAME / 2
    idx = np.arange(start, start + n, dtype=np.float32)
    db = np.interp(idx, centers, frame_db).astype(np.float32)
    return (10 ** (db / 20)).astype(np.float32)


def duck_and_master(speech: Path, score: Path, out: Path, target_lufs: float,
                    duck_db=19) -> dict:
    if not 18 <= duck_db <= 20:
        raise ValueError("duck_db must be within 18-20 dB")
    speech, score, out = Path(speech), Path(score), Path(out)
    frame_db = _frame_gain_db(speech, duck_db)
    score_gain = np.float32(10 ** (SCORE_GAIN_DB / 20))
    chunk = CHUNK_FRAMES * FRAME
    stem = out.with_name(out.stem + ".score-ducked.wav")

    def pad(a, n):
        return a if a is None else np.pad(a, ((0, n - len(a)), (0, 0)))

    with tempfile.TemporaryDirectory() as td:
        pre = Path(td) / "pre.wav"
        w_stem, w_pre = _writer(stem), _writer(pre)
        try:
            gs, gc, pos = _stream(speech, chunk), _stream(score, chunk), 0
            while True:
                a, b = next(gs, None), next(gc, None)
                if a is None and b is None:
                    break
                n = max(len(a) if a is not None else 0, len(b) if b is not None else 0)
                a = np.zeros((n, 2), np.float32) if a is None else pad(a, n)
                b = np.zeros((n, 2), np.float32) if b is None else pad(b, n)
                b = b * score_gain * _gain_for(pos, n, frame_db)[:, None]
                w_stem.stdin.write(b.astype(np.float32).tobytes())
                w_pre.stdin.write((a + b).astype(np.float32).tobytes())
                pos += n
        finally:
            _close(w_stem)
            _close(w_pre)
        res = _loudnorm_gated(pre, out, target_lufs)
    res.update({"score_stem": str(stem), "duck_db": duck_db, "target_lufs": target_lufs})
    return res


def _loudnorm_gated(pre: Path, out: Path, target_lufs: float, tp: float = TRUE_PEAK_LIMIT,
                    tp_max: float = -1.0, channels: int = 2) -> dict:
    """Two-pass linear loudnorm to target_lufs; raises ValueError unless the result meets
    target +-1 LU and true peak <= tp_max (-1.0 dBTP by default)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(pre), "-af",
                        f"loudnorm=I={target_lufs}:TP={tp}:LRA=11:print_format=json",
                        "-f", "null", "-"], check=True, capture_output=True, text=True)
    stats = loudnorm_stats(r.stderr)
    if any(str(stats[k]).strip("-+").lower() in ("inf", "nan") for k in ("input_i", "input_tp")):
        raise ValueError("master misses gate: input is silent or unmeasurable")
    f = (f"loudnorm=I={target_lufs}:TP={tp}:LRA=11:"
         f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
         f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
         f"offset={stats['target_offset']}:linear=true")
    _run(["-i", str(pre), "-af", f, "-ar", str(RATE), "-ac", str(channels),
          "-c:a", "pcm_s16le", str(out)])
    res = measure(out)
    if res["true_peak"] > tp_max or abs(res["lufs"] - target_lufs) > 1:
        raise ValueError(f"master misses gate: {res} (target {target_lufs} LUFS, TP <= {tp_max})")
    return res


def master(speech: Path, out: Path, target_lufs: float) -> dict:
    """Narration-only master with the same gate as duck_and_master (no score)."""
    res = _loudnorm_gated(Path(speech), Path(out), target_lufs)
    res["target_lufs"] = target_lufs
    return res


def arrange_cues(cues: list, boundaries_s: list, total_s: float, out: Path):
    """Place cue i at boundaries_s[i], crossfading into the next; loop short cues."""
    if not cues or len(cues) != len(boundaries_s):
        raise ValueError("cues and boundaries_s must be non-empty and the same length")
    b = [float(x) for x in boundaries_s]
    if b[0] < 0 or any(y <= x for x, y in zip(b, b[1:])) or b[-1] >= total_s:
        raise ValueError("boundaries must be increasing, >= 0 and before total_s")
    args, parts, labels = [], [], []
    for i, cue in enumerate(cues):
        end = b[i + 1] if i + 1 < len(b) else total_s
        xf = min(CROSSFADE_S, (end - b[i]) / 2)
        last = i == len(cues) - 1
        length = end - b[i] + (0 if last else xf)
        args += ["-stream_loop", "-1", "-i", str(cue)]
        f = (f"[{i}:a]aformat=sample_rates={RATE}:channel_layouts=stereo,"
             f"atrim=0:{length:.3f},asetpts=PTS-STARTPTS")
        if i > 0:
            f += f",afade=t=in:d={min(CROSSFADE_S, (b[i] - b[i - 1]) / 2):.3f}"
        if not last:
            f += f",afade=t=out:st={length - xf:.3f}:d={xf:.3f}"
        f += f",adelay={int(round(b[i] * 1000))}:all=1[a{i}]"
        parts.append(f)
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"amix=inputs={len(cues)}:normalize=0:duration=longest,"
                 f"apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f}[o]")
    _run([*args, "-filter_complex", ";".join(parts), "-map", "[o]", "-ar", str(RATE),
          "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    return Path(out)


# ---- audiobook master (Listen, spec section 9) -------------------------------------------------
AUDIOBOOK_LUFS = -18.0          # +-1 LU
AUDIOBOOK_TP_MAX = -2.0         # dBTP, measured on the encoded file
AUDIOBOOK_PRE_TP = -3.0         # loudnorm ceiling before the lossy encode (mp3 overshoots a little)
LRA_LU = (4.0, 8.0)             # loudness range gate on the encoded file
AUDIOBOOK_KBPS = 64             # mono, encoded once from PCM
BED_UNDER_VOICE_LU = 24.0       # an unducked bed sits at least this far under the voice
BED_DUCK_DB, BED_ATTACK_S, BED_HOLD_S, BED_RELEASE_S = 6.0, 0.05, 0.5, 1.5
BED_FADE_IN_S = 0.5
BED_ACTIVE_DB = -50.0           # voice frames above this duck the bed (room tone is far below)
OPEN_LEAD_S, OPEN_GAP_S, BODY_LEAD_S = 1.0, 0.8, 1.5   # room tone before/between title+author, before the body
CLOSE_GAP_S, TAIL_S, PART_TAIL_S = 2.0, 3.0, 0.5       # before the closing word, after it (book end), after a part
INTRO_BED_AFTER_S, PART_BED_AFTER_S, OUTRO_BED_BEFORE_S = 4.0, 6.0, 2.0


def _bed_gain_db(active: np.ndarray, frame_s: float = 0.01) -> np.ndarray:
    """Per-frame bed gain: ducks BED_DUCK_DB within BED_ATTACK_S of speech, holds BED_HOLD_S after it, then
    recovers linearly over BED_RELEASE_S. A pause of up to ~1.25 s therefore moves the bed by under 3 dB."""
    attack = BED_DUCK_DB / (BED_ATTACK_S / frame_s)
    release = BED_DUCK_DB / (BED_RELEASE_S / frame_s)
    hold, g, quiet = int(BED_HOLD_S / frame_s), 0.0, 10 ** 9
    out = np.empty(len(active), np.float32)
    for i, a in enumerate(active):
        if a:
            quiet, g = 0, max(g - attack, -BED_DUCK_DB)
        else:
            quiet += 1
            if quiet > hold:
                g = min(g + release, 0.0)
        out[i] = g
    return out


def _bed_window(bed: Path, n: int, fade_out_s: float) -> np.ndarray:
    """n mono samples of the bed (looped when short), faded in over BED_FADE_IN_S and out over the release."""
    y = retime.read(bed)
    if not len(y):
        raise ValueError(f"empty score bed {bed}")
    y = np.tile(y, n // len(y) + 1)[:n].astype(np.float32)
    fi, fo = min(int(BED_FADE_IN_S * RATE), n // 2), min(int(fade_out_s * RATE), n // 2)
    y[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)
    if fo:
        y[n - fo:] *= np.linspace(1, 0, fo, dtype=np.float32)
    return y


def _lufs(y: np.ndarray, td: Path, name: str) -> float:
    path = Path(td) / name
    retime.write(path, y)
    return measure(path)["lufs"]


def master_audiobook(narration: Path, cues: dict, out: Path) -> dict:
    """The audiobook master of one part: mono 64 kbps MP3 encoded once from PCM at -18 LUFS +-1, true peak
    <= -2 dBTP and LRA 4-8 LU, all measured on the encoded file (ValueError when a gate is missed).

    narration is the part's narration track (mono WAV). cues, all optional:
      opening   [title.wav, author.wav]  spoken before the body (room tone between)
      closing   the closing word's WAV, after CLOSE_GAP_S of room tone, then TAIL_S of room tone (book end)
      intro / part / outro   score bed WAVs: the only places music plays (opening, part change, closing)
    Beds are loudness-matched BED_UNDER_VOICE_LU under the voice, ducked BED_DUCK_DB under speech with a
    BED_RELEASE_S release. Returns the measured numbers, where the narration starts in the master
    (voice_offset_s, to be added to every narration timestamp) and the bed stem (<out>.bed.wav)."""
    narration, out, cues = Path(narration), Path(out), dict(cues or {})
    x = retime.read(narration)
    tone = lambda seconds: retime.room_tone(x, int(round(seconds * RATE)))
    xf = int(retime.XF_S * RATE)
    acc = np.zeros(0, np.float32)
    opening = [Path(p) for p in cues.get("opening") or []]

    def add(piece):  # 40 ms equal-power joins: no click, no digital zero; returns where the piece starts
        nonlocal acc
        start = max(len(acc) - xf, 0)
        acc = retime._crossfade(acc, piece, xf) if len(acc) else piece.copy()
        return start

    if opening:
        add(tone(OPEN_LEAD_S))
        for p in opening:
            add(retime.read(p))
            add(tone(OPEN_GAP_S))
        add(tone(BODY_LEAD_S - OPEN_GAP_S))
    elif cues.get("part") or cues.get("intro"):
        add(tone(BODY_LEAD_S))
    voice_start = add(x)
    voice_end = len(acc)
    closing_start = None
    if cues.get("closing"):
        add(tone(CLOSE_GAP_S))
        closing_start = add(retime.read(Path(cues["closing"])))
        add(tone(TAIL_S))
    else:
        add(tone(PART_TAIL_S))
    total = len(acc)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pre, voice = td / "pre.wav", td / "voice.wav"
        retime.write(pre, acc)
        _loudnorm_gated(pre, voice, AUDIOBOOK_LUFS, tp=AUDIOBOOK_PRE_TP, tp_max=AUDIOBOOK_TP_MAX, channels=1)
        v = retime.read(voice)
        n = min(len(v), total)
        v = v[:n]
        voice_lufs = measure(voice)["lufs"]
        # bed windows: the opening (intro) or a part change (part) at the start, the closing (outro) at the end
        windows = []
        head = cues.get("intro") or cues.get("part")
        if head:
            windows.append((head, 0, voice_start + int((INTRO_BED_AFTER_S if cues.get("intro") else PART_BED_AFTER_S) * RATE)))
        if cues.get("outro") and closing_start is not None:
            windows.append((cues["outro"], max(closing_start - int(OUTRO_BED_BEFORE_S * RATE), voice_end), n))
        frame = RATE // 100
        frames = n // frame
        rms = np.sqrt((v[:frames * frame].reshape(frames, frame) ** 2).mean(axis=1)) if frames else np.zeros(0)
        duck = _gain_for(0, n, _bed_gain_db(rms > 10 ** (BED_ACTIVE_DB / 20)))
        bed, nominal = np.zeros(n, np.float32), []
        for path, a, b in windows:
            b = min(b, n)
            if b - a < 3 * RATE:
                continue
            w = _bed_window(path, b - a, BED_RELEASE_S)
            w *= np.float32(10 ** ((voice_lufs - BED_UNDER_VOICE_LU - _lufs(w, td, "bed.wav")) / 20))
            nominal.append(_lufs(w, td, "bednom.wav"))
            bed[a:b] += w
        bed *= duck
        bed_under = round(voice_lufs - max(nominal), 2) if nominal else None
        if nominal and bed_under < BED_UNDER_VOICE_LU - 0.1:
            raise ValueError(f"master misses gate: bed only {bed_under} LU under the voice")
        gain_db, res = 0.0, {}
        for _ in range(4):  # a lossy encode can overshoot: trim the level and re-encode from the PCM
            g = np.float32(10 ** (gain_db / 20))
            mixed = td / "mixed.wav"
            retime.write(mixed, np.clip((v + bed) * g, -1.0, 1.0))
            _run(["-i", str(mixed), "-ac", "1", "-ar", str(RATE), "-c:a", "libmp3lame",
                  "-b:a", f"{AUDIOBOOK_KBPS}k", str(out)])
            res = measure(out)
            if res["true_peak"] > AUDIOBOOK_TP_MAX:
                gain_db -= res["true_peak"] - AUDIOBOOK_TP_MAX + 0.2
            elif abs(res["lufs"] - AUDIOBOOK_LUFS) > 1:
                gain_db += AUDIOBOOK_LUFS - res["lufs"]
            else:
                break
        if res["true_peak"] > AUDIOBOOK_TP_MAX or abs(res["lufs"] - AUDIOBOOK_LUFS) > 1:
            raise ValueError(f"master misses gate: {res} (target {AUDIOBOOK_LUFS} LUFS, TP <= {AUDIOBOOK_TP_MAX})")
        if res["lra"] is None or not LRA_LU[0] <= res["lra"] <= LRA_LU[1]:
            raise ValueError(f"master misses gate: LRA {res['lra']} LU outside {LRA_LU[0]}-{LRA_LU[1]} LU")
        stem = out.with_name(out.stem + ".bed.wav")
        retime.write(stem, bed * g)
    res.update({"voice_lufs": round(voice_lufs + gain_db, 2), "bed_under_voice_lu": bed_under,
                "duck_db": BED_DUCK_DB, "release_s": BED_RELEASE_S, "bed_stem": str(stem),
                "voice_offset_s": round(voice_start / RATE, 3),
                "closing_start_s": None if closing_start is None else round(closing_start / RATE, 3),
                "duration_s": round(total / RATE, 3), "encoder": f"libmp3lame {AUDIOBOOK_KBPS} kbps CBR mono"})
    return res
