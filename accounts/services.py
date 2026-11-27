import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote
from django.conf import settings
from django.contrib.auth import authenticate,login,logout,update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction,IntegrityError
from django.db.models import F,Q
from django.middleware.csrf import get_token,rotate_token
from django.utils import timezone
from core.api import DomainError,public_uuid
from core.models import OutboxJob
from core.services import audit
from .models import User,Preferences,Device,EmailActionToken,Consent,RateLimitBucket,normalize_email_address
from .password_consent import record_password_purpose_consent

TTL={'magic_signin':600,'password_reset':1800,'verify_email':86400}


def iso(value): return value.isoformat().replace('+00:00','Z') if value else None

def _key(): return getattr(settings,'EMAIL_ACTION_HASH_KEY',settings.SECRET_KEY)

def _digest(value):return hmac.new(_key().encode(),value.encode(),hashlib.sha256).hexdigest()

def safe_return_path(path):
    from urllib.parse import unquote
    value=unquote(str(path or '/'))
    if not value.startswith('/') or value.startswith('//') or '\\' in value or any(ord(x)<32 for x in value) or len(value)>1024:
        raise DomainError('invalid_return_path','Use a local content destination.',422)
    if value.startswith('/api/') or value.startswith('/auth/'):
        raise DomainError('invalid_return_path','Choose a content destination.',422)
    return value


def _email(email):
    email=normalize_email_address(email)
    try: validate_email(email)
    except ValidationError:raise DomainError('validation_error','Enter a valid email address.',422)
    return email


def _password(password,user=None):
    if not isinstance(password,str) or not 12<=len(password)<=128:
        raise DomainError('weak_password','Use a password between 12 and 128 characters.',422)
    try:validate_password(password,user)
    except ValidationError:raise DomainError('weak_password','Choose a stronger password.',422)


def check_rate(purpose,identifier,limit=10,seconds=600):
    current=time.time();stamp=int(current)//seconds;now=timezone.now()
    with transaction.atomic():
        row,_=RateLimitBucket.objects.get_or_create(key_hash=_digest(identifier),purpose=purpose,window=stamp,
            defaults={'expires_at':now+timedelta(seconds=seconds*2)})
        RateLimitBucket.objects.filter(pk=row.pk).update(count=F('count')+1)
        row.refresh_from_db()
        count=row.count
    metadata={'limit':limit,'remaining':max(0,limit-count),'reset':max(1,int((stamp+1)*seconds-current+0.999))}
    if count>limit:
        error=DomainError('rate_limited','Please wait before trying again.',429);error.rate_limit=metadata;raise error
    return metadata


def cleanup_rate_buckets(limit=1000):
    """Maintenance removes only expired windows in a bounded primary-key batch."""
    if type(limit)!=int or not 1<=limit<=10000:raise ValueError('limit must be1–10000')
    identifiers=list(RateLimitBucket.objects.filter(expires_at__lte=timezone.now()).order_by('pk').values_list('pk',flat=True)[:limit])
    count,_=RateLimitBucket.objects.filter(pk__in=identifiers,expires_at__lte=timezone.now()).delete()
    return {'deleted':count}


def _token_value(action):
    # The random UUID is signed with a private domain-separated MAC. Only its keyed
    # digest is persisted; a retry reconstructs the same value without extending TTL.
    return signing.Signer(key=_key(),salt='maison.email-action.v1').sign(str(action.id))


def _create_action(user,purpose,return_path='/',locale='en'):
    now=timezone.now()
    EmailActionToken.objects.filter(user=user,purpose=purpose,consumed_at__isnull=True).update(consumed_at=now)
    action=EmailActionToken(id=uuid.uuid4(),user=user,email_normalized=user.email,purpose=purpose,
        return_path=safe_return_path(return_path),expires_at=now+timedelta(seconds=TTL[purpose]))
    action.token_sha256=_digest(_token_value(action));action.save()
    OutboxJob.objects.create(kind='email_action',dedupe_key=f'email-action:{action.id}',actor=user,
        payload={'action_id':str(action.id),'locale':locale},not_before=now)
    return action


