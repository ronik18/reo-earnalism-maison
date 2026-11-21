"""Google OIDC through maintained allauth protocols and framework identity tables."""
import hmac
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit,urlencode
import requests
from urllib3.exceptions import HTTPError as Urllib3HTTPError
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction,IntegrityError,DatabaseError
from django.http import HttpResponseRedirect
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter,get_adapter
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter,_verify_and_decode
from allauth.socialaccount.providers.oauth2.views import OAuth2CallbackView
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from core.api import DomainError,problem
from core.services import audit
from .models import User,Preferences,Consent,Device,RateLimitBucket
from .services import safe_return_path,_digest,_email

PROVIDER_URLS={'https://oauth2.googleapis.com/token','https://www.googleapis.com/oauth2/v1/certs'}


PUBLIC_GOOGLE_ERRORS=frozenset({'identity_link_required','identity_already_linked','reauthentication_required','authentication_required',
    'email_verification_required','identity_mismatch','account_unavailable','feature_disabled','provider_not_configured',
    'google_provider_unavailable','google_authentication_failed','invalid_oauth_state','account_registration_required','account_permission_required'})


def oauth_problem(error,request):
    """Keep the saved local destination without exposing OAuth state or details."""
    if request.get_preferred_type(['application/json','text/html'])=='text/html':
        next_path=getattr(request,'_maison_google_state',{}).get('next','')
        if not next_path and request.path=='/api/v1/auth/google':next_path=request.GET.get('return_path','')
        try:return_path=safe_return_path(next_path or '/en/vault/')
        except DomainError:return_path='/en/vault/'
        match=re.match(r'^/(en|bn)/',return_path)
        locale=match[1] if match else 'en'
        code=error.code if error.code in PUBLIC_GOOGLE_ERRORS else 'google_authentication_failed'
        response=HttpResponseRedirect(f'/{locale}/sign-in/?'+urlencode({'google_error':code,'return_to':return_path}),status=303)
    else:response=problem(error,request)
    response['Referrer-Policy']='no-referrer';response['Cache-Control']='private, no-store'
    return response


