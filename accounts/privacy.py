"""Owned personal-data exports use streamed JSON and private object storage."""
import hashlib
import json
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q,F
from django.contrib.sessions.models import Session
from django.utils import timezone
from core.api import DomainError
from core.models import OperationReceipt,OutboxJob
from core.services import audit
from .models import User,Preferences,Consent,EmailActionToken,Device,MFARecoveryCode


def _iso(value):return value.isoformat().replace('+00:00','Z')


def _write_export(user,file,deadline):
    from reader.models import Progress,Completion,Annotation,SavedItem,PersonalList,PersonalListItem,DownloadLicense
    from learning.models import LessonCompletion,QuizAttempt
    from billing.models import Order,Entitlement,Invoice,Refund
    from .services import preferences_data
    encoder=DjangoJSONEncoder(ensure_ascii=False,separators=(',',':'))
    digest=hashlib.sha256();size=0
    def raw(value):
        nonlocal size
        if time.monotonic()>=deadline:raise DomainError('export_time_budget','Export exceeded its bounded processing window.',503)
        data=value.encode('utf-8');file.write(data);digest.update(data);size+=len(data)
    def value(value):
        for part in encoder.iterencode(value):raw(part)
    alias=getattr(settings,'PRIVACY_EXPORT_DB_ALIAS','default')
    pref=Preferences.objects.using(alias).filter(user=user).first();consent=Consent.objects.using(alias).filter(user=user).values('necessary_notice_version','analytics_opt_in','marketing_email_opt_in','updated_at').first()
    fields={'schema_version':1,'profile':{'member_id':str(user.public_id),'email':user.email,'display_name':user.display_name,'first_name':user.first_name,'last_name':user.last_name,'created_at':user.date_joined},'preferences':preferences_data(pref) if pref else None,'consents':consent}
    arrays={
        'progress':Progress.objects.filter(user=user).values('edition_id','revision_id','format','location','fraction_complete','version','updated_at'),
        'completion':Completion.objects.filter(user=user).values('edition_id','revision_id','format','is_complete','completed_at','version','updated_at'),
        'annotations':Annotation.objects.filter(user=user,deleted_at=None).values('id','revision_id','kind','range','color','note_text','quoted_text','created_at','updated_at'),
        'saved_items':SavedItem.objects.filter(user=user).values('edition_id','created_at'),
        'lists':PersonalList.objects.filter(user=user).values('id','name','created_at','updated_at'),
        'list_items':PersonalListItem.objects.filter(personal_list__user=user).values('personal_list_id','edition_id','sort_order','added_at'),
        'downloads':DownloadLicense.objects.filter(user=user).values('id','device_id','revision_id','format','unit_ids','issued_at','expires_at','revoked_at'),
        'learning_completion':LessonCompletion.objects.filter(user=user).values('lesson_id','completed_at'),
        'quiz_attempts':QuizAttempt.objects.filter(user=user).values('id','quiz_id','quiz_version','status','answers','score','result','started_at','submitted_at'),
        'orders':Order.objects.filter(user=user).values('id','total_minor','currency','status','fulfillment_status','created_at','paid_at'),
        'entitlements':Entitlement.objects.filter(user=user).values('id','source','scope','edition_id','track_id','formats','valid_from','valid_until','status','revoked_at'),
        'invoices':Invoice.objects.filter(Q(order__user=user)|Q(subscription__user=user)).values('id','order_id','subscription_id','number','amount_minor','currency','line_snapshot','period_start','period_end','revision','issued_at'),
        'refunds':Refund.objects.filter(payment__order__user=user).values('id','amount_minor','proposed_amount_minor','currency','status','created_at','processed_at'),
    }
    from django.apps import apps
    if apps.is_installed('allauth.account'):
        from allauth.account.models import EmailAddress
        from allauth.socialaccount.models import SocialAccount
        arrays['email_addresses']=EmailAddress.objects.filter(user=user).values('email','verified','primary')
        arrays['linked_identities']=SocialAccount.objects.filter(user=user).values('provider','uid','date_joined')
    raw('{');first=True
    for name,item in fields.items():
        if not first:raw(',')
        first=False;value(name);raw(':');value(item)
    for name,rows in arrays.items():
        raw(',');value(name);raw(':[');first=True
        for row in rows.using(alias).iterator(chunk_size=200):
            if not first:raw(',')
            first=False;value(row)
        raw(']')
    raw('}');file.flush();file.seek(0)
    return size,digest.hexdigest()


