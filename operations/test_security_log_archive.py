"""Original security-log fixtures; no provider, real credentials or customer logs."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest import TestCase,skipUnless
from unittest.mock import patch,MagicMock
from .database_archive import ArchiveConfig,ArchiveError
from .security_log_archive import (LogConfig,SecurityLogs,RenderLogs,ROOT,RESOURCES,WORKSPACE,iso,packed,safe_row,redact,run_security_log_archive,security_log_failure,coded_error)
from .test_database_archive import FakeR2


def row(at,identity='original-log',message='Original harmless security event',resource=None):
    return {'id':identity,'timestamp':iso(at),'message':message,'labels':[{'name':'resource','value':resource or RESOURCES[0]},{'name':'level','value':'info'}]}


class API:
    def __init__(self,pages=None):self.calls=[];self.pages=pages
    def page(self,start,end):
        self.calls.append((start,end))
        if self.pages is not None:
            value=self.pages[len(self.calls)-1]
            if isinstance(value,Exception):raise value
            return value
        at=datetime.fromisoformat(start.replace('Z','+00:00'))+timedelta(seconds=1)
        return {'hasMore':False,'nextStartTime':end,'nextEndTime':end,'logs':[row(at,identity=start)]}


class RedactionTests(TestCase):
    def setUp(self):self.now=datetime(2026,11,20,12,tzinfo=timezone.utc)
    def test_source_allowlist_and_queries_credentials_and_action_paths_are_minimized(self):
        text='GET https://maison.example/en/password-reset/action-secret/?token=query-secret password=short-secret Authorization: Bearer bearer-secret'
        safe=safe_row(row(self.now,message=text),self.now-timedelta(seconds=1),self.now+timedelta(seconds=1))
        raw=json.dumps(safe)
        for secret in ['action-secret','query-secret','short-secret','bearer-secret']:self.assertNotIn(secret,raw)
        identity='20000000-0000-4000-8000-000000000001'
        event={'event':'earnalism.security.request','schema_version':1,'at':iso(self.now),'component':'web','method':'GET','route':'en/password-reset/<str:token>/','source_ip':'192.0.2.1','request_id':identity,'actor_id':identity,'status':200,'territory':'IN','password':'original-private-fixture','headers':{'Authorization':'fixture-never-keep'}}
        safe=safe_row(row(self.now,message=json.dumps(event)),self.now,self.now)
        self.assertEqual(safe['source']['actor_id'],identity);self.assertEqual(safe['source']['source_ip'],'192.0.2.1')
        self.assertNotIn('password',safe['source']);self.assertNotIn('headers',safe['source']);self.assertNotIn('original-private-fixture',json.dumps(safe))
    def test_maintenance_outcomes_and_fixed_diagnostics_are_preserved_without_nested_payloads(self):
        identity='20000000-0000-4000-8000-000000000001'
        event={'outcome':'partial_failure','run_id':identity,'source':'scheduled_export','commit':'0123456789abcdef0123456789abcdef01234567',
            'error_code':'security_log_provider_transport','started_at':iso(self.now),'finished_at':iso(self.now),
            'backup_status':'verified_archive','payload':'private-unknown',
            'security_logs':{'status':'failed','code':'security_log_deadline','coverage_status':'catching_up',
                'verified_window_end':iso(self.now),'requested_window_end':iso(self.now),'logs':15451,
                'pages':155,'adopted_manifest_count':2,'payload':{'token':'nested-private'},
                'message':'raw-private','token':'private-token'}}
        source=safe_row(row(self.now,message=json.dumps(event)),self.now,self.now)['source']
        self.assertEqual(source['run_id'],identity);self.assertEqual(source['outcome'],'partial_failure')
        self.assertEqual(source['commit'],event['commit']);self.assertEqual(source['error_code'],'security_log_provider_transport')
        self.assertEqual(source['backup_status'],'verified_archive');self.assertEqual(source['security_logs']['logs'],15451)
        self.assertEqual(len(source['security_logs']),8)
        raw=json.dumps(source)
        for secret in ['private-unknown','nested-private','raw-private','private-token']:self.assertNotIn(secret,raw)
        event['commit']='token=private-commit';event['run_id']='not-a-uuid';event['source']='https://example.test/verify-email/private-action/?token=private-query'
        event['security_logs']['code']='token=private-credential';event['security_logs']['pages']=-1
        source=safe_row(row(self.now,message=json.dumps(event)),self.now,self.now)['source']
        self.assertEqual(source['commit'],'[redacted-invalid-commit]');self.assertEqual(source['run_id'],'[redacted-invalid-identity]');self.assertNotIn('pages',source['security_logs'])
        for secret in ['private-action','private-query','private-credential']:self.assertNotIn(secret,json.dumps(source))

    def test_every_resource_timestamp_and_field_bound_is_checked(self):
        for change in [dict(resource='srv-unrelated'),dict(message='x'*32769)]:
            with self.assertRaises(ArchiveError):safe_row(row(self.now,**change),self.now,self.now)
        bad=row(self.now);bad['labels']*=2
        with self.assertRaises(ArchiveError):safe_row(bad,self.now,self.now)
        with self.assertRaises(ArchiveError):safe_row(row(self.now),self.now-timedelta(days=2),self.now-timedelta(days=1))
        self.assertNotIn('query-secret',redact('/auth/reset/?token=query-secret'))


@skipUnless(shutil.which('age') and shutil.which('age-keygen'),'actual age tools are required for cryptographic fixture tests')
class SecurityArchiveTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        generated=subprocess.run(['age-keygen'],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        match=re.search(rb'age1[0-9a-z]{58}',generated.stdout+generated.stderr)
        if not match:self.fail('Local age fixture generation failed.')
        self.recipient=match[0].decode();self.identity=Path(self.tmp.name)/'fixture-identity.txt';self.identity.write_bytes(generated.stdout);self.identity.chmod(0o600)
        self.archive=ArchiveConfig('https://'+'a'*32+'.r2.cloudflarestorage.com','original-security-fixture','fixture-key','fixture-secret')
        self.start=datetime(2026,11,20,12,tzinfo=timezone.utc);self.now=self.start+timedelta(hours=1)
        self.config=LogConfig('original-fixture-read-only',iso(self.start));self.client=FakeR2()
    def collector(self,api=None,config=None):return SecurityLogs(self.archive,config or self.config,self.recipient,client=self.client,api=api or API())
    def test_actual_age_encrypt_upload_retrieve_decrypt_and_checkpoint_after_complete_readback(self):
        collector=self.collector();result=collector.run(self.now)
        self.assertEqual(result['status'],'verified_security_log_archive');self.assertEqual(result['logs'],1)
        ciphertext=next(value for key,value in self.client.objects.items() if key.endswith('.jsonl.age'))
        self.assertNotIn(b'Original harmless security event',ciphertext)
        encrypted=Path(self.tmp.name)/'fixture.age';encrypted.write_bytes(ciphertext)
        decrypted=subprocess.run(['age','--decrypt','--identity',str(self.identity),str(encrypted)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        decoded=json.loads(decrypted.stdout);self.assertEqual(decoded['message'],'Original harmless security event');self.assertEqual(decoded['labels']['resource'],RESOURCES[0])
        checkpoint=next(key for key in self.client.objects if '/checkpoints/' in key)
        self.assertEqual(collector._checkpoint(checkpoint)['window_end'],result['window_end'])
        self.assertEqual(collector.run(self.now)['status'],'already_archived')
        self.assertEqual(self.client.deleted,[])
    def test_pagination_uses_exact_supplied_times_and_deduplicates_identical_boundary_log(self):
        middle=self.start+timedelta(minutes=10);upper=self.now-timedelta(minutes=5)
        first=row(middle,'original-boundary')
        pages=[{'hasMore':True,'nextStartTime':iso(middle),'nextEndTime':iso(upper),'logs':[first]}, {'hasMore':False,'nextStartTime':iso(upper),'nextEndTime':iso(upper),'logs':[first,row(middle+timedelta(minutes=1),'original-second')]}]
        api=API(pages);result=self.collector(api).run(self.now)
        self.assertEqual(result['logs'],2);self.assertEqual(api.calls[1],(iso(middle),iso(upper)))
    def test_incomplete_loop_cross_resource_and_bounds_never_commit_checkpoint(self):
        end=self.now-timedelta(minutes=5)
        cases=[API([{'hasMore':True,'nextStartTime':iso(self.start),'nextEndTime':iso(end),'logs':[]}]),API([{'hasMore':False,'nextStartTime':iso(end),'nextEndTime':iso(end),'logs':[row(self.start,resource='srv-unrelated')]}]),API([{'hasMore':True,'nextStartTime':iso(self.start+timedelta(minutes=1)),'nextEndTime':iso(end),'logs':[]}])]
        for api in cases:
            self.client=FakeR2()
            config=LogConfig('fixture',iso(self.start),max_pages=1)
            with self.assertRaises(ArchiveError):self.collector(api,config).run(self.now)
            self.assertFalse(any('/checkpoints/' in key for key in self.client.objects))
    def test_corrupt_ciphertext_readback_never_commits_manifest_or_checkpoint(self):
        original=self.client.get_object
        def corrupt(**kwargs):
            result=original(**kwargs)
            if kwargs['Key'].endswith('.jsonl.age'):
                raw=result['Body'].read();result['Body']=io.BytesIO(raw[:-1]+bytes([raw[-1]^1]))
            return result
        self.client.get_object=corrupt
        with self.assertRaises(ArchiveError):self.collector().run(self.now)
        self.assertFalse(any(key.endswith('.json') for key in self.client.objects))
    def test_manifest_verified_before_checkpoint_and_missing_checkpoint_retries_without_skipping(self):
        original=self.client.put_object
        def fail_checkpoint(**kwargs):
            if '/checkpoints/' in kwargs['Key']:raise RuntimeError('original-private-provider-error')
            return original(**kwargs)
        self.client.put_object=fail_checkpoint
        with self.assertRaises(ArchiveError) as failed:self.collector().run(self.now)
        self.assertNotIn('original-private-provider-error',str(failed.exception))
        self.assertTrue(any(key.endswith('.manifest.json') for key in self.client.objects));self.assertFalse(any('/checkpoints/' in key for key in self.client.objects))
        self.client.put_object=original;api=API();result=self.collector(api).run(self.now)
        self.assertEqual(api.calls,[]);self.assertEqual(result['adopted_manifest_count'],1);self.assertEqual(result['status'],'verified_security_log_archive')
    def test_checkpoint_and_adoption_require_ciphertext_ownership_metadata(self):
        collector=self.collector();collector.run(self.now)
        checkpoint=next(key for key in self.client.objects if '/checkpoints/' in key)
        cipher=next(key for key in self.client.objects if key.endswith('.jsonl.age'))
        self.client.metadata[cipher]['maison-security-logs']='unrelated'
        with self.assertRaises(ArchiveError):collector._checkpoint(checkpoint)
        del self.client.objects[checkpoint]
        with self.assertRaises(ArchiveError):self.collector().run(self.now)
        self.assertFalse(any('/checkpoints/' in key for key in self.client.objects))

    def test_adoption_accepts_known_redaction_versions_and_rejects_unknown(self):
        for version in (1,2,3):
            self.client=FakeR2();collector=self.collector();collector.run(self.now)
            for key in list(self.client.objects):
                if '/checkpoints/' in key:del self.client.objects[key]
                elif key.endswith('.manifest.json'):
                    manifest=json.loads(self.client.objects[key]);self.assertEqual(manifest['redaction_version'],2)
                    manifest['redaction_version']=version;raw=packed(manifest);self.client.objects[key]=raw
                    self.client.metadata[key]['sha256']=hashlib.sha256(raw).hexdigest()
            if version in (1,2):
                result=self.collector(API()).run(self.now);self.assertEqual(result['adopted_manifest_count'],1)
            else:
                with self.assertRaises(ArchiveError):self.collector(API()).run(self.now)

    def test_checkpoint_lost_response_and_conflicting_retry_preserve_first_verified_window(self):
        original=self.client.put_object
        def lost_response(**kwargs):
            result=original(**kwargs)
            if '/checkpoints/' in kwargs['Key']:raise RuntimeError('original lost response fixture')
            return result
        self.client.put_object=lost_response
        with self.assertRaises(ArchiveError):self.collector().run(self.now)
        self.client.put_object=original;api=API();collector=self.collector(api)
        self.assertEqual(collector.run(self.now)['status'],'already_archived');self.assertEqual(api.calls,[])
        key=next(key for key in self.client.objects if '/checkpoints/' in key);previous=self.client.objects[key]
        changed=packed({'original':'different checkpoint body'})
        with self.assertRaises(ArchiveError):collector._put(key,changed,'application/json',hashlib.sha256(changed).hexdigest(),len(changed))
        self.assertEqual(self.client.objects[key],previous)

    def test_interrupted_bootstrap_resumes_verified_end_without_overlap_and_signals_full_coverage(self):
        requested=self.now+timedelta(days=2);api=API();original=api.page
        def interrupted(start,end):
            if datetime.fromisoformat(start.replace('Z','+00:00')).day==21:raise coded_error('security_log_provider_transport','original private fixture error')
            return original(start,end)
        api.page=interrupted;collector=self.collector(api)
        with self.assertRaises(ArchiveError) as failed:collector.run(requested)
        report=security_log_failure(failed.exception)
        self.assertEqual(report['code'],'security_log_provider_transport');self.assertEqual(report['coverage_status'],'catching_up')
        verified=datetime(2026,11,21,tzinfo=timezone.utc)
        self.assertEqual(report['verified_window_end'],iso(verified));self.assertEqual(report['requested_window_end'],iso(requested-timedelta(minutes=5)))
        key=max(key for key in self.client.objects if '/checkpoints/' in key);checkpoint=collector._checkpoint(key)
        self.assertEqual(checkpoint['coverage_status'],'catching_up');self.assertEqual(checkpoint['window_end'],iso(verified))
        retry=API();result=self.collector(retry).run(requested)
        self.assertEqual(retry.calls[0][0],iso(verified));self.assertEqual(result['coverage_status'],'complete');self.assertEqual(result['verified_window_end'],result['requested_window_end'])

    def old_piece(self,start,end):
        with tempfile.TemporaryDirectory() as directory:return self.collector()._window(start,end,directory)

    def test_adopts_only_complete_exact_contiguous_old_pairs_and_validates_legacy_checkpoint(self):
        first=datetime(2026,11,21,tzinfo=timezone.utc);second=first+timedelta(days=1)
        self.old_piece(self.start,first);self.old_piece(first,second)
        api=API();collector=self.collector(api);result=collector.run(self.now+timedelta(days=2))
        self.assertEqual(result['adopted_manifest_count'],2);self.assertEqual(api.calls[0][0],iso(second));self.assertEqual(result['coverage_status'],'complete')
        key=max(key for key in self.client.objects if '/checkpoints/' in key);value=collector._checkpoint(key)
        value.pop('coverage_status');value.pop('requested_window_end')
        raw=packed(value);self.client.objects[key]=raw;self.client.metadata[key]['sha256']=hashlib.sha256(raw).hexdigest()
        self.assertEqual(collector._checkpoint(key)['window_end'],result['window_end'])
        legacy_retry=API();self.collector(legacy_retry).run(self.now+timedelta(days=3))
        self.assertEqual(legacy_retry.calls[0][0],iso(datetime.fromisoformat(result['window_end'].replace('Z','+00:00'))-timedelta(days=1)))

    def test_later_old_pair_cannot_skip_an_unverified_earlier_window_and_corruption_cannot_be_adopted(self):
        first=datetime(2026,11,21,tzinfo=timezone.utc);second=first+timedelta(days=1)
        self.old_piece(first,second)
        api=API([coded_error('security_log_provider_transport','private-fixture')])
        with self.assertRaises(ArchiveError):self.collector(api).run(self.now+timedelta(days=2))
        self.assertEqual(api.calls[0][0],iso(self.start));self.assertFalse(any('/checkpoints/' in key for key in self.client.objects))
        self.client=FakeR2();entry=self.old_piece(self.start,first);manifest=self.collector()._manifest(entry['key']);cipher=manifest['ciphertext_key']
        raw=self.client.objects[cipher];self.client.objects[cipher]=raw[:-1]+bytes([raw[-1]^1])
        api=API()
        with self.assertRaises(ArchiveError) as failed:self.collector(api).run(self.now+timedelta(days=2))
        self.assertEqual(security_log_failure(failed.exception)['code'],'security_log_integrity');self.assertEqual(api.calls,[]);self.assertFalse(any('/checkpoints/' in key for key in self.client.objects))

    def test_complete_normal_overlap_does_not_rewrite_old_checkpoint_keys(self):
        requested=self.now+timedelta(days=2);self.collector().run(requested)
        original={key:value for key,value in self.client.objects.items() if '/checkpoints/' in key}
        api=API();result=self.collector(api).run(requested+timedelta(days=1))
        self.assertEqual(api.calls[0][0],iso(requested-timedelta(minutes=5)-timedelta(days=1)))
        self.assertEqual(result['coverage_status'],'complete')
        for key,value in original.items():self.assertEqual(self.client.objects[key],value)

    def test_partial_progress_checkpoints_follow_hold_and_expiry_pair_rules(self):
        requested=self.now+timedelta(days=2);api=API();original=api.page
        def interrupted(start,end):
            if datetime.fromisoformat(start.replace('Z','+00:00')).day==21:raise ArchiveError('Original interrupted fixture')
            return original(start,end)
        api.page=interrupted;collector=self.collector(api)
        with self.assertRaises(ArchiveError):collector.run(requested)
        key=max(key for key in self.client.objects if '/checkpoints/' in key);value=collector._checkpoint(key)
        manifest_key=value['manifests'][0]['key'];manifest=collector._manifest(manifest_key)
        self.client.metadata[manifest['ciphertext_key']]['retention-hold']='true'
        old=requested+timedelta(days=181);self.assertEqual(collector.retention(old,True)['removed_pairs'],0);self.assertIn(key,self.client.objects)
        self.client.metadata[manifest['ciphertext_key']].pop('retention-hold');self.assertEqual(collector.retention(old,True)['removed_pairs'],1);self.assertNotIn(key,self.client.objects)

    def test_lost_partial_checkpoint_response_resumes_without_rereading_verified_window(self):
        original=self.client.put_object;lost=[False]
        def lost_response(**kwargs):
            result=original(**kwargs)
            if '/checkpoints/' in kwargs['Key'] and not lost[0]:
                lost[0]=True;raise RuntimeError('original lost partial checkpoint fixture')
            return result
        self.client.put_object=lost_response;requested=self.now+timedelta(days=2)
        with self.assertRaises(ArchiveError):self.collector().run(requested)
        key=max(key for key in self.client.objects if '/checkpoints/' in key);checkpoint=self.collector()._checkpoint(key)
        self.assertEqual(checkpoint['coverage_status'],'catching_up')
        api=API();result=self.collector(api).run(requested)
        self.assertEqual(api.calls[0][0],checkpoint['window_end']);self.assertEqual(result['coverage_status'],'complete')

    def test_native_retention_gap_fails_instead_of_advancing_checkpoint(self):
        self.collector().run(self.now);before=set(self.client.objects)
        with self.assertRaises(ArchiveError):self.collector().run(self.now+timedelta(days=8))
        self.assertEqual(set(self.client.objects),before)
        api=API()
        with self.assertRaises(ArchiveError):self.collector(api,LogConfig('fixture',iso(self.start-timedelta(days=8)))).run(self.now)
        self.assertEqual(api.calls,[])
    def test_later_collection_overlaps_and_utc_day_manifests_are_contiguous(self):
        self.collector().run(self.now);api=API();collector=self.collector(api);result=collector.run(self.now+timedelta(days=2))
        self.assertEqual(api.calls[0][0],iso(self.start));self.assertEqual(result['manifest_count'],3)
        latest=max(key for key in self.client.objects if '/checkpoints/' in key)
        self.assertEqual(collector._checkpoint(latest)['window_end'],result['window_end'])
    def test_expiry_only_owns_180_day_pairs_checkpoints_and_holds(self):
        collector=self.collector();collector.run(self.now)
        manifest_key=next(key for key in self.client.objects if key.endswith('.manifest.json'));manifest=collector._manifest(manifest_key)
        unrelated='backups/v1/daily/2020-01-01/private.dump.age';self.client.objects[unrelated]=b'preserved backup'
        self.client.objects[ROOT+'windows/manual-private-file']=b'preserved unknown'
        self.client.metadata[manifest['ciphertext_key']]['legal-hold']='true'
        old=self.now+timedelta(days=181)
        self.assertEqual(collector.retention(old,True)['removed_pairs'],0)
        self.assertIn(manifest_key,self.client.objects);self.assertTrue(any('/checkpoints/' in key for key in self.client.objects))
        self.client.metadata[manifest['ciphertext_key']].pop('legal-hold')
        result=collector.retention(old,True);self.assertEqual(result['removed_pairs'],1);self.assertFalse(any('/checkpoints/' in key for key in self.client.objects))
        self.assertIn(unrelated,self.client.objects);self.assertIn(ROOT+'windows/manual-private-file',self.client.objects)
        self.assertTrue(all(key.startswith(ROOT) for key in self.client.deleted))
    def test_storage_inventory_paginates_exact_prefix_and_fails_unknown_completeness(self):
        collector=self.collector();prefix=ROOT+'windows/'
        for index in range(1100):self.client.objects[prefix+f'unknown-{index:04}']=b'original'
        calls=[]
        def listed(Bucket,Prefix,MaxKeys,ContinuationToken=None):
            calls.append((Prefix,ContinuationToken));keys=sorted(key for key in self.client.objects if key.startswith(Prefix));offset=int(ContinuationToken or '0')
            part=keys[offset:offset+MaxKeys];more=offset+len(part)<len(keys)
            return {'Contents':[{'Key':key} for key in part],'IsTruncated':more,**({'NextContinuationToken':str(offset+len(part))} if more else {})}
        self.client.list_objects_v2=listed
        self.assertEqual(len(collector._inventory(prefix)),1100);self.assertEqual(len(calls),2);self.assertTrue(all(item[0]==prefix for item in calls))
        self.client.list_objects_v2=lambda **kwargs:{'Contents':[]}
        with self.assertRaises(ArchiveError):collector._inventory(prefix)

    def test_bootstrap_capacity_changes_only_security_budget_and_cap_exhaustion_is_incomplete(self):
        from unittest.mock import patch
        with patch('operations.security_log_archive.time.monotonic',return_value=1000):collector=self.collector()
        self.assertEqual(self.archive.max_seconds,300);self.assertEqual(collector.archive.config.max_seconds,1200);self.assertEqual(collector.archive.deadline,2200)
        self.assertEqual(collector.config.max_pages,500);self.assertEqual(collector.config.max_lines,50000)
        self.assertEqual(collector.config.max_plain_bytes,20*1024**2);self.assertEqual(collector.archive.config.max_bytes,25*1024**2)
        api=API();calls=[]
        def unfinished(start,end):
            calls.append((start,end));lower=datetime.fromisoformat(start.replace('Z','+00:00'))+timedelta(seconds=1)
            return {'hasMore':True,'nextStartTime':iso(lower),'nextEndTime':end,'logs':[]}
        api.page=unfinished;collector=self.collector(api)
        with self.assertRaises(ArchiveError):list(collector._rows(self.start,self.now))
        self.assertEqual(len(calls),500);self.assertEqual(self.client.objects,{})

    def test_inventory_truncation_and_unknown_ciphertext_metadata_stop_deletion(self):
        collector=self.collector();collector.run(self.now);self.client.truncated=True
        with self.assertRaises(ArchiveError):collector.retention(self.now+timedelta(days=181),True)
        self.assertEqual(self.client.deleted,[]);self.client.truncated=False
        cipher=next(key for key in self.client.objects if key.endswith('.jsonl.age'));self.client.metadata[cipher]['maison-security-logs']='foreign'
        with self.assertRaises(ArchiveError):collector.retention(self.now+timedelta(days=181),True)
        self.assertEqual(self.client.deleted,[])


class RenderTransportTests(TestCase):
    def response(self,status=200,body=None,retry_after=None):
        value=MagicMock();value.status=status;value.getheader.return_value=retry_after;value.isclosed.return_value=False
        value.read.side_effect=[body if body is not None else packed({'hasMore':False,'nextStartTime':'2026-11-20T01:00:00Z','nextEndTime':'2026-11-20T01:00:00Z','logs':[]}),b'']
        return value

    def real_connection(self,body,*,chunked=False,declared_length=None,status=200,retry_after=None):
        import http.client,socket
        client,server=socket.socketpair();self.addCleanup(client.close);self.addCleanup(server.close)
        if chunked:
            headers=b'HTTP/1.1 200 OK\r\nConnection: close\r\nTransfer-Encoding: chunked\r\n\r\n'
            payload=f'{len(body):x}\r\n'.encode()+body+b'\r\n0\r\n\r\n'
        else:
            quota=f'Retry-After: {retry_after}\r\n' if retry_after is not None else ''
            headers=f'HTTP/1.1 {status} OriginalFixture\r\nConnection: close\r\n{quota}Content-Length: {len(body) if declared_length is None else declared_length}\r\n\r\n'.encode();payload=body
        server.sendall(headers+payload);server.shutdown(socket.SHUT_WR)
        connection=http.client.HTTPConnection('original-fixture.invalid');connection.sock=client
        return connection

    def test_real_http_response_short_and_chunked_eof_do_not_retry_closed_socket(self):
        from time import monotonic
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');end='2026-11-20T01:00:00Z'
        expected={'hasMore':False,'nextStartTime':end,'nextEndTime':end,'logs':[]};body=packed(expected)
        for chunked in [False,True]:
            connection=self.real_connection(body,chunked=chunked)
            with self.subTest(chunked=chunked),patch('operations.security_log_archive.http.client.HTTPSConnection',return_value=connection) as factory,patch('operations.security_log_archive.time.sleep') as sleep:
                self.assertEqual(RenderLogs(config,monotonic()+30).page(config.inception,end),expected)
                self.assertEqual(factory.call_count,1);sleep.assert_not_called();self.assertIsNone(connection.sock)

    def test_real_http_response_truncation_is_not_success_even_when_json_body_is_valid(self):
        from time import monotonic
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');end='2026-11-20T01:00:00Z';body=packed({'hasMore':False,'nextStartTime':end,'nextEndTime':end,'logs':[]})
        connections=[self.real_connection(body,declared_length=len(body)+10) for _ in range(3)]
        with patch('operations.security_log_archive.http.client.HTTPSConnection',side_effect=connections) as factory,patch('operations.security_log_archive.time.sleep'):
            with self.assertRaises(ArchiveError):RenderLogs(config,monotonic()+30).page(config.inception,end)
            self.assertEqual(factory.call_count,3)

    def test_transport_and_503_retry_exact_page_with_fresh_connections_and_bounded_timeout(self):
        from time import monotonic
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');connections=[MagicMock() for _ in range(3)]
        connections[0].request.side_effect=TimeoutError('original-private-transport-detail')
        failed=self.response(503);connections[1].getresponse.return_value=failed
        connections[2].getresponse.return_value=self.response()
        with patch('operations.security_log_archive.http.client.HTTPSConnection',side_effect=connections) as factory,patch('operations.security_log_archive.time.sleep') as sleep:
            result=RenderLogs(config,monotonic()+30).page('2026-11-20T00:00:00Z','2026-11-20T01:00:00Z')
        self.assertEqual(result['logs'],[]);self.assertEqual(factory.call_count,3);self.assertTrue(all(0<call.kwargs['timeout']<=10 for call in factory.call_args_list))
        self.assertEqual([item.request.call_args for item in connections],[connections[0].request.call_args]*3)
        self.assertEqual(sleep.call_count,2);failed.read.assert_not_called()
        for item in connections:item.close.assert_called_once()

    def test_partial_page_transport_failure_discards_uncommitted_bytes_and_repeats_full_get(self):
        from time import monotonic
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');connections=[MagicMock(),MagicMock()]
        partial=self.response();partial.read.side_effect=[b'{"logs":[{"message":"original-private-partial"}]',TimeoutError('original-private-read-detail')]
        connections[0].getresponse.return_value=partial;connections[1].getresponse.return_value=self.response()
        with patch('operations.security_log_archive.http.client.HTTPSConnection',side_effect=connections),patch('operations.security_log_archive.time.sleep'):
            self.assertEqual(RenderLogs(config,monotonic()+30).page(config.inception,'2026-11-20T01:00:00Z')['logs'],[])
        self.assertEqual(connections[0].request.call_args,connections[1].request.call_args)
        connections[0].close.assert_called_once()

    def test_auth_and_other_4xx_fail_without_retry_or_reading_error_body(self):
        from time import monotonic
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z')
        for status in [400,401,403,404,408]:
            with self.subTest(status=status),patch('operations.security_log_archive.http.client.HTTPSConnection') as factory,patch('operations.security_log_archive.time.sleep') as sleep:
                response=self.response(status);factory.return_value.getresponse.return_value=response
                with self.assertRaises(ArchiveError) as failed:RenderLogs(config,monotonic()+30).page(config.inception,'2026-11-20T01:00:00Z')
                self.assertNotIn(config.token,str(failed.exception));self.assertEqual(factory.call_count,1);response.read.assert_not_called();sleep.assert_not_called()
                self.assertEqual(security_log_failure(failed.exception)['code'],'security_log_provider_auth' if status in (401,403) else 'security_log_provider_http')

    def test_429_retry_after_and_transport_exhaustion_are_bounded(self):
        from time import monotonic
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');connections=[MagicMock(),MagicMock()]
        connections[0].getresponse.return_value=self.response(429,retry_after='1');connections[1].getresponse.return_value=self.response()
        with patch('operations.security_log_archive.http.client.HTTPSConnection',side_effect=connections) as factory,patch('operations.security_log_archive.time.sleep') as sleep:
            self.assertEqual(RenderLogs(config,monotonic()+30).page(config.inception,'2026-11-20T01:00:00Z')['logs'],[])
            self.assertEqual(factory.call_count,2);sleep.assert_called_once_with(2)
        with patch('operations.security_log_archive.http.client.HTTPSConnection') as factory,patch('operations.security_log_archive.time.sleep') as sleep:
            factory.return_value.request.side_effect=ConnectionResetError('original-private-transport-detail')
            with self.assertRaises(ArchiveError) as failed:RenderLogs(config,monotonic()+30).page(config.inception,'2026-11-20T01:00:00Z')
            self.assertEqual(factory.call_count,3);self.assertEqual(sleep.call_count,2);self.assertNotIn('original-private',str(failed.exception))
            self.assertEqual(security_log_failure(failed.exception)['code'],'security_log_provider_transport')

    def test_quota_retry_waits_58_or_60_seconds_only_inside_the_same_deadline(self):
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');end='2026-11-20T01:00:00Z'
        for wait in [58,60]:
            clock=[10.0];connections=[MagicMock(),MagicMock()]
            connections[0].getresponse.return_value=self.response(429,retry_after=str(wait));connections[1].getresponse.return_value=self.response()
            def slept(seconds):clock[0]+=seconds
            with self.subTest(wait=wait),patch('operations.security_log_archive.time.monotonic',side_effect=lambda:clock[0]),patch('operations.security_log_archive.time.sleep',side_effect=slept) as sleep,patch('operations.security_log_archive.http.client.HTTPSConnection',side_effect=connections) as factory:
                self.assertEqual(RenderLogs(config,71).page(config.inception,end)['logs'],[])
                actual=min(60,wait+1)
                sleep.assert_called_once_with(actual);self.assertEqual(factory.call_count,2)
                self.assertLessEqual(factory.call_args_list[1].kwargs['timeout'],61-actual)

    def test_real_zero_retry_after_waits_across_reset_rollover_before_success(self):
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');end='2026-11-20T01:00:00Z'
        expected={'hasMore':False,'nextStartTime':end,'nextEndTime':end,'logs':[]};body=packed(expected)
        connections=[self.real_connection(b'original quota fixture',status=429,retry_after='0'),self.real_connection(b'original quota fixture',status=429,retry_after='0'),self.real_connection(body)]
        clock=[10.0]
        def slept(seconds):clock[0]+=seconds
        with patch('operations.security_log_archive.time.monotonic',side_effect=lambda:clock[0]),patch('operations.security_log_archive.time.sleep',side_effect=slept) as sleep,patch('operations.security_log_archive.http.client.HTTPSConnection',side_effect=connections) as factory:
            self.assertEqual(RenderLogs(config,40).page(config.inception,end),expected)
            self.assertEqual(factory.call_count,3);self.assertEqual([item.args[0] for item in sleep.call_args_list],[1,1]);self.assertEqual(clock[0],12)

    def test_quota_wait_over_60_or_remaining_budget_fails_without_sleep_or_retry(self):
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z');end='2026-11-20T01:00:00Z'
        for header,deadline in [('61',100),('nan',100),('inf',100),('invalid',100),('58',40)]:
            with self.subTest(header=header,deadline=deadline),patch('operations.security_log_archive.time.monotonic',return_value=10),patch('operations.security_log_archive.time.sleep') as sleep,patch('operations.security_log_archive.http.client.HTTPSConnection') as factory:
                factory.return_value.getresponse.return_value=self.response(429,retry_after=header)
                with self.assertRaises(ArchiveError):RenderLogs(config,deadline).page(config.inception,end)
                self.assertEqual(factory.call_count,1);sleep.assert_not_called()

    def test_deadline_invalid_payload_and_tls_fail_without_unsafe_retry(self):
        import ssl
        config=LogConfig('original-private-fixture','2026-11-20T00:00:00Z')
        with patch('operations.security_log_archive.time.monotonic',return_value=10),patch('operations.security_log_archive.http.client.HTTPSConnection') as factory:
            with self.assertRaises(ArchiveError):RenderLogs(config,10).page(config.inception,'2026-11-20T01:00:00Z')
            factory.assert_not_called()
        with patch('operations.security_log_archive.time.monotonic',return_value=10),patch('operations.security_log_archive.http.client.HTTPSConnection') as factory,patch('operations.security_log_archive.time.sleep') as sleep:
            factory.return_value.request.side_effect=TimeoutError('private')
            with self.assertRaises(ArchiveError):RenderLogs(config,10.1).page(config.inception,'2026-11-20T01:00:00Z')
            self.assertEqual(factory.call_count,1);self.assertLessEqual(factory.call_args.kwargs['timeout'],.101);sleep.assert_not_called()
        for invalid in [b'original-private-bad-json',b'x'*(4*1024**2+1)]:
            with patch('operations.security_log_archive.http.client.HTTPSConnection') as factory,patch('operations.security_log_archive.time.sleep') as sleep:
                factory.return_value.getresponse.return_value=self.response(body=invalid)
                with self.assertRaises(ArchiveError) as failed:RenderLogs(config,10**12).page(config.inception,'2026-11-20T01:00:00Z')
                self.assertEqual(factory.call_count,1);sleep.assert_not_called();self.assertNotIn('original-private',str(failed.exception))
        with patch('operations.security_log_archive.http.client.HTTPSConnection') as factory,patch('operations.security_log_archive.time.sleep') as sleep:
            factory.return_value.request.side_effect=ssl.SSLCertVerificationError(1,'original-private-certificate-detail')
            with self.assertRaises(ArchiveError):RenderLogs(config,10**12).page(config.inception,'2026-11-20T01:00:00Z')
            self.assertEqual(factory.call_count,1);sleep.assert_not_called()

    def test_fixed_host_owner_resources_and_forward_pagination_are_the_only_request(self):
        config=LogConfig('original-transport-token','2026-11-20T00:00:00Z')
        from time import monotonic
        start='2026-11-20T00:00:00Z';end='2026-11-20T01:00:00Z'
        result={'hasMore':False,'nextStartTime':end,'nextEndTime':end,'logs':[]}
        with patch('operations.security_log_archive.http.client.HTTPSConnection') as transport:
            response=transport.return_value.getresponse.return_value;response.status=200;response.isclosed.return_value=False;response.read.side_effect=[packed(result),b'']
            self.assertEqual(RenderLogs(config,monotonic()+30).page(start,end),result)
            self.assertEqual(transport.call_args.args,('api.render.com',))
            method,path=transport.return_value.request.call_args.args
            self.assertEqual(transport.return_value.request.call_args.kwargs['headers']['User-Agent'],'Earnalism-Security-Archive/1')
            from urllib.parse import parse_qs,urlsplit
            parsed=urlsplit(path);query=parse_qs(parsed.query)
            self.assertEqual(method,'GET');self.assertEqual(parsed.path,'/v1/logs');self.assertEqual(query['ownerId'],[WORKSPACE]);self.assertEqual(query['resource'],list(RESOURCES));self.assertEqual(query['direction'],['forward'])
        with patch('operations.security_log_archive.http.client.HTTPSConnection') as transport:
            transport.return_value.getresponse.return_value.status=403
            with self.assertRaises(ArchiveError) as failed:RenderLogs(config,monotonic()+30).page(start,end)
            self.assertNotIn(config.token,str(failed.exception))


class ScheduledIntegrationTests(TestCase):
    def test_feature_off_needs_no_log_credentials_and_does_not_read_backup_recipient(self):
        with patch.dict(os.environ,{},clear=True):self.assertEqual(run_security_log_archive(None),{'status':'disabled'})
        env={'SECURITY_LOG_ARCHIVE_ENABLED':'true','RENDER_LOG_READ_TOKEN':'fixture','SECURITY_LOG_INCEPTION_UTC':'2026-11-20T00:00:00Z','BACKUP_AGE_RECIPIENT':'age1'+'a'*58}
        with patch.dict(os.environ,env,clear=True),self.assertRaises(ArchiveError):run_security_log_archive(None)
    def test_database_failure_does_not_skip_security_collection(self):
        from .scheduled_export import main
        env={'BACKUP_R2_ENDPOINT':'https://'+'a'*32+'.r2.cloudflarestorage.com','BACKUP_R2_BUCKET':'original-security-fixture','BACKUP_R2_KEY_ID':'fixture','BACKUP_R2_SECRET':'never-echo-this'}
        with patch.dict(os.environ,env,clear=True),patch('operations.scheduled_export.export_database',side_effect=OSError('never-echo-this')),patch('operations.scheduled_export.run_security_log_archive',return_value={'status':'verified_security_log_archive'}) as logs,patch('builtins.print') as output:
            self.assertEqual(main([]),1);logs.assert_called_once()
        raw=output.call_args.args[0];result=json.loads(raw)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['code'],'backup_archive_failed');self.assertEqual(result['security_logs']['status'],'verified_security_log_archive');self.assertNotIn('never-echo-this',raw)

    def test_returned_partial_coverage_is_not_a_successful_cron_and_safe_codes_never_echo_details(self):
        from .scheduled_export import main
        env={'BACKUP_R2_ENDPOINT':'https://'+'a'*32+'.r2.cloudflarestorage.com','BACKUP_R2_BUCKET':'original-security-fixture','BACKUP_R2_KEY_ID':'fixture','BACKUP_R2_SECRET':'original-private-secret'}
        report={'ciphertext_bytes':10,'ciphertext_sha256':'a'*64}
        for logs in [{'status':'verified_security_log_archive','coverage_status':'catching_up'}, {'status':'partial','coverage_status':'catching_up'}]:
            with patch.dict(os.environ,env,clear=True),patch('operations.scheduled_export.export_database',return_value=report),patch('operations.scheduled_export.Archive') as archive,patch('operations.scheduled_export.run_security_log_archive',return_value=logs),patch('builtins.print') as output:
                archive.return_value.upload.return_value=[];archive.return_value.retention.return_value={'dry_run':True}
                self.assertEqual(main([]),1);self.assertEqual(json.loads(output.call_args.args[0])['status'],'partial_failure')
        for error,code in [(ArchiveError('Security-log collection exceeded its time budget.'),'security_log_deadline'),(ArchiveError('Render log pagination did not complete within its bound.'),'security_log_page_bound'),(coded_error('security_log_provider_rate_limited','original-private-provider-payload'),'security_log_provider_rate_limited')]:
            result=security_log_failure(error);self.assertEqual(result['code'],code);self.assertNotIn('original-private',json.dumps(result))

    def test_log_failure_cannot_turn_verified_backup_into_false_cron_success(self):
        from .scheduled_export import main
        env={'BACKUP_R2_ENDPOINT':'https://'+'a'*32+'.r2.cloudflarestorage.com','BACKUP_R2_BUCKET':'original-security-fixture','BACKUP_R2_KEY_ID':'fixture','BACKUP_R2_SECRET':'never-echo-this'}
        report={'ciphertext_bytes':10,'ciphertext_sha256':'a'*64}
        with patch.dict(os.environ,env,clear=True),patch('operations.scheduled_export.export_database',return_value=report),patch('operations.scheduled_export.Archive') as archive,patch('operations.scheduled_export.run_security_log_archive',side_effect=ArchiveError('never-echo-this')),patch('builtins.print') as output:
            archive.return_value.upload.return_value=[];archive.return_value.retention.return_value={'dry_run':True}
            self.assertEqual(main([]),1)
        raw=output.call_args.args[0];result=json.loads(raw)
        self.assertEqual(result['status'],'partial_failure');self.assertEqual(result['backup_status'],'verified_archive');self.assertEqual(result['security_logs']['status'],'failed');self.assertNotIn('never-echo-this',raw)
