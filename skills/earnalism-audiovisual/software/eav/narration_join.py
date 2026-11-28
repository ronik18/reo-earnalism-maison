"""Join the separately synthesized segments of one voice unit into the unit's single WAV.

The narration notebook embeds this file's source verbatim (colab_jobs._notebook), so the code the
GPU runs is the code the tests exercise. It needs only numpy. A unit without segments is never
passed through here: its WAV is written exactly as before (dry, nothing added).

Between two segments (a narrator line and a character line, or two speakers) it inserts
SEGMENT_GAP_MS of silence, a short natural breath between voices, and fades the touching edges in
and out over EDGE_FADE_MS so the cut to silence never clicks. The unit's outer start and end are
left untouched, so measured unit ends stay speech ends (film.narration_track adds every pause
between units, once).

Expressive titles (eav.expressive, a cast.json with `tone`) pass each gap's length (gaps_ms, from
the unit's job row) and room-tone settings (room): the gap is then a soft, deterministic room-tone
bed (room_tone) instead of digital silence. film.narration_track uses the same room_tone between
units of such a title.
"""
SEGMENT_GAP_MS = 150
EDGE_FADE_MS = 5


def room_tone(n, rate, dbfs=-62.0, seed=0, fade_ms=10, smooth_ms=0.5):
    """n samples of soft room tone at `dbfs` RMS: splitmix64 noise of the sample index (the same
    on every machine and numpy version), smoothed by a Hann kernel of smooth_ms, with fade_ms
    raised-cosine fades in and out. Deterministic for (n, rate, dbfs, seed, fade_ms, smooth_ms)."""
    import numpy as np
    n = int(n)
    if n <= 0:
        return np.zeros(0, dtype="float32")
    with np.errstate(over="ignore"):
        x = np.arange(n, dtype=np.uint64) * np.uint64(0x9E3779B97F4A7C15) \
            + np.uint64(int(seed) & 0xFFFFFFFFFFFFFFFF)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        x = x ^ (x >> np.uint64(31))
    noise = (x >> np.uint64(11)).astype(np.float64) / float(1 << 53) * 2.0 - 1.0
    k = max(1, int(round(rate * smooth_ms / 1000)))
    if k > 1:
        kernel = np.hanning(k + 2)[1:-1]
        noise = np.convolve(noise, kernel / kernel.sum(), mode="same")
    rms = float(np.sqrt(np.mean(noise ** 2)))
    if rms > 0:
        noise = noise * (10 ** (dbfs / 20.0) / rms)
    f = min(int(round(rate * fade_ms / 1000)), n // 2)
    if f:
        ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(f) + 0.5) / f)
        noise[:f] *= ramp
        noise[-f:] *= ramp[::-1]
    return noise.astype("float32")


def join_segments(wavs, rate, gap_ms=SEGMENT_GAP_MS, fade_ms=EDGE_FADE_MS, gaps_ms=None, room=None):
    """wavs: the segments' mono samples in order (each already trimmed to its generated length).
    gaps_ms: one gap per pair of segments (else gap_ms for every gap); room: room-tone settings
    {"dbfs", "seed", "fade_ms", "smooth_ms"} (gap k seeded seed + k), else the gaps are silence.
    Returns (joined float32 samples, [seconds of each segment as generated])."""
    import numpy as np
    parts = [np.asarray(w, dtype="float32").reshape(-1).copy() for w in wavs]
    if not parts:
        raise ValueError("a joined unit needs at least one segment")
    seconds = [round(len(p) / float(rate), 3) for p in parts]
    if len(parts) == 1:
        return parts[0], seconds
    gaps = list(gaps_ms) if gaps_ms is not None else [gap_ms] * (len(parts) - 1)
    if len(gaps) != len(parts) - 1:
        raise ValueError(f"{len(parts)} segments need {len(parts) - 1} gaps, not {len(gaps)}")
    fade = int(rate * fade_ms / 1000)
    out = []
    for i, p in enumerate(parts):
        k = min(fade, len(p) // 2)
        if k:
            ramp = (np.arange(k, dtype="float32") + 0.5) / k  # 0 -> 1, never exactly 1 at the edge
            if i > 0:
                p[:k] *= ramp
            if i < len(parts) - 1:
                p[-k:] *= ramp[::-1]
        out.append(p)
        if i < len(parts) - 1:
            n = int(round(rate * gaps[i] / 1000))
            if room:
                out.append(room_tone(n, rate, room.get("dbfs", -62.0), int(room.get("seed", 0)) + i,
                                     room.get("fade_ms", 10), room.get("smooth_ms", 0.5)))
            else:
                out.append(np.zeros(n, dtype="float32"))
    return np.concatenate(out).astype("float32"), seconds


def joined_seconds(segment_seconds, gap_ms=SEGMENT_GAP_MS, gaps_ms=None):
    """The length a joined unit has: its segments plus one gap between each pair (gaps_ms: the
    unit's own gaps, as its job row carries them)."""
    if gaps_ms is not None:
        return sum(segment_seconds) + sum(gaps_ms[:max(0, len(segment_seconds) - 1)]) / 1000
    return sum(segment_seconds) + max(0, len(segment_seconds) - 1) * gap_ms / 1000