def register_member(email,password,display_name='',locale='en',return_path='/',*,password_consent=None,_return_created_user=False,account_capacity=None,account_notice_version=None,account_terms_consent=None,_guardian_account=False,territory=None):
    from .enrollment import adult_declaration,record_adult
    declaration=None if _guardian_account else adult_declaration({'account_capacity':account_capacity,'account_notice_version':account_notice_version,'account_terms_consent':account_terms_consent},territory)
    email=_email(email);_password(password);check_rate('registration',email,3,3600)
    if locale not in ('en','bn') or not isinstance(display_name,str) or len(display_name)>100:
        raise DomainError('validation_error','Invalid profile fields.',422)
    with transaction.atomic():
        user=User.objects.filter(email=email).first()
        if user:
            if _return_created_user:return None
            return {'status':'delivery_pending'}
        from django.apps import apps
        if apps.is_installed('allauth.account'):
            from allauth.account.models import EmailAddress
            if EmailAddress.objects.filter(email__iexact=email,verified=True).exists():
                if _return_created_user:return None
                return {'status':'delivery_pending'}
        try:
            with transaction.atomic():user=User.objects.create_user(email,password,display_name=display_name)
        except IntegrityError:
            if _return_created_user:return None
            return {'status':'delivery_pending'}
        Preferences.objects.create(user=user,locale=locale);Consent.objects.create(user=user,necessary_notice_version=settings.PRIVACY_NOTICE_VERSION)
        _create_action(user,'verify_email',return_path,locale);audit(user,'account.registered',user)
        record_password_purpose_consent(user,'registration',password_consent)
        record_adult(user,declaration,'registration')
    return user if _return_created_user else {'status':'delivery_pending'}


def request_email_verification(email,return_path='/',locale='en'):
    if locale not in ('en','bn'):raise DomainError('validation_error','Invalid locale.',422)
    email=_email(email);check_rate('verify_email',email,3,900)
    with transaction.atomic():
        user=User.objects.select_for_update().filter(email=email,is_active=True,is_verified=False).first()
        if user:_create_action(user,'verify_email',return_path,locale)
    return {'status':'delivery_pending'}


def request_password_reset(email,return_path='/',locale='en'):
    if locale not in ('en','bn'):raise DomainError('validation_error','Invalid locale.',422)
    email=_email(email);check_rate('password_reset',email,3,900)
    with transaction.atomic():
        user=User.objects.select_for_update().filter(email=email,is_active=True).first()
        if user:_create_action(user,'password_reset',return_path,locale)
    return {'status':'delivery_pending'}


def request_magic_signin(email,return_path='/',locale='en'):
    if not getattr(settings,'FEATURES',{}).get('email_link',False):raise DomainError('feature_disabled','Email sign-in is not enabled.',409)
    if locale not in ('en','bn'):raise DomainError('validation_error','Invalid locale.',422)
    email=_email(email);return_path=safe_return_path(return_path);check_rate('magic_signin',email,3,900)
    with transaction.atomic():
        user=User.objects.select_for_update().filter(email=email,is_active=True).first()
        if user:_create_action(user,'magic_signin',return_path,locale)
    return {'status':'delivery_pending'}


def confirm_magic_signin(request,token):
    """Explicit CSRF-protected POST establishes mailbox ownership, never a link GET."""
    if not getattr(settings,'FEATURES',{}).get('email_link',False):raise DomainError('feature_disabled','Email sign-in is not enabled.',409)
    with transaction.atomic():
        action=consume_action(token,'magic_signin')
        user=User.objects.select_for_update().get(pk=action.user_id)
        if not user.is_verified:
            user.is_verified=True;user.version+=1;user.save(update_fields=['is_verified','version'])
        from .email_identity import ensure_email_address
        ensure_email_address(user,verified=True)
        action.consumed_at=timezone.now();action.save(update_fields=['consumed_at'])
        login(request,user,backend='django.contrib.auth.backends.ModelBackend')
        audit(user,'account.magic_signin',user)
    return action.return_path


def consume_action(token,purpose):
    try:token_id=signing.Signer(key=_key(),salt='maison.email-action.v1').unsign(token)
    except (signing.BadSignature,TypeError,ValueError):raise DomainError('action_token_invalid','This link is expired or already used.',410)
    try:token_id=uuid.UUID(token_id)
    except (ValueError,TypeError):raise DomainError('action_token_invalid','This link is expired or already used.',410)
    initial=EmailActionToken.objects.filter(pk=token_id,purpose=purpose).first()
    if initial:User.objects.select_for_update().get(pk=initial.user_id)
    action=EmailActionToken.objects.select_for_update().filter(pk=token_id,purpose=purpose).first()
    if not action or action.consumed_at or action.expires_at<=timezone.now() or not action.user.is_active or action.user.email!=action.email_normalized or not hmac.compare_digest(action.token_sha256,_digest(token)):
        raise DomainError('action_token_invalid','This link is expired or already used.',410)
    return action


