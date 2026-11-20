import json
from functools import wraps
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.sessions.models import Session
from django.db import transaction,DatabaseError
from django.db.models import F
from django.http import FileResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from core.api import json_endpoint,json_body,api_response,DomainError,expected_version,operation_key,public_uuid
from core.models import OutboxJob
from core.services import apply_operation,audit
from .models import User,Preferences,Device,Consent,EmailActionToken
from . import services


def acknowledgement(request):
    return {'status':'accepted','request_id':str(getattr(request,'request_id',__import__('uuid').uuid4())),
            'message':'If the request is eligible, it will be processed shortly.'}


def profile_data(user):
    p,_=Preferences.objects.get_or_create(user=user)
    return {'member_id':str(user.public_id),'display_name':user.display_name,'email':user.email,
        'email_verified':user.is_verified,'locale':p.locale,'created_at':services.iso(user.date_joined),'version':user.version}


def require_fresh(request):
    raw=request.session.get('reauthenticated_at')
    try: stamp=__import__('datetime').datetime.fromisoformat(raw)
    except (TypeError,ValueError):raise DomainError('reauthentication_required','Confirm your identity before this action.',403)
    if timezone.is_naive(stamp) or not timedelta(0)<=timezone.now()-stamp<=timedelta(minutes=5):raise DomainError('reauthentication_required','Confirm your identity before this action.',403)


@ensure_csrf_cookie
@json_endpoint(('GET','DELETE'),auth=False)
def session_view(request):
    if request.method=='DELETE':
        if not request.user.is_authenticated:raise DomainError('authentication_required','Sign in to continue.',401)
        services.logout_member(request);return api_response({},204)
    return api_response(services.session_data(request))


@json_endpoint(('POST',),auth=False)
def register_view(request):
    d=json_body(request,{'email','password','display_name','locale','return_path'},['email','password','display_name'])
    services.register_member(**d);return api_response(acknowledgement(request),202)


@json_endpoint(('POST',),auth=False)
def login_view(request):
    d=json_body(request,{'email','password'},['email','password']);services.login_member(request,**d)
    return api_response(services.session_data(request))


@json_endpoint(('POST',),auth=False)
def request_action(request,purpose):
    if purpose not in {'email-links','email-verifications','password-resets'}:raise DomainError('not_found','Account action not found.',404)
    d=json_body(request,{'email','return_path','locale'},['email'])
    fn=services.request_magic_signin if purpose=='email-links' else services.request_password_reset if purpose=='password-resets' else services.request_email_verification
    fn(**d);return api_response(acknowledgement(request),202)


@json_endpoint(('POST',),auth=False)
def consume_action(request,purpose):
    if purpose not in {'email-links','email-verifications','password-resets'}:raise DomainError('not_found','Account action not found.',404)
    d=json_body(request,{'token','new_password'} if purpose=='password-resets' else {'token'},['token','new_password'] if purpose=='password-resets' else ['token'])
    if purpose=='email-links':
        services.confirm_magic_signin(request,d['token']);return api_response(services.session_data(request))
    if purpose=='password-resets':services.confirm_password_reset(**d);return api_response({},204)
    services.confirm_email_verification(d['token'],request=request);return api_response(services.session_data(request))


@json_endpoint(('GET','POST'),auth=False)
def provider_disabled(request,**kwargs):
    raise DomainError('feature_disabled','This provider is not configured and qualified.',409)


