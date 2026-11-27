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


def _placed(text, gaps, rate=0.2, breaths=()):
    """Pauses of a synthetic take of `text` spoken at `rate` s per character: gaps[i] seconds after clause i (an
    interior boundary), and each breath (clause index, fraction of that clause, seconds) inside its clause.
    Returns (pauses, bounds)."""
    cl = retime.clauses(text)
    t, out = 0.0, []
    for i, (c, _) in enumerate(cl):
        n = retime._spoken_len(c)
        inside = sorted((f, g) for k, f, g in breaths if k == i)
        done = 0.0
        for f, g in inside:
            t += (f - done) * n * rate
            out.append((round(t, 3), round(t + g, 3)))
            t += g
            done = f
        t += (1 - done) * n * rate
        if i < len(cl) - 1:
            out.append((round(t, 3), round(t + gaps[i], 3)))
            t += gaps[i]
    return out, (0.0, round(t, 3))


def test_targets_follow_punctuation():
    text = "এক, দুই। তিন! চার।"
    pauses, bounds = _placed(text, [0.2, 0.3, 0.5])
    plan = retime.plan_pauses(text, pauses, rng_seed=7, bounds=bounds)
    t = [p[2] for p in plan]
    assert 0.34 <= t[0] <= 0.63 and 0.68 <= t[1] <= 1.15 and 1.19 <= t[2] <= 1.84
    assert plan == retime.plan_pauses(text, pauses, rng_seed=7, bounds=bounds)


def test_tags_headings_and_unmatched_pauses():
    text = "[sad] এক।\nপরিচ্ছেদ ১\nদুই, তিন চার পাঁচ ছয়"
    pauses, bounds = _placed(text, [0.2, 0.3, 0.2], breaths=[(3, 0.3, 0.3), (3, 0.7, 0.4)])
    plan = retime.plan_pauses(text, pauses, 3, bounds=bounds)
    t = [p[2] for p in plan]
    assert 2.5 * 0.85 <= t[0] <= 3.0 * 1.15 and 1.5 * 0.85 <= t[1] <= 1.5 * 1.15
    assert 0.34 <= t[2] <= 0.63
    assert abs(t[3] - 0.3) < 1e-3 and abs(t[4] - 0.4) < 1e-3    # unpunctuated breaths keep their length


def test_breath_before_a_mark_never_takes_its_pause():
    """G3: a breath inside a clause is matched by position, not by order: it keeps its place and length, and the
    mark after it gets its own pause."""
    text = "এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ এগারো নাই! বারো তেরো চোদ্দ।"
    pauses, bounds = _placed(text, [1.6], breaths=[(0, 0.8, 0.3)])
    rows = retime.match_pauses(text, pauses, bounds)
    assert [(r["kind"], r["pause"]) for r in rows] == [("turn", 1)]
    plan = retime.plan_pauses(text, pauses, 1, bounds=bounds)
    assert abs(plan[0][2] - 0.3) < 1e-3                        # the breath stays a 0.3 s breath
    assert 1.19 <= plan[1][2] <= 1.84                          # the ! keeps its turn pause


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
        text = f"এক।\n{heading}\nদুই তিন চার"
        pauses, bounds = _placed(text, [0.2, 0.3], breaths=[(2, 0.5, 0.4)])
        plan = retime.plan_pauses(text, pauses, 5, bounds=bounds)
        t = [p[2] for p in plan]
        assert 2.5 * 0.85 <= t[0] <= 3.0 * 1.15, heading   # replaces the sentence end before it
        assert 1.5 * 0.85 <= t[1] <= 1.5 * 1.15, heading   # its own danda adds no extra pause
        assert abs(t[2] - 0.4) < 1e-3, heading             # nothing left to match: keeps its length


def test_prose_containing_chapter_word_is_not_a_heading():
    text = "আমি প্রথম পরিচ্ছেদ পড়লাম। তারপর ঘুমালাম।"
    pauses, bounds = _placed(text, [0.2])
    plan = retime.plan_pauses(text, pauses, 5, bounds=bounds)
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


# G3 regression: the owner-endorsed v4 take of বিচারক scene 14 (pilot/voice/v2/v4-retimed.wav, 51.92 s). Its pauses
# at -38 dB / 0.18 s as recorded in pilot/v5/ACCEPTANCE.md and measured on that take: the in-clause breaths after
# "তাহা", "রাত্রি", "প্রভাতে", "পতিত হইবে" and "সহসা" carry no punctuation. In-order mapping gave the breath after
# "তাহা" the "!" turn pause (1.51 s) and shrank the 1.6 s pause after "নাই!" to a comma.
V4_PAUSES = [(1.58, 2.03), (7.17, 8.17), (15.50, 15.80), (18.07, 19.67), (22.89, 23.44), (26.26, 26.86),
             (30.22, 30.44), (31.93, 32.58), (34.27, 34.59), (43.61, 44.31), (45.70, 45.88), (47.75, 48.45)]
V4_SPEECH, V4_LENGTH = (0.09, 51.83), 51.92


def test_endorsed_v4_take_keeps_the_held_breath_after_nai(tmp_path):
    import json
    from pathlib import Path
    from eav import passages
    text = json.loads((Path(__file__).parent / "fixtures" / "scene14.json").read_text(encoding="utf-8"))["scene"]["text"]
    t = np.arange(int(V4_LENGTH * SR)) / SR
    y = (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)        # 'speech' from the first word to the last
    for a, b in [(0.0, V4_SPEECH[0])] + V4_PAUSES + [(V4_SPEECH[1], V4_LENGTH)]:
        y[int(a * SR):int(b * SR)] = 0
    take = tmp_path / "v4.wav"
    retime.write(take, y)
    pauses = retime.detect_pauses(take)
    assert len(pauses) == len(V4_PAUSES)
    assert all(abs(p[0] - q[0]) < 0.02 and abs(p[1] - q[1]) < 0.02 for p, q in zip(pauses, V4_PAUSES))
    a, b = passages._bounds(retime.read(take))
    plan = retime.plan_pauses(text, pauses, 1, bounds=(a / SR, b / SR))
    target = {round(s, 1): t_ for s, _, t_ in plan}
    assert 1.4 * 0.85 <= target[18.1] <= 1.6 * 1.15                 # the held breath after "নাই!" stays a turn
    for breath, length in ((15.5, 0.30), (30.2, 0.22), (34.3, 0.32), (43.6, 0.70), (45.7, 0.18)):
        assert abs(target[breath] - length) < 0.02, breath           # unpunctuated breaths keep place and length
    kinds = [(r["kind"], r["pause"]) for r in retime.match_pauses(text, pauses, (a / SR, b / SR))]
    assert kinds == [("comma", 0), ("sentence", 1), ("turn", 3), ("comma", 4), ("comma", 5), ("comma", 7),
                     ("comma", 11)]
    out = retime.retime(take, tmp_path / "o.wav", plan, [16.0, 18.9])
    moved = retime.detect_pauses(tmp_path / "o.wav")
    nai = min(moved, key=lambda p: abs(p[0] - out["cuts"][1]))
    taha = min(moved, key=lambda p: abs(p[0] - out["cuts"][0]))
    assert nai[1] - nai[0] > 1.1 and taha[1] - taha[0] < 0.45       # never the other way round
