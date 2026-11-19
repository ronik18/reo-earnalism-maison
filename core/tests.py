"""Wire-level response framing for no-content account/device actions."""
from django.test import SimpleTestCase
from core.api import api_response

class ResponseFramingTests(SimpleTestCase):
 def test_no_content_action_emits_no_json_bytes_but_preserves_security_and_version(self):
  response=api_response({'ignored':'a completed mutation has no response representation'},204,version=7)
  self.assertEqual(b''.join(response),b'')
  self.assertEqual(response.status_code,204)
  self.assertNotIn('Content-Type',response)
  self.assertEqual(response['ETag'],'"v7"')
  self.assertEqual(response['Cache-Control'],'private, no-store')
 def test_regular_json_response_still_carries_representation(self):
  response=api_response({'status':'ok'})
  self.assertEqual(response.content,b'{"status": "ok"}')
  self.assertEqual(response['Content-Type'],'application/json')