@json_endpoint(('GET','PATCH'))
def profile(request):
    if request.method=='GET':return api_response(profile_data(request.user),version=request.user.version)
    data=json_body(request,{'display_name','locale'});base=expected_version(request)
    if not data:raise DomainError('validation_error','Provide a profile change.',422)
    with transaction.atomic():
        user=User.objects.select_for_update().get(pk=request.user.pk)
        if user.version!=base:raise DomainError('version_conflict','Profile changed.',412,profile_data(user))
        if 'display_name' in data:
            if not isinstance(data['display_name'],str) or len(data['display_name'])>100:raise DomainError('validation_error','Invalid display name.',422)
            user.display_name=data['display_name']
        if 'locale' in data:
            if data['locale'] not in ['en','bn']:raise DomainError('validation_error','Invalid locale.',422)
            p,_=Preferences.objects.get_or_create(user=user);p.locale=data['locale'];p.version+=1;p.save()
        user.version+=1;user.save(update_fields=['display_name','version'])
    return api_response(profile_data(user),version=user.version)


@json_endpoint(('GET','PATCH'))
def preferences(request):
    if request.method=='GET':
        p,_=Preferences.objects.get_or_create(user=request.user);return api_response(services.preferences_data(p),version=p.version)
    data=json_body(request);base=expected_version(request)
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk)
        result=services.update_preferences(request.user,data,base)
    return api_response(result,version=result['version'])


@json_endpoint(('GET','PUT'))
def consents(request):
    def serialize(c):return {k:getattr(c,k) for k in ['necessary_notice_version','analytics_opt_in','marketing_email_opt_in','version']}|{'updated_at':services.iso(c.updated_at)}
    if request.method=='GET':
        c,_=Consent.objects.get_or_create(user=request.user);return api_response(serialize(c),version=c.version)
    data=json_body(request,{'necessary_notice_version','analytics_opt_in','marketing_email_opt_in'},['necessary_notice_version','analytics_opt_in','marketing_email_opt_in']);base=expected_version(request)
    if not isinstance(data['necessary_notice_version'],str) or not 1<=len(data['necessary_notice_version'])<=64 or any(type(data[k])!=bool for k in ['analytics_opt_in','marketing_email_opt_in']):raise DomainError('validation_error','Invalid consent value.',422)
    with transaction.atomic():
        User.objects.select_for_update().get(pk=request.user.pk);c,_=Consent.objects.get_or_create(user=request.user)
        if c.version!=base:raise DomainError('version_conflict','Consent choices changed.',412,serialize(c))
        for k,v in data.items():setattr(c,k,v)
        c.version+=1;c.save();audit(request.user,'consent.changed',c,{k:v for k,v in data.items()})
    return api_response(serialize(c),version=c.version)


@json_endpoint(('POST',))
def reauthenticate(request):
    data=json_body(request,{'password'},['password']);services.check_rate('reauth',str(request.user.public_id),5,600)
    if not request.user.check_password(data['password']):raise DomainError('invalid_credentials','Authentication could not be confirmed.',403)
    now=timezone.now();request.session['reauthenticated_at']=now.isoformat()
    return api_response({'reauthenticated_at':services.iso(now),'valid_until':services.iso(now+timedelta(minutes=5))})


@json_endpoint(('POST',))
def change_password(request):
    data=json_body(request,{'current_password','new_password'},['current_password','new_password'])
    if not request.user.check_password(data['current_password']):raise DomainError('invalid_credentials','Authentication could not be confirmed.',403)
    services._password(data['new_password'],request.user)
    with transaction.atomic():
        user=User.objects.select_for_update().get(pk=request.user.pk);user.set_password(data['new_password']);user.session_epoch+=1;user.version+=1;user.save()
        current=request.session.session_key;keys=list(user.devices.exclude(session_id=current).exclude(session_id=None).values_list('session_id',flat=True));Session.objects.filter(session_key__in=keys).delete()
        user.devices.exclude(session_id=current).filter(revoked_at__isnull=True).update(revoked_at=timezone.now(),version=F('version')+1)
        from reader.models import DownloadLicense
        DownloadLicense.objects.filter(user=user,revoked_at=None).exclude(device_id=request.session.get('device_id')).update(revoked_at=timezone.now())
        EmailActionToken.objects.filter(user=user,consumed_at__isnull=True).update(consumed_at=timezone.now())
        update_session_auth_hash(request,user);request.session['session_epoch']=user.session_epoch;request.session['reauthenticated_at']=timezone.now().isoformat()
        # Django rotated the current session key; keep its bound device relationship.
        Device.objects.filter(pk=request.session.get('device_id')).update(session_id=request.session.session_key)
    return api_response({},204)


