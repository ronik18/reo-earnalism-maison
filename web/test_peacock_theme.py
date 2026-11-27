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
    def test_every_route_shares_the_reading_room_shell_with_real_navigation_and_local_assets(self):
        # Owner-approved reading-room design (22 Nov 2026) replaces the dark Peacock shell on every route.
        for locale in ('en','bn'):
            for template,route,extra in (('web/home.html','home',{}),('web/status.html','not-found',{'error_key':'not_found'})):
                request=RequestFactory().get(f'/{locale}/')
                request.user=AnonymousUser();request.resolver_match=SimpleNamespace(url_name=route)
                html=render_to_string(template,context(request,locale,**extra),request=request)
                self.assertIn('maison/room/room.css',html)
                self.assertIn('maison/app.css',html)
                self.assertIn('maison/fonts/typography.css',html)
                self.assertIn('maison/logo.png',html)
                self.assertIn('class="room-nav"',html)
                self.assertIn('/en/explore/',html)
                self.assertIn('/en/settings/',html)
                self.assertIn(f'data-route="{route}"',html)
                self.assertIn('lang="en" data-ui-locale="en"',html)
                self.assertIn('theme-light',html)
                self.assertNotIn('maison/peacock/maison-theme.css',html)
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


class LogoPlateTests(SimpleTestCase):
    def test_logo_img_has_no_filter_and_same_src(self):
        root=Path(settings.BASE_DIR)/'static/maison'
        for name in ('app.css','room/room.css'):
            css=(root/name).read_text()
            for rule in re.findall(r'([^{}]*)\{([^{}]*)\}',css):
                selector,body=rule
                if re.search(r'\.room-logo-mini\s+img',selector) or re.search(r'\.room-logo(-mini)?\s+img',selector):
                    for prop in ('filter','opacity','mix-blend-mode','backdrop-filter'):
                        self.assertNotRegex(body,r'(^|[;\s])'+prop+r'\s*:',(name,selector))
        request=RequestFactory().get('/en/read/x/y/');request.user=AnonymousUser()
        request.resolver_match=SimpleNamespace(url_name='reader')
        html=render_to_string('web/base.html',context(request,'en',focused=True),request=request)
        self.assertRegex(html,r'class="room-logo room-logo-mini"[^>]*>\s*<img src="[^"]*maison/logo\.png[^"]*"')
    def test_logo_plate_is_ivory_in_every_reader_theme(self):
        css=(Path(settings.BASE_DIR)/'static/maison/room/room.css').read_text()
        self.assertRegex(css,r'\.room-logo-mini\{[^}]*background:var\(--ivory\)')
        for theme in ('light','sepia','dark','true_black'):
            self.assertIn('body.reader-theme-'+theme,css)
        self.assertRegex(css,r'reader-theme-dark \.room-evening :focus-visible[^{]*\{outline-color:var\(--gold-on-dark\)')
    def test_new_header_rules_use_tokens_not_raw_hex_for_light_themes(self):
        css=(Path(settings.BASE_DIR)/'static/maison/room/room.css').read_text()
        for theme in ('light','sepia'):
            for rule in re.findall(r'body\.reader-theme-'+theme+r'[^{]*\{([^}]*)\}',css):
                self.assertNotRegex(rule,r'#[0-9A-Fa-f]{3,6}\b')