def confirm_email_verification(token,request=None):
    with transaction.atomic():
        action=consume_action(token,'verify_email');user=User.objects.select_for_update().get(pk=action.user_id)
        user.is_verified=True;user.version+=1;user.save(update_fields=['is_verified','version'])
        from .guardian import confirm_direct_account_verification
        confirm_direct_account_verification(user)
        from .email_identity import ensure_email_address
        ensure_email_address(user,verified=True)
        action.consumed_at=timezone.now();action.save(update_fields=['consumed_at']);audit(user,'account.email_verified',user)
        if request is not None:
            device=getattr(request,'device',None)
            request.session.cycle_key();rotate_token(request)
            if device is not None:
                Device.objects.filter(pk=device.pk,user=request.user,revoked_at=None).update(session_id=request.session.session_key,version=F('version')+1)
                request.user._maison_operation_authority=(request.user.session_epoch,device.pk,request.session.session_key,device.token_binding_sha256)
    return user


def confirm_password_reset(token,new_password,*,password_consent=None):
    _password(new_password)
    with transaction.atomic():
        action=consume_action(token,'password_reset');user=User.objects.select_for_update().get(pk=action.user_id)
        user.set_password(new_password);user.session_epoch+=1;user.version+=1;user.save(update_fields=['password','session_epoch','version'])
        now=timezone.now();session_keys=list(Device.objects.filter(user=user,revoked_at__isnull=True).exclude(session_id=None).values_list('session_id',flat=True))
        Session.objects.filter(session_key__in=session_keys).delete();Device.objects.filter(user=user,revoked_at__isnull=True).update(revoked_at=now,version=F('version')+1)
        EmailActionToken.objects.filter(user=user,consumed_at__isnull=True).update(consumed_at=now)
        from reader.models import DownloadLicense
        DownloadLicense.objects.filter(user=user,revoked_at=None).update(revoked_at=now)
        audit(user,'account.password_reset',user)
        record_password_purpose_consent(user,'password_reset',password_consent)


@transaction.atomic
def bind_device(request,user):
    from core.services import locked_actor
    user=locked_actor(user)
    if not request.session.session_key:request.session.save()
    token=secrets.token_urlsafe(32)
    session=Session.objects.get(session_key=request.session.session_key)
    previous=getattr(request,'device',None)
    replaced=Device.objects.filter(Q(session=session)|Q(pk=getattr(previous,'pk',None))).filter(revoked_at=None)
    identifiers=list(replaced.values_list('pk',flat=True));now=timezone.now()
    replaced.update(session=None,revoked_at=now,version=F('version')+1)
    if identifiers:
        from reader.models import DownloadLicense
        DownloadLicense.objects.filter(device_id__in=identifiers,revoked_at=None).update(revoked_at=now)
    device=Device.objects.create(user=user,session=session,token_binding_sha256=_digest(token),
        label='Browser',expires_at=timezone.now()+timedelta(seconds=28800 if user.is_staff else 1209600))
    request.session['device_id']=str(device.id);request.session['session_epoch']=user.session_epoch;request.session['reauthenticated_at']=timezone.now().isoformat();request.session['staff_last_seen']=timezone.now().isoformat()
    request.session.set_expiry(28800 if user.is_staff else 1209600)
    request.device=device;request._maison_device_cookie=token
    return device


def login_member(request,email,password,*,password_consent=None):
    email=_email(email);check_rate('login',email,5,900)
    user=authenticate(request,email=email,password=password)
    if user is None:raise DomainError('invalid_credentials','Email or password is incorrect.',403)
    if not user.is_verified:raise DomainError('email_verification_required','Verify your email before signing in.',403)
    with transaction.atomic():
        login(request,user)
        record_password_purpose_consent(user,'sign_in',password_consent)
    return user


@transaction.atomic
def logout_member(request):
    if request.user.is_authenticated:User.objects.select_for_update().get(pk=request.user.pk)
    if request.user.is_authenticated:
        Device.objects.filter(user=request.user,session_id=request.session.session_key,revoked_at__isnull=True).update(revoked_at=timezone.now(),version=F('version')+1)
    if request.user.is_authenticated:
        from reader.models import DownloadLicense
        DownloadLicense.objects.filter(user=request.user,device_id=request.session.get('device_id'),revoked_at=None).update(revoked_at=timezone.now())
    logout(request);request._maison_clear_device_cookie=True


@transaction.atomic
def session_data(request):
    user=request.user;flags=getattr(settings,'FEATURES',{})
    member=None
    if user.is_authenticated:
        from core.services import locked_actor
        user=locked_actor(user)
        prefs,_=Preferences.objects.get_or_create(user=user)
        member={'member_id':str(user.public_id),'display_name':user.display_name,'locale':prefs.locale,'email_verified':user.is_verified,'email':user.email,'created_at':iso(user.date_joined),'version':user.version}
    return {'authenticated':user.is_authenticated,'member':member,'device_id':request.session.get('device_id') if user.is_authenticated else None,'csrf_token':get_token(request),'reauthenticated_at':request.session.get('reauthenticated_at','').replace('+00:00','Z') or None if user.is_authenticated else None,
        'features':{'email_magic_link':flags.get('email_link',False),'phone_otp':flags.get('phone_otp',False),'recurring_pass':flags.get('recurring_billing',False),'video_format_switch':False,'word_read_along':flags.get('word_read_along',False),'gifts':False,'clips':False}}