def _enabled():
    if not settings.FEATURES.get('google_oauth',False):raise DomainError('feature_disabled','Google sign-in is not enabled.',409)
    callback=getattr(settings,'GOOGLE_REDIRECT_URI','')
    expected=settings.PUBLIC_BASE_URL.rstrip('/')+'/api/v1/auth/google/callback'
    if not getattr(settings,'GOOGLE_CLIENT_ID','') or not getattr(settings,'GOOGLE_CLIENT_SECRET','') or callback!=expected:
        raise DomainError('provider_not_configured','Google sign-in is not configured.',503)
    parsed=urlsplit(callback)
    if parsed.scheme!='https' and not (settings.LOCAL and parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost'}):
        raise DomainError('provider_not_configured','Google callback must use the canonical HTTPS origin.',503)


def _bound_intent(request,data):
    intent=data.get('intent')
    if intent not in {'sign_in','link','reauthenticate'}:raise DomainError('invalid_oauth_state','Start Google sign-in again.',403)
    if data.get('browser_session')!=request.session.session_key:raise DomainError('invalid_oauth_state','Start Google sign-in in this browser again.',403)
    if intent!='sign_in':
        device=getattr(request,'device',None)
        if (not request.user.is_authenticated or not request.user.is_active or not device
            or str(request.user.public_id)!=data.get('member') or str(device.pk)!=data.get('device')):
            raise DomainError('authentication_required','Sign in before linking or confirming an identity.',403)
        if intent=='link':
            if not request.user.is_verified:raise DomainError('email_verification_required','Verify your account email before linking Google.',403)
            stamp=parse_datetime(request.session.get('reauthenticated_at',''))
            if not stamp or timezone.is_naive(stamp) or not timedelta(0)<=timezone.now()-stamp<=timedelta(minutes=5):
                raise DomainError('reauthentication_required','Confirm your identity before linking Google.',403)
    return intent


class GoogleProviderUnavailable(OAuth2Error):pass


class BoundedGoogleSession(requests.Session):
    def __init__(self,deadline):super().__init__();self.deadline=deadline
    def request(self,method,url,**kwargs):
        if url not in PROVIDER_URLS:raise OAuth2Error('Unexpected Google provider endpoint')
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise GoogleProviderUnavailable('Google provider budget expired')
        kwargs.update(timeout=(min(3,remaining),min(5,remaining)),allow_redirects=False,stream=True)
        response=super().request(method,url,**kwargs)
        try:
            length=response.headers.get('Content-Length');expected=int(length) if length is not None else None
            if expected is not None and not 0<=expected<=131072:raise OAuth2Error('Google provider response is too large')
            chunks=[];size=0
            while True:
                remaining=self.deadline-time.monotonic()
                if remaining<=0:raise GoogleProviderUnavailable('Google provider budget expired')
                connection=getattr(response.raw,'_connection',None);sock=getattr(connection,'sock',None)
                if sock is None:
                    buffered=getattr(getattr(response.raw,'_fp',None),'fp',None)
                    sock=getattr(getattr(buffered,'raw',None),'_sock',None)
                if sock is not None and not getattr(sock,'_closed',False):sock.settimeout(max(.01,min(5,remaining)))
                block=response.raw.read(min(16384,131073-size),decode_content=True)
                if not block:break
                size+=len(block)
                if size>131072:raise OAuth2Error('Google provider response is too large')
                chunks.append(block)
            response._content=b''.join(chunks);response._content_consumed=True
            if time.monotonic()>=self.deadline:raise GoogleProviderUnavailable('Google provider budget expired')
            return response
        except (Urllib3HTTPError,OSError):
            raise GoogleProviderUnavailable('Google provider response was interrupted') from None
        finally:response.close()


class MaisonAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self,request):
        state=getattr(request,'_maison_google_state',{})
        return safe_return_path(state.get('next') or '/en/vault/')


