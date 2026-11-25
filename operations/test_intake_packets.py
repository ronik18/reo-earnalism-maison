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

    def test_draft_clearance_is_not_approved(self):
        record = json.loads((INTAKE.parent.parent / 'docs/evidence/publication-clearance-kshudhita-pashan-draft.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'], 'DRAFT_PENDING_OWNER_APPROVAL')
        self.assertFalse(record['approval']['approved'])
        pages = record['books']['kshudhita-pashan']['scan_pages']
        self.assertEqual(len(pages), 24)
        self.assertTrue(all(p['quality'] == 4 for p in pages))
