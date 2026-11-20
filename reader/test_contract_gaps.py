import uuid
from django.test import TestCase
from django.utils import timezone
from .tests import ReaderFixture,PASS,EN
from .models import SavedItem,Progress
from library.validation import validate_schema

class SyncContractAcceptanceTests(ReaderFixture,TestCase):
    def setUp(self):
        self.seed();self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':PASS,'password_purpose_consent':True,'password_purpose_version':'password-account-v1'},content_type='application/json')
    def test_invalid_sync_types_rejected_while_valid_operation_applies(self):
        device=self.client.get('/api/v1/session').json()['device_id'];stamp=timezone.now().isoformat().replace('+00:00','Z')
        operations=[{'operation_id':str(uuid.uuid4()),'kind':'saved.set','edition_id':EN,'saved':'false','occurred_at':stamp},
                    {'operation_id':str(uuid.uuid4()),'kind':'saved.set','edition_id':EN,'saved':True,'occurred_at':stamp}]
        response=self.client.post('/api/v1/me/sync',{'device_id':device,'operations':operations},content_type='application/json')
        self.assertEqual(response.status_code,200,response.content);validate_schema(response.json(),'SyncResponse')
        self.assertEqual([row['outcome'] for row in response.json()['results']],['rejected','applied']);self.assertEqual(response.json()['results'][0]['http_status'],422)
        self.assertEqual(SavedItem.objects.filter(user=self.user).count(),1)
    def test_malformed_progress_timestamp_rejected_without_mutation(self):
        for value in [True,'2026-99-99T00:00:00Z',{'time':'invalid'}]:
            data=self.data();data['occurred_at']=value
            response=self.client.put(f'/api/v1/me/progress/{EN}/reader',data,content_type='application/json',HTTP_IF_MATCH='"v0"')
            self.assertEqual(response.status_code,422,response.content)
        self.assertFalse(Progress.objects.exists())
