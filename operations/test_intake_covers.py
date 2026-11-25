import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from operations.intake import covers
from operations.models import ReviewItem


def png(size, color=(200, 30, 30), mode="RGB", fmt="PNG"):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, fmt)
    return buf.getvalue()


def dims(raw):
    return Image.open(io.BytesIO(raw)).size


def listing(pid, raw, **kw):
    w, h = dims(raw)
    base = dict(public_id=pid, asset_id=pid.ljust(32, "0")[-32:], version=1784226492, format="png",
                width=w, height=h, bytes=len(raw), created_at="2026-07-16T18:28:12Z")
    base.update(kw)
    return base


class CoverTests(TestCase):
    def test_pair_is_800_by_1200_and_hashes_recorded(self):
        f, b = png((1024, 1536)), png((512, 768), (10, 90, 200))
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
        f, b = png((1000, 1000)), png((1024, 1536), (1, 2, 3))
        origs = {"front": listing("x/front", f), "back": listing("x/back", b)}
        with self.assertRaises(covers.CoverError) as cm:
            covers.derive_pair(f, b, origs)
        self.assertEqual(cm.exception.code, "COVER_RATIO")

    def test_downloaded_bytes_must_match_listing_size(self):
        f, b = png((1024, 1536)), png((1024, 1536), (1, 2, 3))
        origs = {"front": listing("x/front", f, bytes=len(f) + 1), "back": listing("x/back", b)}
        with self.assertRaises(covers.CoverError) as cm:
            covers.derive_pair(f, b, origs)
        self.assertEqual(cm.exception.code, "COVER_BYTES_MISMATCH")

    def test_command_writes_packet_and_refuses_overwrite(self):
        f, b = png((1024, 1536)), png((1024, 1536), (1, 2, 3))
        lists = {"x/front": listing("x/front", f), "x/back": listing("x/back", b)}

        def fake_get(url):
            if "api.cloudinary.com" in url:
                return json.dumps(lists[url.split("/upload/")[1]]).encode()
            return f if "front" in url else b

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(covers, "_get", fake_get), \
                override_settings(BASE_DIR=Path(tmp)):
            folder = str(Path(tmp) / "slug")
            args = ["slug", "--front", "x/front", "--back", "x/back", "--folder", folder]
            call_command("intake_cover", *args)
            item = ReviewItem.objects.get()
            self.assertEqual((item.kind, item.ref, item.summary), ("cover", "slug/cover_provenance.json",
                                                                  {"edition_slug": "slug", "title": "slug"}))
            self.assertEqual(item.sha256, hashlib.sha256((Path(folder) / "cover_provenance.json").read_bytes()).hexdigest())
            prov = json.loads((Path(folder) / "cover_provenance.json").read_text())
            self.assertEqual(prov["status"], "OWNER_PROVIDED_ARTWORK")
            self.assertTrue((Path(folder) / "front.jpg").exists())
            with self.assertRaises(CommandError):
                call_command("intake_cover", *args)
            (Path(folder) / "front.jpg").write_bytes(b"stale")
            (Path(folder) / "cover_provenance.json").write_text("{}")
            call_command("intake_cover", *args, "--replace")
            self.assertNotEqual((Path(folder) / "front.jpg").read_bytes(), b"stale")
            self.assertEqual(
                json.loads((Path(folder) / "cover_provenance.json").read_text())["slug"], "slug"
            )
            self.assertEqual(ReviewItem.objects.filter(status="pending").count(), 1)  # the replaced file supersedes

    def test_command_outside_the_repository_is_refused_before_fetching(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as repo, \
                mock.patch.object(covers, "_get", side_effect=AssertionError("no fetch")), override_settings(BASE_DIR=Path(repo)):
            with self.assertRaisesRegex(CommandError, "REVIEW_REF_INVALID"):
                call_command("intake_cover", "slug", "--front", "x/front", "--back", "x/back", "--folder", str(Path(tmp) / "slug"))
            self.assertFalse((Path(tmp) / "slug").exists())

    def test_alpha_composites_onto_white(self):
        f = png((1024, 1536), (0, 0, 0, 0), "RGBA")
        b = png((1024, 1536), (1, 2, 3))
        origs = {"front": listing("x/front", f), "back": listing("x/back", b)}
        fo, _, _ = covers.derive_pair(f, b, origs)
        px = Image.open(io.BytesIO(fo)).getpixel((400, 600))
        self.assertTrue(all(c >= 250 for c in px), px)

    def test_exif_orientation_is_applied(self):
        img = Image.new("RGB", (1536, 1024), (255, 0, 0))
        exif = Image.Exif()
        exif[0x0112] = 6  # rotate 90 CW on display -> 1024x1536
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)
        f = buf.getvalue()
        b = png((1024, 1536), (1, 2, 3))
        origs = {"front": listing("x/front", f, format="jpg"), "back": listing("x/back", b)}
        fo, _, prov = covers.derive_pair(f, b, origs)
        self.assertEqual(Image.open(io.BytesIO(fo)).size, (800, 1200))
        self.assertEqual(prov["sides"]["front"]["original"]["width"], 1024)

    def test_duplicate_pair_refused(self):
        f = png((1024, 1536))
        same_id = {"front": listing("x/a", f), "back": listing("x/a", f)}
        with self.assertRaises(covers.CoverError) as cm:
            covers.derive_pair(f, f, same_id)
        self.assertEqual(cm.exception.code, "COVER_PAIR_DUPLICATE")
        same_bytes = {"front": listing("x/a", f), "back": listing("x/b", f)}
        with self.assertRaises(covers.CoverError) as cm:
            covers.derive_pair(f, f, same_bytes)
        self.assertEqual(cm.exception.code, "COVER_PAIR_DUPLICATE")

    def test_listing_must_match_decoded_image(self):
        f, b = png((1024, 1536)), png((1024, 1536), (1, 2, 3))
        for bad in ({"width": 999}, {"format": "webp"}):
            origs = {"front": listing("x/front", f, **bad), "back": listing("x/back", b)}
            with self.assertRaises(covers.CoverError) as cm:
                covers.derive_pair(f, b, origs)
            self.assertEqual(cm.exception.code, "COVER_LISTING_MISMATCH")

    def test_provenance_key_sets_match_reference(self):
        f, b = png((1024, 1536)), png((1024, 1536), (1, 2, 3))
        origs = {"front": listing("x/front", f), "back": listing("x/back", b)}
        _, _, prov = covers.derive_pair(f, b, origs, slug="s")
        self.assertEqual(
            set(prov),
            {"schema", "slug", "status", "owner_statement", "basis", "scope", "sides"},
        )
        self.assertEqual(set(prov["owner_statement"]), {"date", "text"})
        self.assertEqual(set(prov["sides"]), {"front", "back"})
        for side in prov["sides"].values():
            self.assertEqual(set(side), {"original", "delivery"})
            self.assertEqual(
                set(side["original"]),
                {"url", "public_id", "asset_id", "version", "created_at", "format",
                 "width", "height", "bytes", "sha256"},
            )
            self.assertEqual(
                set(side["delivery"]),
                {"path", "width", "height", "format", "bytes", "sha256", "derivation"},
            )