@json_endpoint(('GET',))
def devices(request):
    from core.pagination import paginate_queryset
    result=paginate_queryset(request,Device.objects.filter(user=request.user),'devices',ordering='-last_seen_at')
    result['items']=[{'device_id':str(d.id),'label':d.label,'current':str(d.id)==request.session.get('device_id'),'created_at':services.iso(d.created_at),'last_seen_at':services.iso(d.last_seen_at),'revoked_at':services.iso(d.revoked_at)} for d in result['items']]
    return api_response(result)



@json_endpoint(('DELETE',))
def revoke_device(request,device_id):
    key=operation_key(request)
    def mutate():
        d=Device.objects.select_for_update().filter(pk=device_id,user=request.user).first()
        if not d:raise DomainError('not_found','Device not found.',404)
        if not d.revoked_at:
            if d.session_id:Session.objects.filter(session_key=d.session_id).delete()
            d.revoked_at=timezone.now();d.version+=1;d.save(update_fields=['revoked_at','version'])
            from reader.models import DownloadLicense
            DownloadLicense.objects.filter(device=d,revoked_at=None).update(revoked_at=d.revoked_at)
            audit(request.user,'device.revoked',d)
        return 204,{},d.version
    status,body=apply_operation(request.user,key,'device.revoke',{'device_id':device_id},mutate)
    if request.session.get('device_id')==str(device_id):services.logout_member(request)
    return api_response(body,status)


def privacy_cancellable(job):
    """Pure availability projection; mutation separately rechecks the active actor."""
    if job.kind not in ('privacy_export','privacy_delete') or job.status not in ('pending','blocked') or job.completed_at is not None:return False
    if job.kind=='privacy_delete' and (
        not isinstance(job.payload,dict) or 'delete_export_keys' in job.payload
        or isinstance(job.result,dict) and job.result.get('status') in ('anonymised','anonymised_financial_records_retained','already_removed')):return False
    return True


def privacy_data(job):
    retained=[]
    if job.kind=='privacy_delete':
        if job.status=='blocked' and job.error_code=='privacy_hold':retained=['legal_or_retention_hold']
        elif job.status=='blocked' and job.error_code=='awaiting_resolution':retained=['financial_obligations']
        elif job.status=='done':
            recorded=job.result.get('retained_categories')
            retained=[x for x in recorded if isinstance(x,str) and x in {'financial_obligations','account_security_records'}] if isinstance(recorded,list) else ['retention_details_unavailable']
    status={'pending':'queued','claimed':'processing','done':'completed','blocked':'awaiting_resolution','dead':'failed','cancelled':'cancelled'}[job.status]
    return {'privacy_request_id':str(job.id),'kind':job.kind.removeprefix('privacy_'),'status':status,
        'requested_at':services.iso(job.created_at),'completed_at':services.iso(job.completed_at),
        'download_expires_at':job.result.get('expires_at'),'retained_categories':retained,'can_cancel':privacy_cancellable(job)}


@json_endpoint(('GET','POST'))
def privacy_requests(request):
    if request.method=='GET':
        from core.pagination import keyset_page
        rows=OutboxJob.objects.filter(actor=request.user,kind__in=['privacy_export','privacy_delete'])
        return api_response(keyset_page(rows,request.GET,f'privacy:{request.user.pk}','created_at',privacy_data))
    require_fresh(request);d=json_body(request,{'kind','confirm'},['kind','confirm'])
    if d['kind'] not in ['export','delete'] or d['confirm'] is not True:raise DomainError('validation_error','Explicit confirmation is required.',422)
    key=operation_key(request)
    def mutate():
        job=OutboxJob.objects.create(kind='privacy_'+d['kind'],actor=request.user,dedupe_key=f'privacy:{request.user.public_id}:{key}',payload={'session_epoch':request.user.session_epoch},not_before=timezone.now());audit(request.user,'privacy.requested',job,{'kind':d['kind']})
        return 202,privacy_data(job),1
    status,body=apply_operation(request.user,key,'privacy.create',d,mutate);return api_response(body,status)


