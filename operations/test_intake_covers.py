import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from PIL import Image

from operations.intake import covers


def png(size):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def listing(pid, raw, **kw):
    base = dict(public_id=pid, asset_id="a" * 32, version=1784226492, format="png",
                width=1024, height=1536, bytes=len(raw), created_at="2026-07-16T18:28:12Z")
    base.update(kw)
    return base


class CoverTests(SimpleTestCase):
    def test_pair_is_800_by_1200_and_hashes_recorded(self):
        f, b = png((1024, 1536)), png((512, 768))
        origs = {"front": listing("x/front", f), "back": listing("x/back", b)}
        fo, bo, prov = covers.derive_pair(f, b, origs, slug="s")
        for data, side in ((fo, "front"), (bo, "back")):
            img = Image.open(io.BytesIO(data))
            self.assertEqual((img.size, img.format), ((800, 1200), "JPEG"))
            d = prov["sides"][side]["delivery"]
            self.assertEqual(d["bytes"], len(data))
            self.assertEqual(d["path"], f"{side}.jpg")
        self.assertEqual(prov["schema"], "earnalism.cover-provenance.v2")
        o = prov["sides"]["front"]["original"]
        self.assertEqual(len(o["sha256"]), 64)
        self.assertEqual(o["url"], "https://res.cloudinary.com/dzlrhlfpu/image/upload/v1784226492/x/front.png")
        self.assertEqual(prov["sides"]["back"]["original"]["width"], 512)

    def test_non_two_by_three_original_is_refused(self):
        f, b = png((1000, 1000)), png((1024, 1536))
        origs = {"front": listing("x/front", f), "back": listing("x/back", b)}
        with self.assertRaises(covers.CoverError) as cm:
            covers.derive_pair(f, b, origs)
        self.assertEqual(cm.exception.code, "COVER_RATIO")

    def test_downloaded_bytes_must_match_listing_size(self):
        f, b = png((1024, 1536)), png((1024, 1536))
        origs = {"front": listing("x/front", f, bytes=len(f) + 1), "back": listing("x/back", b)}
        with self.assertRaises(covers.CoverError) as cm:
            covers.derive_pair(f, b, origs)
        self.assertEqual(cm.exception.code, "COVER_BYTES_MISMATCH")

    def test_command_writes_packet_and_refuses_overwrite(self):
        f, b = png((1024, 1536)), png((1024, 1536))
        lists = {"x/front": listing("x/front", f), "x/back": listing("x/back", b)}

        def fake_get(url):
            if "api.cloudinary.com" in url:
                return json.dumps(lists[url.split("/upload/")[1]]).encode()
            return f if "front" in url else b

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(covers, "_get", fake_get):
            folder = str(Path(tmp) / "slug")
            args = ["slug", "--front", "x/front", "--back", "x/back", "--folder", folder]
            call_command("intake_cover", *args)
            prov = json.loads((Path(folder) / "cover_provenance.json").read_text())
            self.assertEqual(prov["status"], "OWNER_PROVIDED_ARTWORK")
            self.assertTrue((Path(folder) / "front.jpg").exists())
            with self.assertRaises(CommandError):
                call_command("intake_cover", *args)
            call_command("intake_cover", *args, "--replace")
