"""Join the separately synthesized segments of one voice unit into the unit's single WAV.

The narration notebook embeds this file's source verbatim (colab_jobs._notebook), so the code the
GPU runs is the code the tests exercise. It needs only numpy. A unit without segments is never
passed through here: its WAV is written exactly as before (dry, nothing added).

Between two segments (a narrator line and a character line, or two speakers) it inserts
SEGMENT_GAP_MS of silence, a short natural breath between voices, and fades the touching edges in
and out over EDGE_FADE_MS so the cut to silence never clicks. The unit's outer start and end are
left untouched, so measured unit ends stay speech ends (film.narration_track adds every pause
between units, once).
"""
SEGMENT_GAP_MS = 150
EDGE_FADE_MS = 5


def join_segments(wavs, rate, gap_ms=SEGMENT_GAP_MS, fade_ms=EDGE_FADE_MS):
    """wavs: the segments' mono samples in order (each already trimmed to its generated length).
    Returns (joined float32 samples, [seconds of each segment as generated])."""
    import numpy as np
    parts = [np.asarray(w, dtype="float32").reshape(-1).copy() for w in wavs]
    if not parts:
        raise ValueError("a joined unit needs at least one segment")
    seconds = [round(len(p) / float(rate), 3) for p in parts]
    if len(parts) == 1:
        return parts[0], seconds
    fade = int(rate * fade_ms / 1000)
    gap = np.zeros(int(round(rate * gap_ms / 1000)), dtype="float32")
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
            out.append(gap)
    return np.concatenate(out).astype("float32"), seconds


def joined_seconds(segment_seconds, gap_ms=SEGMENT_GAP_MS):
    """The length a joined unit has: its segments plus one gap between each pair."""
    return sum(segment_seconds) + max(0, len(segment_seconds) - 1) * gap_ms / 1000
