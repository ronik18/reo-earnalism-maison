"""Maison film bundle: the faststart H.264/AAC MP4, its WebVTT captions and a hashed manifest.

Pure checks and file writing only; the record/QC gate lives in cli.cmd_bundle_film.
"""
import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

from .record import sha256_file

SCHEMA = "earnalism.audiovisual-film-bundle.v1"
MAX_BYTES = 1_073_741_824  # 1 GiB
_TIME = re.compile(r"(\d{2}:\d{2}:\d{2}),(\d{3})")


def srt_to_vtt(text: str) -> str:
    """WEBVTT header, comma milliseconds become dots; cue order and text are unchanged."""
    if not text.strip():
        raise ValueError("the subtitle file is empty")
    body = _TIME.sub(r"\1.\2", text.replace("\r\n", "\n").lstrip("﻿"))
    return "WEBVTT\n\n" + body.strip("\n") + "\n"


def is_faststart(path) -> bool:
    """True when the top-level moov box precedes mdat. Reads box headers only."""
    with open(path, "rb") as f:
        size = Path(path).stat().st_size
        pos = 0
        while pos + 8 <= size:
            f.seek(pos)
            head = f.read(8)
            length, kind = struct.unpack(">I4s", head)
            if length == 1:
                length = struct.unpack(">Q", f.read(8))[0]
            elif length == 0:
                length = size - pos
            if kind == b"moov":
                return True
            if kind == b"mdat":
                return False
            if length < 8:
                return False
            pos += length
    return False


def probe(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                          "-of", "json", str(path)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def check_streams(info: dict) -> None:
    kinds = [(s.get("codec_type"), s.get("codec_name")) for s in info.get("streams", [])]
    if sorted(kinds) != [("audio", "aac"), ("video", "h264")]:
        raise ValueError("the film must be a single H.264 video stream plus a single AAC audio "
                         f"stream; found {kinds}")


def build(mp4: Path, srt: Path, unit_id: str, out: Path) -> dict:
    """Validate the MP4 and write film.mp4, film.vtt and film.json under `out`."""
    size = Path(mp4).stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"the film is {size} bytes, over the 1 073 741 824 byte limit")
    if not is_faststart(mp4):
        raise ValueError("the film MP4 is not faststart (moov must precede mdat); "
                         "reassemble it with -movflags +faststart")
    info = probe(mp4)
    check_streams(info)
    vtt = srt_to_vtt(Path(srt).read_text(encoding="utf-8"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mp4, out / "film.mp4")
    (out / "film.vtt").write_text(vtt, encoding="utf-8")
    unit = {"unit_id": unit_id, "mp4": "film.mp4", "vtt": "film.vtt",
            "mp4_sha256": sha256_file(out / "film.mp4"), "vtt_sha256": sha256_file(out / "film.vtt"),
            "duration_ms": round(float(info["format"]["duration"]) * 1000), "bytes": size}
    manifest = {"schema": SCHEMA, "units": [unit]}
    (out / "film.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
    return manifest
