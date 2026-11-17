import json
import uuid
from unittest.mock import patch
from django.conf import settings
from django.db import OperationalError, connection
from django.test import Client, TestCase, override_settings

class RuntimeBoundaryTests(TestCase):
    def test_real_postgresql_and_no_paid_features(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertIn(connection.pg_version // 10000, [17, 18])
        self.assertTrue(all(isinstance(v, bool) for v in settings.FEATURES.values()))
        self.assertFalse(any(settings.FEATURES[k] for k in ['audio','video','offline_text_audio','recurring_billing','google_oauth','phone_otp']))

    def test_liveness_request_id_security_headers_and_private_default(self):
        request_id = str(uuid.uuid4())
        result = self.client.get('/api/v1/health/live', HTTP_X_REQUEST_ID=request_id)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result['X-Request-ID'],request_id)
        self.assertEqual(result.json()['request_id'],request_id)
        self.assertEqual(result['Cache-Control'],'private, no-store')
        self.assertIn("frame-ancestors 'none'",result['Content-Security-Policy'])
        self.assertEqual(result['Referrer-Policy'],'strict-origin-when-cross-origin')

    def test_invalid_trace_id_is_replaced(self):
        result = self.client.get('/api/v1/health/live',HTTP_X_REQUEST_ID='untrusted-arbitrary-value')
        self.assertEqual(uuid.UUID(result['X-Request-ID']).version,4)

    def test_readiness_requires_secret_and_current_migrations(self):
        self.assertEqual(self.client.get('/api/v1/health/ready').status_code,403)
        result=self.client.get('/api/v1/health/ready',HTTP_X_HEALTH_PROBE=settings.HEALTH_PROBE_SECRET)
        self.assertEqual(result.status_code,200,result.content)
        with patch('operations.views.MigrationExecutor') as executor:
            executor.return_value.migration_plan.return_value=['pending']
            result=self.client.get('/api/v1/health/ready',HTTP_X_HEALTH_PROBE=settings.HEALTH_PROBE_SECRET)
            self.assertEqual(result.status_code,503)
            self.assertEqual(result.json()['code'],'schema_not_ready')

    def test_ready_dependency_failure_fails_closed(self):
        with patch('operations.views.MigrationExecutor',side_effect=OperationalError('unavailable')):
            result=self.client.get('/api/v1/health/ready',HTTP_X_HEALTH_PROBE=settings.HEALTH_PROBE_SECRET)
            self.assertEqual(result.status_code,503)
            self.assertTrue(result.json()['retryable'])

    @override_settings(LOCAL=False,ORIGIN_SHARED_SECRET='local-test-origin-key')
    def test_origin_boundary_and_health_exception(self):
        self.assertEqual(self.client.get('/api/v1/session').status_code,403)
        self.assertEqual(self.client.get('/api/v1/session',HTTP_X_MAISON_ORIGIN='local-test-origin-key').status_code,200)
        self.assertEqual(self.client.get('/api/v1/health/live').status_code,200)

    def test_csrf_is_enforced_on_authentication_mutation(self):
        result=Client(enforce_csrf_checks=True).post('/api/v1/auth/login',data=json.dumps({'email':'nobody@example.test','password':'unused'}),content_type='application/json')
        self.assertEqual(result.status_code,403)
        self.assertEqual(result['Content-Type'],'application/problem+json')
        self.assertEqual(result.json()['code'],'csrf_failed')