def preferences_data(pref):
    fields=['locale','theme','reader_theme','reader_font_size','reader_typeface','reader_margins','reader_alignment','reader_layout','audio_quality_kbps','reduced_motion','low_data_mode','daily_goal_minutes','interests','goal','search_filters','saved_filters','version']
    result={k:getattr(pref,k) for k in fields};result['reader_line_height']=float(pref.reader_line_height);result['updated_at']=iso(pref.updated_at)
    return result


@transaction.atomic
def update_preferences(user,data,base_version):
    # Validate the complete nested contract before creating/locking or changing state.
    # This boundary also protects direct SSR callers of the shared service.
    from library.validation import validate_schema
    validate_schema(data,'PreferencesPatch')
    from core.services import locked_actor
    locked_actor(user)
    pref,_=Preferences.objects.get_or_create(user=user)
    pref=Preferences.objects.select_for_update().get(pk=pref.pk)
    if pref.version!=base_version:raise DomainError('version_conflict','Preferences changed on another device.',412,preferences_data(pref))
    choices={'locale':['en','bn'],'theme':['light','dark','true_black'],'reader_theme':['system','light','sepia','dark','true_black'],
        'reader_font_size':[16,20,23,26,30],'reader_typeface':['serif','sans'],'reader_margins':['compact','comfortable','wide'],
        'reader_alignment':['start','justify'],'reader_layout':['scroll','paginated'],'audio_quality_kbps':[48,96],'goal':['relax','learn','interview']}
    allowed=set(preferences_data(pref))-{'version','updated_at'}
    if not data or set(data)-allowed:raise DomainError('validation_error','Invalid preference field.',422)
    for key,value in data.items():
        if key in choices and value not in choices[key]:raise DomainError('validation_error',f'Invalid {key}.',422)
        if key in ['reduced_motion','low_data_mode'] and not isinstance(value,bool):raise DomainError('validation_error','Expected a boolean.',422)
        if key=='daily_goal_minutes' and (type(value)!=int or not 5<=value<=120):raise DomainError('validation_error','Invalid daily goal.',422)
        if key=='reader_line_height':
            try:value=Decimal(str(value))
            except InvalidOperation:raise DomainError('validation_error','Invalid leading.',422)
            if not Decimal('1.50')<=value<=Decimal('2.40'):raise DomainError('validation_error','Invalid leading.',422)
        if key=='interests' and (not isinstance(value,list) or len(value)>8 or len(value)!=len(set(value)) or any(x not in ['classics','golpo','learn','interview','series','collections'] for x in value)):
            raise DomainError('validation_error','Invalid interests.',422)
        if key=='search_filters' and (not isinstance(value,dict) or len(json.dumps(value).encode())>2048 or set(value)-{'house','format','locale','author','topic','level','duration_min','duration_max','access','recency_days'}):
            raise DomainError('validation_error','Invalid saved filters.',422)
        if key=='saved_filters':
            if not isinstance(value,list) or len(value)>20 or any(not isinstance(x,dict) or set(x)!={'name','query','filters'} or not isinstance(x['name'],str) or not 1<=len(x['name'])<=100 or not isinstance(x['query'],str) or len(x['query'])>120 or not isinstance(x['filters'],dict) for x in value):raise DomainError('validation_error','Invalid saved filters.',422)
        setattr(pref,key,value)
    pref.version+=1;pref.save();return preferences_data(pref)


def process_outbox_job(job,max_seconds=45):
    if job.kind in ('privacy_export','privacy_delete') and job.payload.get('guardian_authorization_id'):
        from .guardian import process_privacy_job
        return process_privacy_job(job,max_seconds=max_seconds)
    if job.kind=='email_action':
        from .email_delivery import deliver_action
        return deliver_action(job,max_seconds=max_seconds)
    if job.kind=='privacy_export':
        from .privacy import create_export
        return create_export(job,max_seconds=max_seconds)
    if job.kind=='privacy_delete':
        from .privacy import delete_account
        return delete_account(job)
    if job.kind=='contact_support':
        recipient=getattr(settings,'SUPPORT_EMAIL','')
        if not recipient and not settings.LOCAL:raise DomainError('support_not_configured','Support delivery must be configured.',503)
        if recipient:
            from .email_delivery import submit_message
            return submit_message(job,'Earnalism support: '+job.payload['category'],job.payload['message']+'\nReply to: '+job.payload['email'],[recipient],max_seconds=max_seconds)
        return {'status':'recorded_for_local_operator','external_delivery':False}
    raise DomainError('unknown_job_kind','No handler exists for this job.',409)
