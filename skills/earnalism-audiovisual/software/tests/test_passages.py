import numpy as np
import pytest

from eav import passages, retime
from eav.retime import SR
from eav.voicecheck import _zero_run_s
from tests._media import rms_db, samples
from tests.test_take import tone

CPS = 10.0


def _sentence(i, chars=40):
    base = f"এই বাক্য {i:02d} ছোট কথা"
    return (base + " " + "ক" * (chars - len(base) - 2))[:chars - 1] + "।"


def _est(p, cps=CPS):
    return len(p.strip()) / cps


def test_split_passages_15_to_30s_at_sentence_or_paragraph_ends():
    text = " ".join(_sentence(i) for i in range(30))  # 30 sentences of 4 s
    ps = passages.split_passages(text, cps=CPS)
    assert len(ps) > 3
    for p in ps:
        assert 15 <= _est(p) <= 30, _est(p)
        assert p.rstrip()[-1] == "।"  # never mid-sentence
    # a paragraph end closes a passage that already holds 15 s
    para = " ".join(_sentence(i) for i in range(5))
    two = para + "\n\n" + " ".join(_sentence(i) for i in range(5, 10))
    ps = passages.split_passages(two, cps=CPS)
    assert [p.strip() for p in ps] == [para, " ".join(_sentence(i) for i in range(5, 10))]


def test_split_passages_keeps_a_long_sentence_whole_and_a_short_scene_as_one():
    long = ("ক" * 399) + "।"  # 40 s at 10 cps: never cut inside a sentence
    assert passages.split_passages(long, cps=CPS) == [long]
    assert passages.split_passages(_sentence(1), cps=CPS) == [_sentence(1)]
    assert passages.split_passages("", cps=CPS) == []


def test_passages_reproduce_scene_text_exactly():
    text = ("  " + "\n\n".join(" ".join(_sentence(10 * k + i) for i in range(6)) for k in range(4))
            + "  \nশেষ লাইন ছাড়া দাঁড়ি")
    ps = passages.split_passages(text, cps=CPS)
    assert "".join(ps) == text


def test_default_rate_is_documented_and_a_parameter():
    assert passages.CPS_BN == 13.0
    text = " ".join(_sentence(i) for i in range(30))
    assert len(passages.split_passages(text, cps=40.0)) < len(passages.split_passages(text, cps=10.0))


SCENE = "প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে। তৃতীয় বাক্য এখানে।"


def test_script_check_rebuilds_the_scene_text_and_returns_plain_passages():
    got = passages.check_passage_scripts(SCENE, ["প্রথম বাক্য এখানে। [pause] দ্বিতীয় বাক্য এখানে।",
                                                 "[warmly] তৃতীয় বাক্য এখানে।"])
    assert got == ["প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে।", "তৃতীয় বাক্য এখানে।"]


@pytest.mark.parametrize("scripts, why", [
    (["প্রথম বাক্য এখানে।", "তৃতীয় বাক্য এখানে।"], "differ|missing|scene text"),
    (["প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে।", "তৃতীয় বাক্য এখানে। বাড়তি।"], "differ|extra"),
    (["প্রথম বাক্য এখানে। দ্বিতীয় বাক্য", "এখানে। তৃতীয় বাক্য এখানে।"], "mid-sentence|sentence end"),
    (["[sad] প্রথম বাক্য [slowly] এখানে। দ্বিতীয় বাক্য এখানে। তৃতীয় বাক্য এখানে।"], "one audio tag per sentence"),
    (["[softly] প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে। তৃতীয় বাক্য এখানে।"], "bare \\[softly\\]"),
    (["[sad] প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে।", "তৃতীয় বাক্য এখানে।"], "carry"),
])
def test_script_check_refuses(scripts, why):
    with pytest.raises(ValueError, match=why):
        passages.check_passage_scripts(SCENE, scripts)


def test_script_check_allows_the_carried_mood_and_a_deliberate_change():
    two = ["[sad] প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে।", "[sad] তৃতীয় বাক্য এখানে।"]
    passages.check_passage_scripts(SCENE, two)
    passages.check_passage_scripts(SCENE, [two[0], "[angry] তৃতীয় বাক্য এখানে।"])
    # [pause] is not a mood: nothing to carry
    passages.check_passage_scripts(SCENE, ["প্রথম বাক্য এখানে। দ্বিতীয় বাক্য এখানে। [pause]", "তৃতীয় বাক্য এখানে।"])
    # a carried [softly] is the mood, not a bare opening
    passages.check_passage_scripts(SCENE, ["প্রথম বাক্য [softly] এখানে।", "[softly] দ্বিতীয় বাক্য এখানে। তৃতীয় বাক্য এখানে।"])


def _passage_wav(path, seconds, freq, edge_zero=0.3):
    z = np.zeros(int(edge_zero * SR))
    retime.write(path, np.concatenate([z, tone(seconds, freq), z]).astype(np.float32))


def test_join_uses_room_tone_and_40ms_crossfade_no_digital_zero(tmp_path):
    # passages with floors of digital zero at both edges (what a raw take must never leave at a join)
    takes = []
    for i, f in enumerate((200, 260, 220)):
        p = tmp_path / f"p{i}.wav"
        _passage_wav(p, 1.0, f)
        takes.append(p)
    out = tmp_path / "scene.wav"
    info = passages.join_passages(takes, out)
    y = samples(out)
    assert info["passages"] == 3 and info["crossfade_ms"] == 40 and len(info["seams"]) == 2   # I7: 30-50 ms
    assert 0.030 <= passages.XF_S <= 0.050 and passages.EDGE_KEEP_S >= 2 * passages.XF_S
    assert abs(info["duration"] - len(y) / SR) < 0.01
    # no run of digital zero inside the seams (the outer edges are the takes' own)
    for s in info["seams"]:
        a, b = int((s["at"] - 0.3) * SR), int((s["at"] + 0.3) * SR)
        assert _zero_run_s(y[a:b]) < 0.012
        mid = y[int((s["at"] - 0.2) * SR):int((s["at"] + 0.2) * SR)]
        assert -69 <= rms_db(mid) <= -61  # room tone level, -62...-68 dBFS
    # the seam holds about seam_s of room tone between the speech
    assert 0.8 <= info["seams"][0]["length_s"] <= 1.1


