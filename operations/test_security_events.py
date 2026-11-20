"""Security metadata must be useful without collecting request content/secrets."""
import json
import io
import logging.config
import copy
from django.conf import settings
import uuid
from types import SimpleNamespace
from unittest.mock import Mock,patch
from django.http import HttpResponse
from django.test import RequestFactory,SimpleTestCase,override_settings
from .security_events import request_event,emit_request_event
from .middleware import RequestContextMiddleware

class SecurityEventTests(SimpleTestCase):
 def request(self):
  request=RequestFactory().post('/en/verify-email/PRIVATE-PATH-TOKEN/?token=SECRET-QUERY',data={'password':'PRIVATE-PASSWORD','note':'PRIVATE-NOTE'},HTTP_AUTHORIZATION='Bearer PRIVATE-BEARER',HTTP_COOKIE='session=PRIVATE-COOKIE')
  request.request_id=str(uuid.uuid4());request.territory='IN';request.trusted_client_ip='203.0.113.10';request.resolver_match=SimpleNamespace(route='<str:locale>/verify-email/<str:token>/')
  request._cached_user=SimpleNamespace(is_authenticated=True,public_id=uuid.uuid4())
  request.user=Mock(side_effect=AssertionError('Never resolve lazy authentication for logs'))
  return request
 def test_only_allowlisted_metadata_not_raw_paths_bodies_queries_or_credentials(self):
  event=request_event(self.request(),HttpResponse(status=403),12.9);text=json.dumps(event)
  self.assertEqual(set(event),{'event','schema_version','at','component','request_id','method','route','status','duration_ms','territory','actor_id','source_ip'})
  self.assertEqual(event['route'],'<str:locale>/verify-email/<str:token>/');self.assertEqual(event['source_ip'],'203.0.113.10');self.assertEqual(event['duration_ms'],12)
  self.assertNotIn('PRIVATE-',text);self.assertNotIn('SECRET-QUERY',text);self.assertTrue(event['at'].endswith('Z'))
 def test_unmatched_or_untrusted_identity_never_falls_back_to_raw_headers(self):
  request=self.request();request.resolver_match=None;request.trusted_client_ip=None;del request._cached_user
  request.META['HTTP_CF_CONNECTING_IP']='198.51.100.20'
  event=request_event(request,HttpResponse(),-2);self.assertEqual(event['route'],'unmatched');self.assertIsNone(event['actor_id']);self.assertIsNone(event['source_ip']);self.assertEqual(event['duration_ms'],0)
 def test_log_transport_failure_does_not_change_response_or_expose_exception(self):
  with patch('operations.security_events.logger.info',side_effect=RuntimeError('PRIVATE-TRANSPORT')):emit_request_event(self.request(),HttpResponse(),1)
 @override_settings(SECURITY_EVENT_LOGGING=True)
 def test_outer_context_emits_after_actual_response_with_valid_request_id(self):
  request=RequestFactory().get('/api/v1/health/live?token=PRIVATE-QUERY')
  with patch('operations.middleware.cache_headers',side_effect=lambda req,res:res),patch('operations.security_events.logger.info') as log:
   response=RequestContextMiddleware(lambda req:HttpResponse(status=401))(request)
  event=json.loads(log.call_args.args[0]);self.assertEqual(response.status_code,401);self.assertEqual(event['status'],401);self.assertEqual(event['request_id'],response['X-Request-ID']);self.assertNotIn('PRIVATE-QUERY',log.call_args.args[0])
 @override_settings(SECURITY_EVENT_LOGGING=False)
 def test_local_disabled_mode_emits_no_events(self):
  with patch('operations.middleware.cache_headers',side_effect=lambda req,res:res),patch('operations.security_events.logger.info') as log:
   RequestContextMiddleware(lambda req:HttpResponse())(RequestFactory().get('/'))
  log.assert_not_called()

 def test_configured_security_handler_writes_single_json_line_to_stdout(self):
  output=io.StringIO();configuration=copy.deepcopy(settings.LOGGING)
  configuration['handlers']['security_console']['stream']=output
  try:
   logging.config.dictConfig(configuration)
   emit_request_event(self.request(),HttpResponse(status=200),1)
   lines=output.getvalue().splitlines();self.assertEqual(len(lines),1)
   self.assertEqual(json.loads(lines[0])['event'],'earnalism.security.request')
   self.assertEqual(settings.LOGGING['handlers']['security_console']['stream'],'ext://sys.stdout')
  finally:logging.config.dictConfig(settings.LOGGING)

 @override_settings(SECURITY_EVENT_LOGGING=True)
 def test_successful_liveness_noise_excluded_without_losing_other_security_outcomes(self):
  for method,path,status,expected in [('get','/api/v1/health/live',200,False),('get','/api/v1/health/live',503,True),('post','/api/v1/health/live',200,True),('get','/en/privacy/',200,True),('get','/missing/',404,True)]:
   with self.subTest(method=method,path=path,status=status),patch('operations.middleware.cache_headers',side_effect=lambda req,res:res),patch('operations.security_events.logger.info') as log:
    response=RequestContextMiddleware(lambda req:HttpResponse(status=status))(getattr(RequestFactory(),method)(path))
    self.assertEqual(response.status_code,status);self.assertEqual(log.called,expected);self.assertIn('X-Request-ID',response)
