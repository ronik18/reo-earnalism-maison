"""Stand-ins for torch, soundfile, parler_tts, transformers and google.colab, shared by the tests that
execute the narration notebook (test_narration_resume, test_modal_run)."""
import types
from pathlib import Path

import numpy as np


class FakeTensor:
    def __init__(self, a):
        self.a = np.asarray(a)

    def __getitem__(self, i):
        return FakeTensor(self.a[i])

    def cpu(self):
        return self

    def float(self):
        return self

    def numpy(self):
        return self.a


class FakeTokens:
    def __init__(self, texts, side="right"):
        width = max(len(t) for t in texts)

        def row(t):
            pad = [0] * (width - len(t))
            ids = [ord(c) for c in t]
            return pad + ids if side == "left" else ids + pad
        self.input_ids = np.array([row(t) for t in texts])
        self.attention_mask = (self.input_ids != 0).astype(int)

    def to(self, device):
        return self


class FakeTokenizer:
    """Pads on the right unless padding_side is set to "left" (as real tokenizers do)."""

    def __init__(self):
        self.padding_side = "right"

    @classmethod
    def from_pretrained(cls, *a, **k):
        return cls()

    def __call__(self, texts, return_tensors=None, padding=False):
        assert padding is True and isinstance(texts, list)
        return FakeTokens(texts, self.padding_side)


def _padded_on(mask, side) -> bool:
    """Every row's padding (zeros) sits on that side of its tokens."""
    for row in np.asarray(mask):
        ones = np.nonzero(row)[0]
        if not len(ones):
            continue
        if side == "left" and not row[ones[0]:].all():
            return False
        if side == "right" and not row[:ones[-1] + 1].all():
            return False
    return True


class FakeModel:
    calls = []
    load = {}
    with_lengths = True
    refuse_sdpa = False
    config = types.SimpleNamespace(sampling_rate=100,
                                   text_encoder=types.SimpleNamespace(_name_or_path="t5"))

    @classmethod
    def from_pretrained(cls, repo, **kw):
        if cls.refuse_sdpa and kw.get("attn_implementation") == "sdpa":
            raise ValueError("T5EncoderModel does not support an attention implementation through "
                             "torch.nn.functional.scaled_dot_product_attention yet.")
        cls.load = dict(kw, repo=repo)
        return cls()

    def to(self, device):
        return self

    def generate(self, **kw):
        FakeModel.calls.append(kw)
        masks = kw["prompt_attention_mask"]
        # Parler conditions on the prompt prepended to the audio: prompts must be padded on the
        # left; the T5 description encoder takes the usual right padding with its mask
        assert _padded_on(masks, "left"), "prompt tokens padded on the right"
        assert _padded_on(kw["attention_mask"], "right"), "description padded on the left"
        ids = kw["prompt_input_ids"]
        lengths = [int(m.sum()) * 3 for m in masks]
        longest = max(lengths) + 5  # the longest sample is also padded with zeros
        seq = np.zeros((len(lengths), 1, longest), dtype="float32")
        for j, n in enumerate(lengths):
            seq[j, 0, :n] = (ids[j][ids[j] != 0][:1].sum() % 7 + 1) * 0.01 + np.arange(1, n + 1) * 1e-4
        out = types.SimpleNamespace(sequences=FakeTensor(seq))
        if FakeModel.with_lengths:
            out.audios_length = lengths
        return out


def fake_modules(bf16=True, colab=True):
    """sys.modules entries for the narration notebook; without colab=True the caller supplies
    google.colab (the modal_run shim does)."""
    torch = types.ModuleType("torch")
    torch.bfloat16, torch.float16, torch.float32 = "bf16", "fp16", "fp32"
    torch.cuda = types.SimpleNamespace(is_available=lambda: True, is_bf16_supported=lambda: bf16)
    sf = types.ModuleType("soundfile")
    sf.write = lambda path, wav, rate: Path(path).write_bytes(
        np.asarray(wav, dtype="float32").tobytes() + str(rate).encode())
    pt = types.ModuleType("parler_tts")
    pt.ParlerTTSForConditionalGeneration = FakeModel
    tr = types.ModuleType("transformers")
    tr.AutoTokenizer = FakeTokenizer
    mods = {"torch": torch, "soundfile": sf, "parler_tts": pt, "transformers": tr}
    if colab:
        gc = types.ModuleType("google.colab")
        gc.drive = types.SimpleNamespace(mount=lambda p: None)
        gc.runtime = types.SimpleNamespace(unassign=lambda: None)
        mods.update({"google": types.ModuleType("google"), "google.colab": gc})
    return mods
