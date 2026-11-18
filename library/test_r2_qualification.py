"""Probe orchestration tests use fake HTTP/storage only, never real credentials."""
import hashlib
from unittest.mock import Mock,patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase,override_settings
from core.api import DomainError
from . import r2_qualification as probe

@override_settings(R2_ENDPOINT_URL='https://test.r2.cloudflarestorage.com',PUBLIC_BASE_URL='https://maison.example')
class PrivateCanaryQualificationTests(SimpleTestCase):
    def test_operator_opt_in_required_before_any_provider_request(self):
        with patch('library.management.commands.qualify_r2_private.qualify_r2') as run:
            with self.assertRaises(CommandError):call_command('qualify_r2_private',origin='https://maison.example',output='/tmp/not-written-r2-probe.json')
            run.assert_not_called()

    def test_probe_reports_exact_http_checks_and_cleanup_without_signatures(self):
        origin='https://maison.example';raw=(b'Maison private synthetic storage qualification.\n'*1500)[:65536]
        sha=hashlib.sha256(raw).hexdigest();cors={'access-control-allow-origin':origin}
        results=[(200,{**cors,'access-control-allow-methods':'PUT','access-control-allow-headers':'Content-Type,If-None-Match'},b''),
            (403,{},b''),(403,{},b''),(403,{},b''),(200,cors,b''),(412,{},b''),
            (200,{**cors,'access-control-expose-headers':'Accept-Ranges,Content-Length,Content-Range,ETag','cache-control':'private, no-store'},raw),
            (206,{**cors,'content-range':f'bytes 5-31/{len(raw)}'},raw[5:32]),
            (200,{**cors,'access-control-allow-headers':'Range'},b''),(403,{},b''),(403,{},b''),(403,{},b'')]
        signed='https://test.r2.cloudflarestorage.com/private/canary?X-Amz-Signature=never-in-evidence'
        with patch.object(probe.storage,'is_r2',return_value=True),patch.object(probe.storage,'put_private'),patch.object(probe.storage,'verify_private',return_value={'sha256':sha}),patch.object(probe.storage,'copy_verified',return_value={'sha256':sha}),patch.object(probe.storage,'upload_url',return_value=(signed,{'If-None-Match':'*'})),patch.object(probe.storage,'private_url',return_value=signed),patch.object(probe.storage,'delete_private') as delete,patch.object(probe.storage,'private_exists',return_value=False),patch.object(probe,'_request',side_effect=results),patch.object(probe.time,'sleep') as sleep:
            report=probe.qualify_r2(origin)
        self.assertEqual(report['status'],'pass');self.assertEqual(delete.call_count,3);sleep.assert_called_once_with(4)
        self.assertFalse(report['browser_qualified']);self.assertFalse(report['public_cdn_qualified'])
        self.assertNotIn('Signature',str(report));self.assertNotIn('never-in-evidence',str(report))

    def test_probe_rejects_untrusted_targets_before_socket_and_does_not_follow_redirects(self):
        with patch('library.r2_qualification.http.client.HTTPSConnection') as connection:
            for url in ['https://outside.example/private','http://test.r2.cloudflarestorage.com/private','https://user@test.r2.cloudflarestorage.com/private']:
                with self.assertRaises(DomainError):probe._request(url)
            connection.assert_not_called()
        connection=Mock();response=Mock(status=302);response.read.return_value=b''
        response.getheaders.return_value=[('Location','https://outside.example')];connection.getresponse.return_value=response
        with patch('library.r2_qualification.http.client.HTTPSConnection',return_value=connection):
            result=probe._request('https://test.r2.cloudflarestorage.com/private')
        self.assertEqual(result[0],302);connection.request.assert_called_once();connection.close.assert_called_once()


    @override_settings(LOCAL=True,PUBLIC_BASE_URL='http://127.0.0.1:8009')
    def test_local_loopback_harness_port_is_explicitly_local_only(self):
        self.assertEqual(probe._validated_origin('http://127.0.0.1:8010'),('http://127.0.0.1:8010',True))
        for origin in ['http://localhost:8010','http://192.168.1.20:8010','http://example.test:8010','http://127.0.0.1','http://127.0.0.1:8010/path','http://127.0.0.1:8010?url=private']:
            with self.subTest(origin=origin),self.assertRaises(DomainError):probe._validated_origin(origin)

    @override_settings(LOCAL=False,PUBLIC_BASE_URL='http://127.0.0.1:8010')
    def test_production_never_accepts_loopback_http_even_when_base_matches(self):
        with self.assertRaises(DomainError):probe._validated_origin('http://127.0.0.1:8010')

    @override_settings(LOCAL=False,PUBLIC_BASE_URL='https://maison.example')
    def test_production_https_requires_exact_configured_origin(self):
        self.assertEqual(probe._validated_origin('https://maison.example'),('https://maison.example',False))
        for origin in ['http://maison.example:8010','https://other.example','https://maison.example:8443']:
            with self.subTest(origin=origin),self.assertRaises(DomainError):probe._validated_origin(origin)

    def test_cleanup_attempts_every_exact_canary_after_unexpected_provider_failure(self):
        with patch.object(probe.storage,'is_r2',return_value=True),patch.object(probe.storage,'put_private',side_effect=RuntimeError('private-signed-url-must-not-escape')),patch.object(probe.storage,'delete_private') as delete,patch.object(probe.storage,'private_exists',return_value=False):
            report=probe.qualify_r2('https://maison.example')
        self.assertEqual(report['status'],'fail');self.assertEqual(report['error_code'],'qualification_failed');self.assertEqual(delete.call_count,3)
        self.assertEqual([row['storage_key'] for row in report['cleanup']],report['canary_keys'])
        self.assertNotIn('private-signed-url',str(report))

    def test_evidence_is_private_and_records_cleanup_scope_before_first_provider_write(self):
        import json
        import tempfile
        from pathlib import Path
        def interrupted(origin,expiry_seconds,on_prepared):
            on_prepared({'status':'running','canary_keys':['exports/qualification/test/server.bin']})
            raise KeyboardInterrupt()
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'probe.json'
            with patch('library.management.commands.qualify_r2_private.qualify_r2',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
                call_command('qualify_r2_private',execute=True,origin='https://maison.example',output=str(target))
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            self.assertEqual(json.loads(target.read_text())['canary_keys'],['exports/qualification/test/server.bin'])
            with patch('library.management.commands.qualify_r2_private.qualify_r2') as run,self.assertRaises(CommandError):
                call_command('qualify_r2_private',execute=True,origin='https://maison.example',output=str(target))
            run.assert_not_called()


    def test_unsigned400_requires_exact_valid_xml_error_without_canary_bytes(self):
        canary=b'private synthetic canary bytes'
        xml=b'<?xml version="1.0"?><Error><Code>InvalidArgument</Code><Message>private provider details</Message></Error>'
        accepted,record=probe._unsigned_denial(400,xml,canary)
        self.assertTrue(accepted);self.assertEqual(record,{'status':400,'code':'InvalidArgument'})
        self.assertNotIn('private provider details',str(record))
        bad=[b'InvalidArgument',b'<Error><Code>AccessDenied</Code></Error>',b'<Error><Code>InvalidArgument',
            b'<Other><Code>InvalidArgument</Code></Other>',b'<Error><Code>InvalidArgument</Code><Code>InvalidArgument</Code></Error>',
            b'<Error><Code>InvalidArgument</Code><Message>'+canary+b'</Message></Error>',
            b'<!DOCTYPE Error [<!ENTITY x "InvalidArgument">]><Error><Code>&x;</Code></Error>']
        for body in bad:
            with self.subTest(body=body):self.assertFalse(probe._unsigned_denial(400,body,canary)[0])
        self.assertFalse(probe._unsigned_denial(200,xml,canary)[0])
        self.assertFalse(probe._unsigned_denial(403,canary,canary)[0])
        self.assertTrue(probe._unsigned_denial(403,b'<Error><Code>AccessDenied</Code></Error>',canary)[0])
