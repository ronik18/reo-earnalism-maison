"""Actual packaged staff assets must survive isolated immutable publication."""
import tempfile
from pathlib import Path
from django.test import SimpleTestCase, override_settings
from operations.management.commands.prepare_public_assets import Command
from operations.static_assets import tree_manifest
from operations.static_storage import MaisonStaticFilesStorage


class AdminStaticReleaseTests(SimpleTestCase):
    @override_settings(LOCAL=False)
    def test_production_admin_urls_use_only_isolated_namespace(self):
        storage=MaisonStaticFilesStorage(base_url='https://assets.example.test/static/'+'a'*64+'/')
        self.assertEqual(storage.url('admin/css/base.css'),storage.base_url+'maison/framework/admin/css/base.css')
        self.assertEqual(storage.url('admin/js/theme.js'),storage.base_url+'maison/framework/admin/js/theme.js')
        self.assertEqual(storage.url('maison/app.css'),storage.base_url+'maison/app.css')

    @override_settings(LOCAL=True)
    def test_local_finders_keep_builtin_admin_paths(self):
        self.assertEqual(MaisonStaticFilesStorage(base_url='/static/').url('admin/css/base.css'),'/static/admin/css/base.css')

    def test_actual_packaged_admin_dependencies_and_license_are_manifested(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'admin').mkdir();(root/'admin/private.js').write_text('NEVER_PUBLISH')
            Command.stage_admin_assets(root)
            manifest=tree_manifest(root);assets={item['path'] for item in manifest['assets']}
            for path in ['css/base.css','css/dark_mode.css','css/nav_sidebar.css','css/responsive.css',
                         'css/login.css','js/theme.js','js/nav_sidebar.js','img/icon-yes.svg','LICENSE','LICENSE.python']:
                self.assertIn('maison/framework/admin/'+path,assets)
            self.assertNotIn('admin/private.js',assets)
            self.assertFalse(any(path.endswith('.map') or '/private' in path for path in assets))
            license_text=(root/'maison/framework/admin/LICENSE').read_text()
            self.assertIn('Redistribution',license_text)
            self.assertIn('Django',license_text)
