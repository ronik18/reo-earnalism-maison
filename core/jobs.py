import time
import uuid
from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .models import OutboxJob
from .api import DomainError


def run_due_jobs(limit=25,max_seconds=45):
    started=time.monotonic();done=0;owner=str(uuid.uuid4())
    while done<limit and time.monotonic()-started<max_seconds:
        with transaction.atomic():
            now=timezone.now()
            job=OutboxJob.objects.select_for_update(skip_locked=True).filter(not_before__lte=now).filter(Q(status='pending')|Q(status='claimed',locked_until__lte=now)).order_by('not_before','created_at').first()
            if not job:break
            if job.attempts>=7:job.status='dead';job.save(update_fields=['status']);continue
            job.status='claimed';job.lease_owner=owner;job.locked_until=now+timedelta(seconds=120);job.attempts+=1;job.save()
        result=None;error=None
        try:
            if job.kind in ['email_action','privacy_export','privacy_delete','contact_support']:
                from accounts.services import process_outbox_job
                result=process_outbox_job(job,max_seconds=max(1,max_seconds-(time.monotonic()-started)))
            elif job.kind=='checkout_reconcile':
                from billing.checkout import process_checkout
                result=process_checkout(job)
            elif job.kind=='order_payment_reconcile':
                from billing.checkout import process_order_reconcile
                result=process_order_reconcile(job)
            elif job.kind=='payment_event_reconcile':
                from billing.checkout import process_payment_event
                result=process_payment_event(job)
            elif job.kind=='scheduled_publication':
                from operations.publication import process_scheduled_publication
                result=process_scheduled_publication(job)
            elif job.kind=='catalog_cache_purge':
                from operations.providers import purge_catalog_cache
                result=purge_catalog_cache(job.payload)
            elif job.kind in ['refund_review','refund_reconcile']:
                from billing.refunds import process_refund_job
                result=process_refund_job(job)
            elif job.kind=='subscription_reconcile':
                from billing.subscription_worker import process_subscription_job
                result=process_subscription_job(job)
            else:
                raise DomainError('handler_not_enabled','This job requires its qualified adapter.',409)
        except Exception as exc:error=exc.code if isinstance(exc,DomainError) else 'delivery_failed'
        with transaction.atomic():
            current=OutboxJob.objects.select_for_update().get(pk=job.pk)
            if current.status!='claimed' or current.lease_owner!=owner:continue
            current.locked_until=None;current.lease_owner=''
            if error:
                current.error_code=error
                if error in ['awaiting_resolution','provider_not_enabled','handler_not_enabled','scheduled_publication_invalid','scheduled_publication_held','refund_review_required','provider_not_qualified','provider_token_identity_missing']:current.status='blocked'
                elif current.attempts>=7:current.status='dead'
                else:
                    current.status='pending';delays=[30,120,600,1800,7200,21600];current.not_before=timezone.now()+timedelta(seconds=delays[min(current.attempts-1,5)])
            elif isinstance(result,dict) and result.get('awaiting_provider_confirmation') is True and (job.kind=='subscription_reconcile' or (job.kind in ['refund_reconcile','refund_review'] and job.payload.get('refund_id'))):
                # Authoritative provider pending state is not a delivery failure.
                # Keep the same durable obligation and mutation marker for GET-only
                # reconciliation; no extra worker or unbounded immediate retry.
                now=timezone.now();delay=result.get('confirmation_poll_seconds',300)
                delay=max(60,min(900,delay)) if type(delay) is int else 300
                due=now+timedelta(seconds=delay)
                if job.payload.get('action')=='subscription.cancel':
                    from django.utils.dateparse import parse_datetime
                    value=result.get('confirmation_not_before')
                    try:known_due=parse_datetime(value) if isinstance(value,str) and len(value)<=64 else None
                    except ValueError:known_due=None
                    if known_due is not None and timezone.is_aware(known_due) and known_due>due:due=known_due
                current.status='pending';current.completed_at=None;current.error_code='provider_confirmation_pending'
                current.not_before=due;current.attempts=0;current.result=result
            else:
                current.status='done';current.completed_at=timezone.now();current.error_code='';current.result=result or {}
            current.save()
        done+=1
    return {'processed':done}
