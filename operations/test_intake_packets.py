"""Every committed book intake packet is a valid manifest whose source bytes match it exactly."""
import hashlib
import json
from pathlib import Path

from django.test import SimpleTestCase

from .book_source import read_source_bytes, validate_manifest

INTAKE = Path(__file__).resolve().parent.parent / 'library' / 'intake'


class IntakePacketTests(SimpleTestCase):
    def test_manifests_bind_their_exact_source(self):
        manifests = sorted(INTAKE.glob('*/manifest.json'))
        self.assertGreaterEqual(len(manifests), 2)
        for path in manifests:
            with self.subTest(packet=path.parent.name):
                manifest = json.loads(path.read_text(encoding='utf-8'))
                validate_manifest(manifest)
                raw = (path.parent / 'source.json').read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest['source']['sha256'])
                self.assertEqual(len(raw), manifest['source']['bytes'])
                source = read_source_bytes(raw)
                self.assertEqual(source['language'], manifest['edition']['language'])
                text = ''.join(p['text'] for u in source['units'] for p in u['paragraphs'])
                self.assertNotIn('​', text)
                self.assertNotIn('{{', text)

    def test_kshudhita_pashan_clearance_is_approved_with_the_cover_attached(self):
        record = json.loads((INTAKE.parent.parent / 'docs/evidence/publication-clearance-kshudhita-pashan.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'OWNER_APPROVED')
        self.assertTrue(record['approval']['approved'])
        self.assertEqual(record['approval']['still_required'], [])
        self.assertEqual(record['approval']['cover_attached']['front_sha256'], hashlib.sha256((INTAKE / 'kshudhita-pashan/front.jpg').read_bytes()).hexdigest())
        pages = record['books']['kshudhita-pashan']['scan_pages']
        self.assertEqual(len(pages), 24)
        self.assertTrue(all(p['quality'] == 4 for p in pages))