def test_join_single_passage_is_a_copy_and_empty_is_refused(tmp_path):
    p = tmp_path / "p.wav"
    _passage_wav(p, 1.0, 200)
    out = tmp_path / "o.wav"
    info = passages.join_passages([p], out)
    assert info["seams"] == [] and out.is_file()
    with pytest.raises(ValueError):
        passages.join_passages([], out)


def test_seams_follow_the_final_punctuation_with_seeded_jitter():
    plains = ["প্রথম বাক্য এখানে।", "দ্বিতীয় কি?", "তৃতীয় থামো!", "চতুর্থ।"]
    ids = ["s-p01", "s-p02", "s-p03", "s-p04"]
    a = passages.seam_lengths(plains, ids)
    assert a == passages.seam_lengths(plains, ids)                      # seeded: repeatable
    assert 0.8 * 0.85 <= a[0] <= 1.15 and 0.8 * 0.85 <= a[1] <= 1.15     # । and ? : 0.8-1.0 s +-15 %
    assert 1.4 * 0.85 <= a[2] <= 1.6 * 1.15 and a[2] > 1.15             # ! : 1.4-1.6 s +-15 %
    heading = passages.seam_lengths(["এক।", "পরিচ্ছেদ শুরু। কথা।"], ["a", "b"], headings=["পরিচ্ছেদ শুরু।"])
    assert 2.5 * 0.85 <= heading[0] <= 3.0 * 1.15


def test_a_passage_ending_in_exclamation_gets_a_longer_seam_in_the_joined_wav(tmp_path):
    takes = []
    for i, f in enumerate((200, 260)):
        p = tmp_path / f"p{i}.wav"
        _passage_wav(p, 1.0, f)
        takes.append(p)
    seams = passages.seam_lengths(["থামো!", "এবার।"], ["x-p01", "x-p02"])
    info = passages.join_passages(takes, tmp_path / "o.wav", seams)
    assert 1.19 <= info["seams"][0]["length_s"] <= 1.85
    assert abs(info["seams"][0]["length_s"] - seams[0]) < 0.03


def test_expected_duration_is_the_runs_own_median_pace():
    chars, durs = [100, 200, 150, 100], [10.0, 20.0, 15.0, 22.0]
    exp, measured = passages.expected_durations(chars, durs, cps=13)
    assert measured and [round(e, 3) for e in exp] == [10.0, 20.0, 15.0, 10.0]   # median 10 chars/s
    exp, measured = passages.expected_durations([130, 260], [1.0, 1.0], cps=13)  # < 3 passages: the estimate
    assert not measured and exp == [10.0, 20.0]


def test_a_cut_is_allowed_at_a_paragraph_end_and_the_sentence_rule_is_text_sentences():
    scene = "পরিচ্ছেদ\n\nপ্রথম বাক্য এখানে। দ্বিতীয় বাক্য।"
    passages.check_passage_scripts(scene, ["পরিচ্ছেদ", "প্রথম বাক্য এখানে। [pause] দ্বিতীয় বাক্য।"])
    with pytest.raises(ValueError, match="mid-sentence"):
        passages.check_passage_scripts(scene, ["পরিচ্ছেদ\n\nপ্রথম", "বাক্য এখানে। দ্বিতীয় বাক্য।"])
    ps = passages.split_passages(scene, cps=0.5)   # a heading line is its own chunk, kept as written
    assert "".join(ps) == scene


def test_join_lays_the_r9_lead_in_and_r4_tail_and_records_offsets(tmp_path):
    """I6/F4: the scene opens on room tone with its first word LEAD_IN_S in and ends TAIL_S after its last word;
    the offsets place each passage on the scene timeline (scene-timing maps clause times through them)."""
    takes = []
    for i, f in enumerate((200, 260)):
        p = tmp_path / f"p{i}.wav"
        _passage_wav(p, 1.0, f)
        takes.append(p)
    out = tmp_path / "scene.wav"
    info = passages.join_passages(takes, out, [0.9], lead_in_s=passages.LEAD_IN_S, tail_s=passages.TAIL_S)
    y = samples(out)
    first = int(np.flatnonzero(np.abs(y) > 10 ** (passages.EDGE_DB / 20))[0]) / SR
    assert abs(info["speech_start"] - passages.LEAD_IN_S) < 0.01 and abs(first - passages.LEAD_IN_S) < 0.05
    assert abs(info["duration"] - (info["speech_end"] + passages.TAIL_S)) < 0.01
    assert _zero_run_s(y) < 0.012                        # lead-in and tail are room tone, never digital zero
    assert -69 <= rms_db(y[:int(0.6 * SR)]) <= -61
    a1 = passages._bounds(retime.read(takes[1]))[0] / SR
    seam_end = info["seams"][0]["at"] + info["seams"][0]["length_s"] / 2
    assert abs(info["offsets"][1] + a1 - (seam_end + passages.EDGE_KEEP_S)) < 0.01   # its first word, placed
