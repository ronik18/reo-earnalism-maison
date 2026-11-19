import io
from django.test import SimpleTestCase
from reportlab.pdfgen.canvas import Canvas
from core.api import DomainError
from .pdf_fonts import draw_text,text_width

class FinancialPDFFontTests(SimpleTestCase):
    def test_mixed_bengali_uses_exact_shaped_advance_and_original_text(self):
        text='Reo Enterprise - বাংলা বই: স্বার্থপর দৈত্য - INR 123.45'
        output=io.BytesIO();c=Canvas(output,pageCompression=0)
        width=draw_text(c,text,36,700,11)
        self.assertAlmostEqual(width,text_width(text,11),places=6)
        self.assertGreater(width,100);self.assertLess(width,530)
        c.save();body=output.getvalue()
        self.assertTrue(body.startswith(b'%PDF-'))
        self.assertIn(b'/ActualText',body)
        self.assertIn('বাংলা বই: স্বার্থপর দৈত্য'.encode('utf-16-be').hex().upper()[:16].encode(),body)
        self.assertIn(b'/FontFile2',body)
    def test_unsupported_script_and_controls_are_not_silent_missing_glyphs(self):
        for text in ['\x00hidden','amount\u202e100','\u200d','unqualified \U0001f680']:
            with self.subTest(text=text),self.assertRaises(DomainError):text_width(text)
    def test_financial_latin_avoids_ligature_extraction_substitutions(self):
        self.assertGreater(text_width('office invoice 19.95'),0)
        self.assertEqual(text_width(''),0)
