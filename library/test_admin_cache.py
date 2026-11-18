"""Admin invalidations stay atomic; all content below is disposable local test data."""
import hashlib
import io
import tempfile
from datetime import timedelta
from unittest.mock import patch
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase,RequestFactory,override_settings
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from operations.models import PublicCacheReference
from .admin import RightsAdmin,WorkAdmin,EditionAdmin
from .models import Edition,Rights,Work

class AdminCacheInvalidationTests(TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.override=override_settings(LOCAL=True,MAISON_LOCAL_FIXTURES=True,MEDIA_ROOT=self.directory.name);self.override.enable();self.addCleanup(self.override.disable)
        call_command('seed_local_pilot',stdout=io.StringIO())
        self.edition=Edition.objects.select_related('live_revision','work').get(pk='20000000-0000-4000-8000-000000000001')
        self.revision=self.edition.live_revision
        self.request=RequestFactory().post('/admin/');self.request.user=get_user_model().objects.create_superuser('cache-admin@example.test','Test-Cache-Admin-Strong47')
        self.rights=RightsAdmin(Rights,admin.site);self.works=WorkAdmin(Work,admin.site);self.editions=EditionAdmin(Edition,admin.site)
        url='https://maison.example/api/v1/home?locale=en&territory=IN'
        PublicCacheReference.objects.create(url=url,url_sha256=hashlib.sha256(url.encode()).hexdigest(),
            dependencies=['catalog:global','work:'+str(self.edition.work_id),'edition:'+str(self.edition.id),'revision:'+str(self.revision.id)],expires_at=timezone.now()+timedelta(minutes=5))

    def jobs(self):return OutboxJob.objects.filter(kind='catalog_cache_purge')

    def test_repeated_rights_edits_create_fresh_events_without_publishing_or_mutating_revision(self):
        grant=self.revision.rights.first();before=self.revision.version
        grant.approved=False;self.rights.save_model(self.request,grant,None,True)
        grant.approved=True;self.rights.save_model(self.request,grant,None,True)
        self.assertEqual(self.jobs().count(),2);self.assertEqual(len(set(self.jobs().values_list('dedupe_key',flat=True))),2)
        self.revision.refresh_from_db();self.edition.refresh_from_db()
        self.assertEqual(self.revision.version,before);self.assertEqual(self.revision.state,'live');self.assertEqual(self.edition.live_revision_id,self.revision.id)

    def test_single_and_bulk_rights_deletion_queue_once_per_revision(self):
        grant=self.revision.rights.first();identifier=grant.pk
        self.rights.delete_model(self.request,grant)
        self.assertFalse(Rights.objects.filter(pk=identifier).exists());self.assertEqual(self.jobs().count(),1)
        remaining=self.revision.rights.all();self.assertGreater(remaining.count(),0)
        self.rights.delete_queryset(self.request,remaining)
        self.assertFalse(self.revision.rights.exists());self.assertEqual(self.jobs().count(),2)

    def test_work_and_edition_metadata_changes_queue_but_noop_save_does_not(self):
        work=self.edition.work;work.title+=' revised';self.works.save_model(self.request,work,None,True)
        self.assertEqual(self.jobs().count(),1)
        self.works.save_model(self.request,work,None,True);self.assertEqual(self.jobs().count(),1)
        self.edition.slug+='-revised';self.editions.save_model(self.request,self.edition,None,True)
        self.assertEqual(self.jobs().count(),2)
        self.editions.save_model(self.request,self.edition,None,True);self.assertEqual(self.jobs().count(),2)

    def test_draft_metadata_and_rights_never_enqueue_public_invalidation(self):
        from .models import Revision
        work=Work.objects.create(slug='draft-cache-test',title='Draft test')
        edition=Edition.objects.create(work=work,slug='draft-cache-test-en',locale='en')
        revision=Revision.objects.create(edition=edition,title='Draft test')
        work.title+=' revised';self.works.save_model(self.request,work,None,True)
        edition.slug+='-revised';self.editions.save_model(self.request,edition,None,True)
        now=timezone.now();grant=Rights(revision=revision,format='reader',action='read',territories=['IN'],starts_at=now,ends_at=now+timedelta(days=1))
        self.rights.save_model(self.request,grant,None,False);self.rights.delete_model(self.request,grant)
        self.assertFalse(self.jobs().exists())

    def test_invalidation_failure_rolls_back_admin_mutation(self):
        grant=self.revision.rights.first();old=grant.approved;version=grant.version;grant.approved=not old
        with patch('library.admin.queue_catalog_purge',side_effect=DomainError('cache_failure','Test only',503)),self.assertRaises(DomainError):
            self.rights.save_model(self.request,grant,None,True)
        grant.refresh_from_db();self.assertEqual(grant.approved,old);self.assertEqual(grant.version,version);self.assertFalse(self.jobs().exists())

    def test_existing_permissions_are_not_expanded(self):
        user=get_user_model().objects.create_user('ordinary-cache@example.test','Test-Ordinary-Strong47');self.request.user=user
        self.assertFalse(self.rights.has_delete_permission(self.request,self.revision.rights.first()))
        self.assertFalse(self.works.has_change_permission(self.request,self.edition.work))
        self.assertIn('live_revision',self.editions.readonly_fields)
