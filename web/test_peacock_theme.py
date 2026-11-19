"""Selected owner-supplied theme: render real shell and preserve protected assets."""
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory,SimpleTestCase
from .views import context

class PeacockShellTests(SimpleTestCase):
    def test_legacy_routes_share_one_english_shell_keeps_real_navigation_and_local_assets(self):
        for locale in ('en','bn'):
            request=RequestFactory().get(f'/{locale}/')
            request.user=AnonymousUser();request.resolver_match=SimpleNamespace(url_name='home')
            html=render_to_string('web/home.html',context(request,locale),request=request)
            self.assertIn('maison/peacock/maison-theme.css',html)
            self.assertIn('maison/fonts/typography.css',html)
            self.assertIn('maison/logo.png',html)
            self.assertIn('/en/explore/',html)
            self.assertIn('/en/settings/',html)
            self.assertIn('class="pc-halo" aria-hidden="true"',html)
            self.assertIn('class="pc-jali" aria-hidden="true"',html)
            self.assertIn('data-route="home"',html)
            self.assertIn('lang="en" data-ui-locale="en"',html)
            self.assertNotIn('aria-label="Interface language"',html)
            self.assertNotIn('fonts.googleapis',html)
            self.assertNotIn('atelier.js',html)
    def test_ornament_assets_are_inert_and_local_references_resolve(self):
        root=Path(settings.BASE_DIR)/'static/maison/peacock'
        for path in (root/'svg').glob('*.svg'):
            for node in ET.parse(path).getroot().iter():
                self.assertNotIn(node.tag.rsplit('}',1)[-1],('script','foreignObject','image','a'))
                for name,value in node.attrib.items():
                    self.assertFalse(name.lower().startswith('on'))
                    self.assertNotIn('href',name)
        css=(root/'maison-theme.css').read_text()
        for url in re.findall(r"url\(['\"]?([^)'\"]+)",css):
            self.assertTrue((root/url).is_file(),url)
        self.assertNotIn('@import',css)
    def test_official_logo_and_existing_font_hashes_are_unchanged(self):
        import json
        root=Path(settings.BASE_DIR)/'static/maison'
        manifest=json.loads((root/'asset-manifest.json').read_text())
        for row in manifest['files']:
            if row['file']=='logo.png' or row['file'].startswith('fonts/'):
                self.assertEqual(hashlib.sha256((root/row['file']).read_bytes()).hexdigest(),row['sha256'])

    def test_settings_keeps_legal_destinations_without_a_phone_footer(self):
        request=RequestFactory().get('/bn/settings/')
        request.user=AnonymousUser();request.resolver_match=SimpleNamespace(url_name='settings')
        html=render_to_string('web/base.html',context(request,'bn'),request=request)
        main=html.split('<main',1)[1].split('</main>',1)[0]
        for route in ('privacy','terms','contact'):self.assertIn('/en/'+route+'/',main)