def create_export(job,max_seconds=45):
    from library import storage
    deadline=time.monotonic()+max_seconds
    user=User.objects.using(getattr(settings,'PRIVACY_EXPORT_DB_ALIAS','default')).filter(pk=job.actor_id,is_active=True).first()
    if not user:raise DomainError('account_unavailable','This account is unavailable.',409)
    if job.payload.get('session_epoch',user.session_epoch)!=user.session_epoch:
        raise DomainError('account_changed','A fresh privacy export is required.',409)
    prepared=job.payload.get('prepared_export')
    if prepared and storage.private_exists(prepared['storage_key']):
        storage.verify_private(prepared['storage_key'],prepared['bytes'],prepared['sha256'],'application/json',max_seconds=max_seconds)
        return prepared
    # Scratch file is discarded after upload; immutable metadata is persisted before the provider call.
    with tempfile.TemporaryFile('w+b') as file:
        size,sha=_write_export(user,file,deadline)
        key=f'exports/{user.public_id}/{job.id}-{sha}.json'
        result={'storage_key':key,'sha256':sha,'bytes':size,'content_type':'application/json',
            'expires_at':_iso(timezone.now()+timedelta(seconds=getattr(settings,'PRIVACY_EXPORT_TTL_SECONDS',604800)))}
        with transaction.atomic():
            current_job=OutboxJob.objects.select_for_update().get(pk=job.pk)
            if current_job.status!='claimed' or current_job.lease_owner!=job.lease_owner:raise DomainError('job_lease_lost','The export was cancelled or reassigned.',409)
            payload=dict(current_job.payload);payload['prepared_export']=result;payload['export_keys']=sorted(set(payload.get('export_keys',[]))|{key})
            current_job.payload=payload;current_job.save(update_fields=['payload'])
        if hasattr(storage,'put_private_file'):storage.put_private_file(key,file,'application/json',size,sha,max_seconds=max(1,deadline-time.monotonic()))
        else:
            if size>4*1024*1024:raise DomainError('export_adapter_unavailable','Streaming export storage must be configured.',503)
            storage.put_private(key,file.read(),'application/json')
    current=User.objects.filter(pk=user.pk,is_active=True,session_epoch=user.session_epoch).exists()
    if not current:
        storage.delete_private(key)
        raise DomainError('account_changed','The account changed while preparing this export.',409)
    return result


def delete_account(job):
    from billing.models import Order,LegacyLiability,Refund
    from reader.services import delete_personal_data
    from reader.models import DownloadLicense
    from learning.models import LessonCompletion,QuizAttempt
    from library import storage
    with transaction.atomic():
        user=User.objects.select_for_update().filter(pk=job.actor_id).first()
        if not user:return {'status':'already_removed'}
        if (Order.objects.filter(user=user).filter(Q(status__in=['creating','created','pending'])|Q(fulfillment_status__in=['refund_pending','review'])).exists()
            or LegacyLiability.objects.filter(user=user,status='unresolved').exists()
            or Refund.objects.filter(payment__order__user=user,status__in=['requested','approved','submitted','pending']).exists()):
            raise DomainError('awaiting_resolution','Outstanding payments or refunds require resolution before deletion.',409)
        # An already-claimed export completes/cancels before deletion; don't race an upload of erased data.
        if OutboxJob.objects.filter(actor=user,kind='privacy_export',status='claimed',locked_until__gt=timezone.now()).exists():
            raise DomainError('export_in_progress','The current export is finishing; deletion will retry.',503)
        current=OutboxJob.objects.select_for_update().get(pk=job.pk)
        keys=set(current.payload.get('delete_export_keys',[]))
        for artifact in OutboxJob.objects.filter(actor=user,kind='privacy_export').values('payload','result'):
            if artifact['result'].get('storage_key'):keys.add(artifact['result']['storage_key'])
            keys.update(artifact['payload'].get('export_keys',[]))
            if artifact['payload'].get('prepared_export',{}).get('storage_key'):keys.add(artifact['payload']['prepared_export']['storage_key'])
        current.payload={'delete_export_keys':sorted(keys)};current.save(update_fields=['payload'])
        now=timezone.now()
        delete_personal_data(user);LessonCompletion.objects.filter(user=user).delete();QuizAttempt.objects.filter(user=user).delete()
        DownloadLicense.objects.filter(user=user,revoked_at=None).update(revoked_at=now)
        Session.objects.filter(session_key__in=user.devices.exclude(session_id=None).values_list('session_id',flat=True)).delete()
        user.devices.filter(revoked_at=None).update(revoked_at=now,version=F('version')+1)
        user.email=f'deleted-{user.public_id}@invalid.local';user.display_name='';user.first_name='';user.last_name='';user.is_active=False;user.is_verified=False;user.session_epoch+=1;user.version+=1;user.set_unusable_password();user.save()
        from django.apps import apps
        if apps.is_installed('allauth.account'):
            from allauth.account.models import EmailAddress
            from allauth.socialaccount.models import SocialAccount
            SocialAccount.objects.filter(user=user).delete();EmailAddress.objects.filter(user=user).delete()
        Preferences.objects.filter(user=user).delete();Consent.objects.filter(user=user).delete();EmailActionToken.objects.filter(user=user).delete();MFARecoveryCode.objects.filter(user=user).delete()
        from django.apps import apps
        if apps.is_installed('django_otp.plugins.otp_totp'):
            from django_otp.plugins.otp_totp.models import TOTPDevice
            TOTPDevice.objects.filter(user=user).delete()
        personal=Q(kind__startswith='annotation.')|Q(kind__startswith='list.')|Q(kind__startswith='progress.')|Q(kind__startswith='completion.')|Q(kind__startswith='saved.')
        OperationReceipt.objects.filter(actor=user).filter(personal).delete()
        OutboxJob.objects.filter(actor=user,kind__in=['email_action','privacy_export','contact_support']).update(status='cancelled',payload={},result={},lease_owner='',locked_until=None)
        audit(user,'privacy.account_anonymised',user)
    # Exact export keys survive provider failures in the deletion job payload; retries are idempotent.
    for key in keys:storage.delete_private(key)
    return {'status':'anonymised_financial_records_retained'}