class MaisonSocialAccountAdapter(DefaultSocialAccountAdapter):
    def generate_state_param(self,state):return secrets.token_urlsafe(32)
    def get_requests_session(self):
        return BoundedGoogleSession(getattr(self.request,'_maison_google_deadline',time.monotonic()+8))
    def on_authentication_error(self,request,provider,error=None,exception=None,extra_context=None):
        retryable=isinstance(exception,(requests.RequestException,GoogleProviderUnavailable))
        raise ImmediateHttpResponse(oauth_problem(DomainError('google_provider_unavailable' if retryable else 'google_authentication_failed','Google authentication is temporarily unavailable. Start again.' if retryable else 'Google authentication failed. Start again.',503 if retryable else 403),request))
    def get_connect_redirect_url(self,request,socialaccount):
        return safe_return_path(getattr(request,'_maison_google_state',{}).get('next') or '/en/settings/')
    def pre_social_login(self,request,sociallogin):
        state=getattr(request,'_maison_google_state',{})
        data=state.get('data',{});intent=_bound_intent(request,data)
        claims=sociallogin.account.extra_data
        if claims.get('email_verified') is not True or not claims.get('email'):
            raise ImmediateHttpResponse(oauth_problem(DomainError('email_verification_required','Google must verify this email address.',403),request))
        email=claims['email'].strip().casefold()
        sociallogin.account.extra_data={'sub':sociallogin.account.uid,'email':email,'email_verified':True}
        if sociallogin.is_existing and not sociallogin.user.is_active:
            raise ImmediateHttpResponse(oauth_problem(DomainError('account_unavailable','This account is unavailable.',403),request))
        if intent=='reauthenticate':
            if not sociallogin.is_existing or sociallogin.user.pk!=request.user.pk:
                raise ImmediateHttpResponse(oauth_problem(DomainError('identity_mismatch','Use the Google identity linked to your account.',403),request))
            request.session['reauthenticated_at']=timezone.now().isoformat();rotate_token(request)
            audit(request.user,'account.google_reauthenticated',request.user)
            raise ImmediateHttpResponse(HttpResponseRedirect(safe_return_path(state.get('next') or '/en/settings/')))
        if intent=='link':
            if User.objects.filter(email=email).exclude(pk=request.user.pk).exists() or EmailAddress.objects.filter(email__iexact=email).exclude(user=request.user).exists():
                raise ImmediateHttpResponse(oauth_problem(DomainError('identity_link_required','Sign in to the account matching this Google email before linking.',409),request))
            if sociallogin.is_existing and sociallogin.user.pk!=request.user.pk:
                raise ImmediateHttpResponse(oauth_problem(DomainError('identity_already_linked','This Google identity cannot be linked.',409),request))
            return
        from .enrollment import enabled,adult_declaration
        if enabled() and not sociallogin.is_existing:
            if data.get('create_account') is not True:
                raise ImmediateHttpResponse(oauth_problem(DomainError('account_registration_required','Create your account first. A parent or legal guardian creates a younger reader’s account.',403),request))
            try:adult_declaration(data.get('account_declaration',{}))
            except DomainError as error:raise ImmediateHttpResponse(oauth_problem(error,request))
        if not sociallogin.is_existing and (User.objects.filter(email=email).exists() or EmailAddress.objects.filter(email__iexact=email).exists()):
            raise ImmediateHttpResponse(oauth_problem(DomainError('identity_link_required','Sign in to your existing account, then explicitly link Google in Settings.',409),request))
    def save_user(self,request,sociallogin,form=None):
        from .enrollment import enabled,adult_declaration,record_adult
        declaration=None
        if enabled():
            state=getattr(request,'_maison_google_state',{}).get('data',{})
            if state.get('create_account') is not True:raise DomainError('account_registration_required','Create your account through the permitted signup route first.',403)
            declaration=adult_declaration(state.get('account_declaration',{}))
        try:
            with transaction.atomic():
                sociallogin.user.email=sociallogin.account.extra_data['email'];sociallogin.user.is_verified=True
                user=super().save_user(request,sociallogin,form)
                Preferences.objects.get_or_create(user=user);Consent.objects.get_or_create(user=user,defaults={'necessary_notice_version':settings.PRIVACY_NOTICE_VERSION})
                record_adult(user,declaration,'google_registration')
                audit(user,'account.google_registered',user)
                return user
        except IntegrityError:
            raise ImmediateHttpResponse(oauth_problem(DomainError('identity_link_required','Sign in to your existing account, then explicitly link Google.',409),request)) from None


class MaisonGoogleAdapter(GoogleOAuth2Adapter):
    def get_callback_url(self,request,app):return settings.GOOGLE_REDIRECT_URI
    def complete_login(self,request,app,token,**kwargs):
        credential=kwargs.get('response',{}).get('id_token')
        if not credential:raise OAuth2Error('A Google ID token is required')
        result=super().complete_login(request,app,token,**kwargs)
        data=result.account.extra_data
        result.account.extra_data={'sub':result.account.uid,'email':data['email'].strip().casefold(),'email_verified':True}
        return result
    def _decode_id_token(self,app,id_token):
        import jwt
        if jwt.get_unverified_header(id_token).get('alg')!='RS256':raise OAuth2Error('Unexpected Google signing algorithm')
        data=_verify_and_decode(app,id_token,verify_signature=True)
        nonce=getattr(self.request,'_maison_google_state',{}).get('data',{}).get('nonce')
        if (data.get('azp',app.client_id)!=app.client_id or (isinstance(data.get('aud'),list) and len(data['aud'])>1 and data.get('azp')!=app.client_id)
            or not isinstance(nonce,str) or not isinstance(data.get('nonce'),str) or not hmac.compare_digest(nonce,data['nonce'])
            or data.get('email_verified') is not True or not isinstance(data.get('email'),str) or type(data.get('exp'))!=int or data['exp']<=time.time() or not isinstance(data.get('sub'),str) or not 1<=len(data['sub'])<=255):
            raise OAuth2Error('Invalid Google identity claims')
        try:data['email']=_email(data['email'])
        except DomainError:raise OAuth2Error('Invalid Google email') from None
        return data


