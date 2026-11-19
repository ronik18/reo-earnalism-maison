"""Bounded Django email submission; SMTP cannot guarantee exactly-once delivery."""
from urllib.parse import quote,urlparse
from django.conf import settings
from django.core.mail import EmailMessage,get_connection
from django.db import transaction
from django.utils import timezone
from core.api import DomainError
from core.models import OutboxJob
from .models import EmailActionToken


def submit_message(job,subject,body,recipients,max_seconds=8,message_identifier=None):
    from .services import iso
    timeout=min(8,float(max_seconds),float(getattr(settings,'EMAIL_TIMEOUT',8) or 8))
    if timeout<=0:raise DomainError('email_time_budget','Email submission will retry.',503)
    domain=urlparse(settings.PUBLIC_BASE_URL).hostname or 'localhost'
    message_id=f'<maison-{message_identifier or job.id}@{domain}>'
    with transaction.atomic():
        current=OutboxJob.objects.select_for_update().get(pk=job.pk)
        if current.status!='claimed' or current.lease_owner!=job.lease_owner or (current.locked_until and current.locked_until<=timezone.now()):
            raise DomainError('job_lease_lost','Email submission was cancelled or reassigned.',409)
        payload=dict(current.payload)
        payload.update(email_message_id=message_id,email_outcome='submitting')
        payload.setdefault('email_first_attempt_at',iso(timezone.now()))
        current.payload=payload;current.save(update_fields=['payload'])
    try:
        connection=get_connection(fail_silently=False,timeout=timeout)
        message=EmailMessage(subject,body,settings.DEFAULT_FROM_EMAIL,recipients,connection=connection,headers={'Message-ID':message_id})
        accepted=message.send(fail_silently=False)
        if accepted!=1:raise DomainError('email_not_accepted','Email was not accepted; submission will retry.',503)
    except Exception as error:
        # A timeout after DATA can mean SMTP accepted the message. Retry the same ID/token,
        # never invent inbox delivery or silently lengthen a security token's lifetime.
        with transaction.atomic():
            current=OutboxJob.objects.select_for_update().get(pk=job.pk)
            if current.status=='claimed' and current.lease_owner==job.lease_owner:
                payload=dict(current.payload);payload['email_outcome']='unknown';current.payload=payload;current.save(update_fields=['payload'])
        if isinstance(error,DomainError):raise
        raise DomainError('email_submission_uncertain','Email submission outcome is unknown; the same message will retry.',503) from None
    return {'status':'submitted','smtp_submission_accepted':True,'delivery_confirmed':False,'message_id':message_id}


def deliver_action(job,max_seconds=8):
    from .services import _token_value,safe_return_path,iso
    action=EmailActionToken.objects.select_related('user').filter(pk=job.payload.get('action_id')).first()
    if not action or action.consumed_at or action.expires_at<=timezone.now():return {'status':'expired_without_send'}
    if not action.user.is_active or action.email_normalized!=action.user.email or action.purpose not in ['password_reset','verify_email','magic_signin']:
        return {'status':'invalidated_without_send'}
    if action.purpose=='magic_signin' and not getattr(settings,'FEATURES',{}).get('email_link',False):return {'status':'disabled_without_send'}
    locale=job.payload.get('locale','en')
    if locale not in ('en','bn'):raise DomainError('invalid_email_locale','Email locale is invalid.',422)
    base=settings.PUBLIC_BASE_URL.rstrip('/')
    route='/auth/sign-in/' if action.purpose=='magic_signin' else '/auth/reset/' if action.purpose=='password_reset' else '/auth/verify/'
    link=f'{base}{route}?token={quote(_token_value(action))}&return_to={quote(safe_return_path(action.return_path),safe="")}&locale={locale}'
    body=f'Use this link to confirm your requested account action: {link}\nThis link expires at {iso(action.expires_at)}.'
    return submit_message(job,'Earnalism account action',body,[action.email_normalized],max_seconds,message_identifier='action-'+str(action.id))