@json_endpoint(('GET',))
def privacy_request(request,privacy_request_id):
    job=OutboxJob.objects.filter(id=privacy_request_id,actor=request.user,kind__in=['privacy_export','privacy_delete']).first()
    if not job:raise DomainError('not_found','Request not found.',404)
    return api_response(privacy_data(job))


@json_endpoint(('POST',))
def privacy_cancel(request,privacy_request_id):
    require_fresh(request);key=operation_key(request)
    def mutate():
        job=OutboxJob.objects.select_for_update().filter(id=privacy_request_id,actor=request.user,kind__in=['privacy_export','privacy_delete']).first()
        if not job:raise DomainError('not_found','Request not found.',404)
        if job.status in ('pending','blocked'):
            # A blocked request may be withdrawn, but never abandon cleanup after
            # account erasure has committed or reverse a completed export.
            if not privacy_cancellable(job) or not User.objects.filter(pk=request.user.pk,is_active=True).exists():
                raise DomainError('already_processing','This request can no longer be cancelled.',409)
            job.status='cancelled';job.lease_owner='';job.locked_until=None
            job.save(update_fields=['status','lease_owner','locked_until'])
            # Preserve holds, obligations and prepared-export keys/expiry. The
            # existing retention worker remains responsible for eligible cleanup.
            audit(request.user,'privacy.cancelled',job)
        elif job.status!='cancelled':raise DomainError('already_processing','This request can no longer be cancelled.',409)
        return 200,privacy_data(job),1
    status,body=apply_operation(request.user,key,'privacy.cancel',{'id':privacy_request_id},mutate);return api_response(body,status)


