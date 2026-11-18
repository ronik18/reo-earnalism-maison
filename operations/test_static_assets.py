import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase,override_settings
from core.api import DomainError
from .static_assets import tree_manifest,publish_manifest,CACHE_CONTROL,CHUNK_BYTES,_public_client


class StaticReleaseTests(SimpleTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);(self.root/'maison/dist').mkdir(parents=True)
        self.files={'maison/dist/reader-HASH.js':b'import "./shared-HASH.js";', 'maison/dist/shared-HASH.js':b'export const value=1;',
            'maison/fonts/OFL.txt':b'Original synthetic license fixture', 'maison/fonts/font.woff2':b'synthetic-font',
            'maison/app.css':b'body {color: #123}', 'maison/logo.png':b'synthetic-image'}
        for name,raw in self.files.items():
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    def test_manifest_deterministic_full_namespace_and_private_exclusion(self):
        for name in ['maison/dist/reader-HASH.js.map','maison/.env','maison/intake/book.json','maison/private.json','admin/private.js']:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'not public')
        first=tree_manifest(self.root);self.assertEqual(first,tree_manifest(self.root));self.assertEqual({item['path'] for item in first['assets']},set(self.files))
        self.assertEqual(first['bytes_total'],sum(len(value) for value in self.files.values()));self.assertEqual(first['file_count'],len(self.files))
        from .static_assets import canonical_manifest
        value={key:item for key,item in first.items() if key!='release_id'}
        self.assertEqual(hashlib.sha256(canonical_manifest(value)).hexdigest(),first['release_id'])
        (self.root/'maison/app.css').write_bytes(b'changed');self.assertNotEqual(tree_manifest(self.root)['release_id'],first['release_id'])
    def test_prepare_and_default_publish_make_no_provider_calls(self):
        with override_settings(BASE_DIR=self.root),patch('operations.static_assets._public_client',side_effect=AssertionError('No provider calls')):
            output=io.StringIO();call_command('prepare_public_assets',collected_directory=str(self.root),stdout=output)
            path=self.root/'.local/public-assets/manifest.json';self.assertTrue(path.is_file());self.assertEqual(path.stat().st_mode & 0o777,0o600)
            output=io.StringIO();call_command('publish_public_assets',manifest=str(path),collected_directory=str(self.root),stdout=output)
            self.assertEqual(json.loads(output.getvalue())['status'],'planned')
    def test_explicit_create_once_and_retry_verify_exact_bytes_headers(self):
        manifest=tree_manifest(self.root);client=Mock();objects={}
        class Conflict(Exception):response={'Error':{'Code':'PreconditionFailed'},'ResponseMetadata':{'HTTPStatusCode':412}}
        def put(**kwargs):
            self.assertEqual(kwargs['Bucket'],'public-static-only');self.assertEqual(kwargs['IfNoneMatch'],'*');self.assertEqual(kwargs['CacheControl'],CACHE_CONTROL)
            self.assertTrue(kwargs['Key'].startswith('static/'+manifest['release_id']+'/maison/'))
            if kwargs['Key'] in objects:raise Conflict()
            raw=kwargs['Body'].read();self.assertEqual(len(raw),kwargs['ContentLength']);self.assertEqual(hashlib.sha256(raw).hexdigest(),kwargs['Metadata']['sha256'])
            objects[kwargs['Key']]={'raw':raw,'ContentLength':len(raw),'ContentType':kwargs['ContentType'],'CacheControl':kwargs['CacheControl']}
        def get(**kwargs):
            value=objects[kwargs['Key']];return {key:item for key,item in value.items() if key!='raw'}|{'Body':io.BytesIO(value['raw'])}
        client.put_object.side_effect=put;client.get_object.side_effect=get
        with override_settings(R2_PUBLIC_BUCKET='public-static-only'),patch('operations.static_assets._public_client',return_value=client):
            first=publish_manifest(self.root,manifest,execute=True);self.assertEqual(first['uploaded'],len(self.files));self.assertFalse(first['public_http_verified'])
            second=publish_manifest(self.root,manifest,execute=True);self.assertEqual(second['uploaded'],0);self.assertEqual(second['verified_existing'],len(self.files))
            first_key=next(iter(objects));objects[first_key]['raw']=b'corrupt'
            with self.assertRaises(DomainError) as error:publish_manifest(self.root,manifest,execute=True)
            self.assertEqual(error.exception.code,'public_asset_mismatch')
    def test_tree_budget_symlink_or_manifest_drift_fails_before_network(self):
        manifest=tree_manifest(self.root)
        with patch('operations.static_assets._public_client',side_effect=AssertionError('No provider calls')):
            with self.assertRaises(DomainError):publish_manifest(self.root,{**manifest,'release_id':'0'*64},execute=True)
            with self.assertRaises(DomainError):tree_manifest(self.root,max_file_bytes=1)
            with self.assertRaises(DomainError):tree_manifest(self.root,max_files=1)
            (self.root/'maison/outside.js').symlink_to(self.root/'maison/app.css')
            with self.assertRaises(DomainError):tree_manifest(self.root)
    def test_separate_public_credentials_required_no_private_fallback(self):
        with override_settings(R2_ACCOUNT_ID='a'*32,R2_ENDPOINT_URL='https://'+'a'*32+'.r2.cloudflarestorage.com',
            R2_PRIVATE_BUCKET='private-book-only',R2_PUBLIC_BUCKET='public-static-only',R2_UPLOAD_KEY_ID='private-key',R2_APPLICATION_KEY_ID='private-read',
            R2_PUBLIC_UPLOAD_KEY_ID='',R2_PUBLIC_UPLOAD_SECRET=''):
            with patch('boto3.client',side_effect=AssertionError('No SDK construction before credentials validated')):
                with self.assertRaises(DomainError):_public_client()
                with override_settings(R2_PUBLIC_UPLOAD_KEY_ID='private-key',R2_PUBLIC_UPLOAD_SECRET='separate-secret'):
                    with self.assertRaises(DomainError):_public_client()
    def test_unknown_provider_outcome_is_redacted_and_never_overwrites(self):
        client=Mock();client.put_object.side_effect=RuntimeError('SYNTHETIC_SECRET_NEVER_LOG')
        with override_settings(R2_PUBLIC_BUCKET='public-static-only'),patch('operations.static_assets._public_client',return_value=client):
            with self.assertRaises(DomainError) as error:publish_manifest(self.root,tree_manifest(self.root),execute=True)
        self.assertEqual(error.exception.code,'public_storage_unavailable');self.assertNotIn('SYNTHETIC_SECRET',str(error.exception));self.assertEqual(client.put_object.call_args.kwargs['IfNoneMatch'],'*')

    def test_verifier_bounds_socket_and_never_touches_exhausted_stream(self):
        from .static_assets import _verify_object
        raw=b'public-static-body'
        class Stream(io.BytesIO):
            def __init__(self):super().__init__(raw);self.timeouts=[]
            def set_socket_timeout(self,value):
                if self.tell()==len(raw):raise AssertionError('Exhausted socket must not be reset')
                self.timeouts.append(value)
        stream=Stream();client=Mock();client.get_object.return_value={'Body':stream,'ContentLength':len(raw),'ContentType':'text/javascript','CacheControl':CACHE_CONTROL}
        asset={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'content_type':'text/javascript'}
        with patch('operations.static_assets.time.monotonic',return_value=100):_verify_object(client,'public-static-only','static/release/maison/app.js',asset,102)
        self.assertEqual(stream.timeouts,[2]);self.assertTrue(stream.closed)
