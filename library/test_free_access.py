"""Free rollout grants access, never publication, finance facts or wider rights."""
import io
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.test import TestCase,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from billing.models import Entitlement,Invoice,Order,Payment,Offer
from billing import checkout
from learning.models import Track
from learning import services as learning
from reader.models import DownloadLicense
from reader import download_services
from .models import Edition
from . import services

@override_settings(FREE_ACCESS_ENABLED=True)
class FreeAccessBoundaryTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.local=override_settings(LOCAL=True,MAISON_LOCAL_FIXTURES=True,MEDIA_ROOT=self.tmp.name,FEATURES={**settings.FEATURES,'offline_text_audio':True})
        self.local.enable();self.addCleanup(self.local.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.user=get_user_model().objects.create_user('original-free-member@example.test','Original-Free-Fixture-47',is_verified=True)
        self.staff=get_user_model().objects.create_superuser('original-free-staff@example.test','Original-Free-Fixture-47')
        self.edition=Edition.objects.get(pk='20000000-0000-4000-8000-000000000001')
        self.revision=services.clone_revision(self.edition.live_revision_id)
        self.revision.access_policy={'reader':'paid','audio':'deny','video':'deny'}
        self.revision.download_policy={'reader':True}
        self.revision.validation_evidence={'browser':{'sha256':self.revision.content_sha256,'status':'pass','scope':'local_test_only'}}
        self.revision.save();self.revision.rights.update(approved=True)
        self.revision.rights.filter(action='download').update(ends_at=timezone.now()+timedelta(hours=2))
        ready=services.transition_revision(self.staff,self.revision.id,'mark-ready',self.revision.version,self.revision.content_sha256,'Original free boundary fixture')
        services.transition_revision(self.staff,self.revision.id,'publish',ready['version'],self.revision.content_sha256,'Original free boundary fixture')
        self.revision.refresh_from_db();self.edition.refresh_from_db()

    def test_published_paid_format_is_free_without_financial_rows_and_all_whitelisted_rights_still_apply(self):
        self.assertEqual(services.authorize_revision(self.user,self.revision).pk,self.revision.pk)
        self.assertFalse(Entitlement.objects.filter(user=self.user).exists())
        self.assertFalse(Order.objects.exists());self.assertFalse(Payment.objects.exists());self.assertFalse(Invoice.objects.exists())
        with self.assertRaises(DomainError):services.authorize_revision(self.user,self.revision,territory='AE')
        self.revision.rights.filter(format='reader',action='read').update(approved=False)
        with self.assertRaises(DomainError) as denied:services.authorize_revision(self.user,self.revision)
        self.assertEqual(denied.exception.code,'rights_unavailable')

    def test_free_catalog_filter_and_labels_match_effective_access_without_expanding_rights(self):
        from .catalog_query import catalog_queryset,card_from_edition
        rows=list(catalog_queryset('en','IN',access='free'))
        own=next(row for row in rows if row.pk==self.edition.pk)
        self.assertEqual(card_from_edition(own)['access_label'],'free')
        self.assertFalse(catalog_queryset('en','IN',access='paid').exists())
        self.assertFalse(catalog_queryset('en','AE',access='free').exists())
        self.assertEqual(services.catalog_card(self.edition)['access_label'],'free')
        with override_settings(FREE_ACCESS_ENABLED=False):
            self.assertFalse(catalog_queryset('en','IN',access='free').filter(pk=self.edition.pk).exists())
            self.assertTrue(catalog_queryset('en','IN',access='paid').filter(pk=self.edition.pk).exists())

    def test_free_does_not_bypass_identity_verification_format_or_draft_boundaries(self):
        for user,code in [(AnonymousUser(),'authentication_required')]:
            with self.assertRaises(DomainError) as denied:services.authorize_revision(user,self.revision)
            self.assertEqual(denied.exception.code,code)
        self.user.is_verified=False
        with self.assertRaises(DomainError):services.authorize_revision(self.user,self.revision)
        self.user.is_verified=True
        draft=services.clone_revision(self.revision.pk);draft.rights.update(approved=True)
        with self.assertRaises(DomainError) as denied:services.authorize_revision(self.user,draft)
        self.assertEqual(denied.exception.code,'content_unavailable')
        with self.assertRaises(DomainError):services.authorize_revision(self.user,self.revision,format='video')

    def test_free_grant_expiry_uses_rights_not_an_old_paid_entitlement(self):
        expiry=timezone.now()+timedelta(minutes=10)
        Entitlement.objects.create(grant_key='original-previous-paid',user=self.user,source='purchase',scope='edition',edition=self.edition,formats=['reader'],valid_from=timezone.now(),valid_until=expiry)
        self.assertGreater(services.authorized_until(self.user,self.revision),expiry)
        with override_settings(FREE_ACCESS_ENABLED=False):
            self.assertEqual(services.authorized_until(self.user,self.revision),expiry)

    def test_offline_free_license_is_bounded_device_owned_and_rolls_back_without_financial_mutation(self):
        response=self.client.post('/api/v1/auth/login',{'email':self.user.email,'password':'Original-Free-Fixture-47'},content_type='application/json')
        self.assertEqual(response.status_code,200);device=response.json()['device_id']
        body={'edition_revision_id':str(self.revision.pk),'format':'reader','unit_ids':[str(self.revision.units.first().pk)],'device_id':device}
        response=self.client.post('/api/v1/me/downloads',body,content_type='application/json',HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(response.status_code,201,response.content)
        row=DownloadLicense.objects.get(pk=response.json()['license_id']);self.assertTrue(row.entitlement.grant_key.startswith('platform-free:'))
        self.assertLessEqual(row.expires_at,row.issued_at+timedelta(hours=24));self.assertLessEqual(row.expires_at,row.rights_record.ends_at)
        self.assertEqual(download_services._status(row),'active')
        with override_settings(FREE_ACCESS_ENABLED=False):
            with self.assertRaises(DomainError) as denied:services.authorize_revision(self.user,self.revision)
            self.assertEqual(denied.exception.code,'entitlement_required')
            self.assertEqual(download_services._status(row),'revoked')
        self.assertTrue(Entitlement.objects.filter(pk=row.entitlement_id).exists())
        self.assertFalse(Order.objects.exists());self.assertFalse(Payment.objects.exists());self.assertFalse(Invoice.objects.exists())

    def test_new_order_and_unattempted_provider_job_stop_before_provider_configuration_or_call(self):
        with patch('billing.checkout.qualified_mode') as mode,patch('billing.checkout.RazorpayClient') as provider:
            with self.assertRaises(DomainError) as denied:checkout.create_order(self.user,{'offer_id':str(uuid.uuid4())},uuid.uuid4(),'IN')
            self.assertEqual(denied.exception.code,'free_access_enabled');mode.assert_not_called();provider.assert_not_called()
        offer=Offer.objects.create(code='free-blocked-original',name='Original synthetic offer',price_minor=100,currency='INR',duration_seconds=3600,formats=['reader'],terms_version='original',approved=True,active=True,test_only=True,edition=self.edition)
        order=Order.objects.create(user=self.user,offer=offer,operation_id=uuid.uuid4(),request_sha256='a'*64,total_minor=100,currency='INR',test_only=True,provider='razorpay',status='creating',offer_snapshot={'territory':'IN'},expires_at=timezone.now()+timedelta(minutes=30))
        job=OutboxJob.objects.create(kind='checkout_reconcile',dedupe_key='original-free-blocked',actor=self.user,payload={'order_id':str(order.pk)},not_before=timezone.now())
        with patch('billing.checkout.qualified_mode') as mode,patch('billing.checkout.RazorpayClient') as provider:
            with self.assertRaises(DomainError):checkout.process_checkout(job)
            mode.assert_not_called();provider.assert_not_called()
        order.refresh_from_db();self.assertEqual(order.status,'creating');self.assertFalse(Payment.objects.exists())

    def test_uncertain_preexisting_provider_order_can_only_be_looked_up(self):
        offer=Offer.objects.create(code='original-previous-offer',name='Original synthetic historical offer',price_minor=100,currency='INR',duration_seconds=3600,formats=['reader'],terms_version='original',approved=True,active=True,test_only=True,edition=self.edition)
        order=Order.objects.create(user=self.user,offer=offer,operation_id=uuid.uuid4(),request_sha256='b'*64,total_minor=100,currency='INR',test_only=True,provider='razorpay',status='creating',offer_snapshot={'territory':'IN'},expires_at=timezone.now()+timedelta(minutes=30))
        job=OutboxJob.objects.create(kind='checkout_reconcile',dedupe_key='original-previous-attempt',actor=self.user,payload={'order_id':str(order.pk),'provider_create_attempted':True},not_before=timezone.now())
        with patch('billing.checkout.qualified_mode',return_value=('test','unused','unused')),patch('billing.checkout.RazorpayClient') as provider:
            provider.return_value.find_order.return_value={'id':'order_OriginalFreeFixture','receipt':str(order.pk),'amount':100,'currency':'INR'}
            self.assertEqual(checkout.process_checkout(job),{'order_id':str(order.pk)})
            provider.return_value.find_order.assert_called_once();provider.return_value.create_order.assert_not_called()
        order.refresh_from_db();self.assertEqual(order.provider_order_id,'order_OriginalFreeFixture');self.assertFalse(Payment.objects.exists())

    def test_learning_uses_free_revision_access_but_keeps_territory_and_published_boundaries(self):
        track=Track.objects.create(title='Original free learning fixture',locale='en',kind='learning',description='Local only',access='paid',edition=self.edition,published=True)
        self.assertEqual(learning.track_dto(self.user,track)['access'],'included')
        self.user.request_territory='AE'
        with self.assertRaises(DomainError) as denied:learning._track(self.user,track.pk)
        self.assertEqual(denied.exception.code,'region_unavailable')
        self.assertEqual(learning.list_tracks(self.user),[])
        self.user.request_territory='IN';track.published=False;track.save()
        with self.assertRaises(DomainError):learning._track(self.user,track.pk)
