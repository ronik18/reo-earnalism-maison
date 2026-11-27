import numpy as np

from eav import retime
from eav.retime import SR
from tests._media import rms_db, samples


def _take(path, gaps=(0.2, 0.5), burst=0.6):
    """220 Hz 'speech' bursts separated by digital-silence gaps; returns the (start, end) of each gap."""
    t = np.arange(int(burst * SR)) / SR
    b = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    parts, spans, pos = [b], [], burst
    for g in gaps:
        parts += [np.zeros(int(g * SR), np.float32), b]
        spans.append((pos, pos + g))
        pos += g + burst
    retime.write(path, np.concatenate(parts))
    return spans


def test_room_tone_never_digital_zero(tmp_path):
    src = tmp_path / "t.wav"
    (g1, g2) = _take(src)
    out = tmp_path / "o.wav"
    retime.retime(src, out, [(g1[0], g1[1], 1.0), (g2[0], g2[1], 1.0)], [])
    y = samples(out)
    win = int(0.02 * SR)
    assert min(rms_db(y[i:i + win]) for i in range(0, len(y) - win, win)) > -80
    longest = run = 0
    for v in (y == 0):
        run = run + 1 if v else 0
        longest = max(longest, run)
    assert longest < 0.05 * SR
    tone = retime.room_tone(samples(src), SR)
    assert -68.5 <= rms_db(tone) <= -61.5


def test_targets_follow_punctuation():
    plan = retime.plan_pauses("এক, দুই। তিন!", [(1, 1.2), (2, 2.3), (3, 3.5)], rng_seed=7)
    t = [p[2] for p in plan]
    assert 0.34 <= t[0] <= 0.63 and 0.68 <= t[1] <= 1.15 and 1.19 <= t[2] <= 1.84
    assert plan == retime.plan_pauses("এক, দুই। তিন!", [(1, 1.2), (2, 2.3), (3, 3.5)], rng_seed=7)


def test_tags_headings_and_unmatched_pauses():
    plan = retime.plan_pauses("[sad] এক।\nপরিচ্ছেদ ১\nদুই, তিন", [(1, 1.2), (2, 2.3), (3, 3.2), (4, 4.3), (5, 5.4)], 3)
    t = [p[2] for p in plan]
    assert 2.5 * 0.85 <= t[0] <= 3.0 * 1.15 and 1.5 * 0.85 <= t[1] <= 1.5 * 1.15
    assert 0.34 <= t[2] <= 0.63
    assert abs(t[3] - 0.3) < 1e-3 and abs(t[4] - 0.4) < 1e-3


def test_cut_mapping_moves_with_inserted_time(tmp_path):
    src = tmp_path / "t.wav"
    g1, g2 = _take(src)
    pauses = retime.detect_pauses(src)
    assert len(pauses) == 2 and abs(pauses[1][0] - g2[0]) < 0.02
    plan = [(g1[0], g1[1], 0.5), (g2[0], g2[1], 1.2)]
    res = retime.retime(src, tmp_path / "o.wav", plan, [(g2[0] + g2[1]) / 2])
    new_mid = 0.6 + 0.5 + 0.6 + 1.2 / 2
    assert abs(res["cuts"][0] - new_mid) < 0.01
    assert abs(res["duration"] - (0.6 * 3 + 0.5 + 1.2)) < 0.01


def test_retime_no_pauses_is_identity(tmp_path):
    src = tmp_path / "t.wav"
    _take(src)
    res = retime.retime(src, tmp_path / "o.wav", [], [1.0])
    assert abs(res["duration"] - len(samples(src)) / SR) < 0.001
    assert res["cuts"] == [1.0]


def test_no_click_at_joins(tmp_path):
    src = tmp_path / "t.wav"
    g1, g2 = _take(src)
    plan = [(g1[0], g1[1], 0.5), (g2[0], g2[1], 1.2)]
    out = tmp_path / "o.wav"
    retime.retime(src, out, plan, [])
    y = samples(out)
    for start, length in ((0.6, 0.5), (0.6 + 0.5 + 0.6, 1.2)):
        for lo, hi in ((start, start + 0.04), (start + length - 0.04, start + length - 0.002)):
            seg = y[int(lo * SR):int(hi * SR)]  # the two 40 ms crossfade zones of this pause
            assert float(np.max(np.abs(np.diff(seg)))) < 10 ** (-50 / 20)


def test_ordinal_chapter_headings_are_headings():
    for heading in ("প্রথম পরিচ্ছেদ।", "দ্বিতীয় পরিচ্ছেদ", "# তৃতীয় পরিচ্ছেদ।"):
        plan = retime.plan_pauses(f"এক।\n{heading}\nদুই", [(1, 1.2), (2, 2.3), (3, 3.4)], 5)
        t = [p[2] for p in plan]
        assert 2.5 * 0.85 <= t[0] <= 3.0 * 1.15, heading   # replaces the sentence end before it
        assert 1.5 * 0.85 <= t[1] <= 1.5 * 1.15, heading   # its own danda adds no extra pause
        assert abs(t[2] - 0.4) < 1e-3, heading             # nothing left to match: keeps its length


def test_prose_containing_chapter_word_is_not_a_heading():
    plan = retime.plan_pauses("আমি প্রথম পরিচ্ছেদ পড়লাম।", [(1, 1.2)], 5)
    assert 0.68 <= plan[0][2] <= 1.15


def test_chapter_length_take_retimes_in_bounded_time(tmp_path):
    import time
    t = np.arange(int(2.5 * SR)) / SR
    burst = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    gap = np.zeros(int(0.5 * SR), np.float32)
    src = tmp_path / "long.wav"
    retime.write(src, np.concatenate([np.concatenate([burst, gap]) for _ in range(200)]))
    plan = [(3.0 * i + 2.5, 3.0 * i + 3.0, 0.9) for i in range(199)]
    t0 = time.time()
    res = retime.retime(src, tmp_path / "o.wav", plan, [])
    assert time.time() - t0 < 20
    assert abs(res["duration"] - (600 - 199 * 0.5 + 199 * 0.9)) < 0.05