@json_endpoint(('POST',))
def privacy_download(request,privacy_request_id):
    require_fresh(request)
    job=OutboxJob.objects.filter(id=privacy_request_id,actor=request.user,kind='privacy_export',status='done').first()
    if not job:raise DomainError('not_found','A completed export was not found.',404)
    if not job.result.get('expires_at') or timezone.now()>=__import__('datetime').datetime.fromisoformat(job.result['expires_at'].replace('Z','+00:00')):raise DomainError('export_expired','Request a new export.',410)
    from library import storage
    artifact_expiry=__import__('datetime').datetime.fromisoformat(job.result['expires_at'].replace('Z','+00:00'))
    expiry=min(timezone.now()+timedelta(seconds=120),artifact_expiry)
    seconds=int((expiry-timezone.now()).total_seconds())
    if seconds<1:raise DomainError('export_expired','Request a new export.',410)
    if job.result.get('storage_key'):
        # Upload completion already verified immutable bytes; do not redownload the export to mint a URL.
        if storage.is_r2():url=storage.private_url(job.result['storage_key'],seconds,'application/json')
        else:
            job.result['delivery_until']=services.iso(expiry);job.save(update_fields=['result'])
            url=request.build_absolute_uri(f'/api/v1/me/privacy/requests/{job.id}/file')
        return api_response({'url':url,'expires_at':services.iso(expiry),'sha256':job.result['sha256'],'bytes':job.result['bytes'],'content_type':'application/json'})
    # Retained development exports are usable only in local mode; no production disk fallback.
    if not settings.LOCAL:raise DomainError('export_unavailable','Request a new export.',410)
    path=Path(settings.BASE_DIR)/'.local'/'privacy'/job.result['artifact_name']
    if not path.exists():raise DomainError('export_unavailable','Request a new export.',410)
    job.result['delivery_until']=services.iso(expiry);job.save(update_fields=['result'])
    return api_response({'url':request.build_absolute_uri(f'/api/v1/me/privacy/requests/{job.id}/file'),'expires_at':services.iso(expiry),'sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'content_type':'application/json'})


@json_endpoint(('GET',))
def privacy_file(request,privacy_request_id):
    require_fresh(request)
    if not settings.LOCAL:raise DomainError('export_unavailable','Request a private download grant.',410)
    job=OutboxJob.objects.filter(id=privacy_request_id,actor=request.user,kind='privacy_export',status='done').first()
    if not job or not job.result.get('delivery_until') or timezone.now()>=__import__('datetime').datetime.fromisoformat(job.result['delivery_until'].replace('Z','+00:00')):raise DomainError('export_expired','Request a new download.',410)
    if job.result.get('storage_key'):
        from library import storage
        storage.verify_private(job.result['storage_key'],job.result['bytes'],job.result['sha256'],'application/json')
        path=storage._local_path(job.result['storage_key'])
    else:path=Path(settings.BASE_DIR)/'.local'/'privacy'/job.result['artifact_name']
    if not path.exists():raise DomainError('export_unavailable','Request a new export.',410)
    response=FileResponse(path.open('rb'),as_attachment=True,filename='earnalism-personal-data.json',content_type='application/json');response['Cache-Control']='private, no-store';return response


@json_endpoint(('POST',),auth=False)
def contact(request):
    if not settings.LOCAL and not getattr(settings,'SUPPORT_EMAIL',''):
        raise DomainError('support_not_configured','The support form is unavailable. Contact sales@reoenterprise.org directly; no message was collected.',503)
    d=json_body(request,{'email','locale','category','message','order_id'},['email','locale','category','message'])
    services._email(d['email']);services.check_rate('contact',d['email'],5,3600)
    if d['locale'] not in ['en','bn'] or d['category'] not in ['account','billing','content','accessibility','privacy','other'] or not isinstance(d['message'],str) or not 10<=len(d['message'])<=5000:raise DomainError('validation_error','Invalid support message.',422)
    OutboxJob.objects.create(kind='contact_support',dedupe_key=f'contact:{__import__("uuid").uuid4()}',actor=request.user if request.user.is_authenticated else None,payload=d,not_before=timezone.now())
    return api_response(acknowledgement(request),202)


@json_endpoint(('GET','POST'))
def mfa_totp(request):
    from . import mfa
    if request.method=='GET':return api_response(mfa.status(request))
    json_body(request,set());return api_response(mfa.enroll(request),201)


@json_endpoint(('POST',))
def mfa_confirm(request):
    from . import mfa
    data=json_body(request,{'token'},['token']);return api_response(mfa.confirm(request,data['token']))


@json_endpoint(('POST',))
def mfa_verify(request):
    from . import mfa
    data=json_body(request,{'token'},['token']);return api_response(mfa.verify(request,data['token']))


@json_endpoint(('POST',))
def mfa_recover(request):
    from . import mfa
    data=json_body(request,{'code'},['code']);return api_response(mfa.recover(request,data['code']))


def _oauth_response_headers(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        response=view(*args,**kwargs);response['Referrer-Policy']='no-referrer';return response
    return wrapped


@_oauth_response_headers
@json_endpoint(('GET',),auth=False)
def google_start(request):
    from .google import start,oauth_problem
    try:return start(request)
    except DomainError as error:return oauth_problem(error,request)
    except DatabaseError:return oauth_problem(DomainError('google_provider_unavailable','Google sign-in is temporarily unavailable.',503),request)


@_oauth_response_headers
@json_endpoint(('GET',),auth=False)
def google_callback(request):
    from .google import callback,oauth_problem
    try:return callback(request)
    except DomainError as error:return oauth_problem(error,request)
    except DatabaseError:return oauth_problem(DomainError('google_provider_unavailable','Google sign-in is temporarily unavailable.',503),request)