class MaisonGoogleCallback(OAuth2CallbackView):
    def _get_state(self,request,provider):
        key=request.session.session_key
        if not key:raise DomainError('invalid_oauth_state','Start Google sign-in again.',403)
        # Serialize only consumption of allauth's session-backed one-use state.
        with transaction.atomic():
            if not Session.objects.select_for_update().filter(pk=key,expire_date__gt=timezone.now()).exists():
                raise DomainError('invalid_oauth_state','Start Google sign-in again.',403)
            request.session=request.session.__class__(key)
            state,response=super()._get_state(request,provider)
            if state:
                # A stale parallel SessionMiddleware save must not resurrect consumed state.
                _,created=RateLimitBucket.objects.get_or_create(key_hash=_digest('google-state:'+key+':'+request.GET.get('state','')),purpose='google_state_used',window=0,defaults={'count':1,'expires_at':timezone.now()+timedelta(seconds=600)})
                if not created:raise DomainError('invalid_oauth_state','This Google challenge was already used.',403)
                request._maison_google_state=state
                _bound_intent(request,state.get('data',{}))
        return state,response


def start(request):
    _enabled()
    from .enrollment import enabled,ACCOUNT_FIELDS,adult_declaration
    if set(request.GET)-({'intent','return_path','create_account'}|ACCOUNT_FIELDS) or any(len(request.GET.getlist(key))!=1 for key in request.GET):
        raise DomainError('validation_error','Invalid Google sign-in parameters.',422)
    intent=request.GET.get('intent','sign_in');return_path=safe_return_path(request.GET.get('return_path','/en/vault/'))
    if not request.session.session_key:request.session.create()
    data={'intent':intent,'browser_session':request.session.session_key,'nonce':secrets.token_urlsafe(32)}
    if enabled():
        create=request.GET.get('create_account','false')
        if create not in ('true','false'):raise DomainError('validation_error','Choose a valid account action.',422)
        if create=='true':
            if intent!='sign_in':raise DomainError('validation_error','Account creation is available only through signup.',422)
            declaration={k:request.GET.get(k) for k in ACCOUNT_FIELDS}
            declaration['account_terms_consent']=declaration.get('account_terms_consent')=='true'
            data.update(create_account=True,account_declaration=adult_declaration(declaration))
        else:data['create_account']=False
    if intent!='sign_in':
        data.update(member=str(getattr(request.user,'public_id','')),device=str(getattr(getattr(request,'device',None),'pk','')))
    _bound_intent(request,data)
    provider=get_adapter(request).get_provider(request,'google');provider.oauth2_adapter_class=MaisonGoogleAdapter
    if not provider.get_pkce_params():raise DomainError('provider_not_configured','Google PKCE must be enabled.',503)
    return provider.redirect(request,process='connect' if intent=='link' else 'login',next_url=return_path,data=data,scope=['openid','email','profile'],auth_params={'nonce':data['nonce']})


def callback(request):
    _enabled()
    if any(len(request.GET.getlist(key))!=1 for key in request.GET) or len(request.GET.get('state',''))>512 or len(request.GET.get('code',''))>4096:
        raise DomainError('validation_error','Invalid Google callback parameters.',422)
    request._maison_google_deadline=time.monotonic()+8
    try:return MaisonGoogleCallback.adapter_view(MaisonGoogleAdapter)(request)
    except (DomainError,DatabaseError):raise
    except Exception:raise DomainError('google_authentication_failed','Google authentication failed. Start again.',403) from None