def cleanup_expired_exports(limit=20,max_seconds=20):
    """Revoke delivery before deletion; persist exact retry keys before storage I/O."""
    from library import storage
    if type(limit)!=int or not 1<=limit<=100:raise ValueError('limit must be1–100')
    if not 0<max_seconds<=60:raise ValueError('max_seconds must be positive and<=60')
    deadline=time.monotonic()+max_seconds;now=timezone.now();stamp=_iso(now)
    candidates=OutboxJob.objects.filter(kind='privacy_export').exclude(status='claimed').filter(
        Q(payload__export_cleanup_pending=True)|Q(result__expires_at__lte=stamp)|Q(payload__prepared_export__expires_at__lte=stamp)
    ).filter(Q(payload__export_cleanup_completed__isnull=True)|Q(payload__export_cleanup_completed=False)).order_by('created_at','id').values_list('id',flat=True)[:limit]
    identifiers=list(candidates);cleaned=failed=0
    for identifier in identifiers:
        if time.monotonic()>=deadline:break
        with transaction.atomic():
            job=OutboxJob.objects.select_for_update().get(pk=identifier)
            if job.status=='claimed' or job.payload.get('export_cleanup_completed'):continue
            payload=dict(job.payload);result=dict(job.result)
            keys=set(payload.get('export_cleanup_keys',[]))|set(payload.get('export_keys',[]))
            for source in [result,payload.get('prepared_export',{})]:
                if source.get('storage_key'):keys.add(source['storage_key'])
            payload.update(export_cleanup_pending=True,export_cleanup_keys=sorted(keys))
            result['delivery_until']=stamp
            if job.status!='done':job.status='cancelled'
            job.payload=payload;job.result=result;job.save(update_fields=['status','payload','result'])
        # Never clear the durable keys on partial/unknown provider outcome.
        try:
            for key in sorted(keys):
                if time.monotonic()>=deadline:raise DomainError('cleanup_time_budget','Cleanup will retry.',503)
                storage.delete_private(key)
        except Exception:
            failed+=1;continue
        with transaction.atomic():
            job=OutboxJob.objects.select_for_update().get(pk=identifier)
            payload=dict(job.payload)
            payload.update(export_cleanup_pending=False,export_cleanup_completed=True)
            for field in ['export_cleanup_keys','export_keys','prepared_export']:payload.pop(field,None)
            job.payload=payload;job.save(update_fields=['payload'])
        cleaned+=1
    return {'cleaned':cleaned,'failed':failed}
