"""Contract-defined authenticated rate policies, using the existing SQL counters."""
import json
import ipaddress
import re
from functools import lru_cache
from django.conf import settings
from django.db import DatabaseError
from core.api import DomainError,problem,json_body

MEMBER_POLICIES={'member_read','member_write','progress','sync','media_grant','checkout'}
PUBLIC_AUTH_POLICIES={'authentication','registration','email_action'}


@lru_cache(maxsize=1)
def _operations():
    contract=json.loads((settings.BASE_DIR/'contracts/openapi.yaml').read_text())
    rules=[]
    for path,operations in contract['paths'].items():
        expression='^/api/v1'+re.sub(r'\{[^}]+\}',r'[^/]+',path)+'$'
        for method,operation in operations.items():
            if not isinstance(operation,dict):continue
            policy=operation.get('x-rate-limit',{}).get('policy')
            if policy in MEMBER_POLICIES or (path.startswith('/auth/') and policy in PUBLIC_AUTH_POLICIES):
                rules.append((re.compile(expression),method.upper(),policy,contract['x-rate-policies'][policy]))
    return rules


def _policy_path(request):
    # SSR forms and JSON APIs share one budget, not parallel ways around it.
    match=re.fullmatch(r'/(?:en|bn)/(sign-in|sign-up|password-reset|email-sign-in|independent-account)/',request.path)
    aliases={'sign-in':'login','sign-up':'register','password-reset':'password-resets/request','email-sign-in':'email-links/request','independent-account':'account-capacity'}
    return '/api/v1/auth/'+aliases[match[1]] if match and request.method=='POST' else request.path


FORM_MODES={'sign-in':'sign-in','sign-up':'sign-up','password-reset':'reset','email-sign-in':'email-link','independent-account':'independent'}


def _web_form_problem(error,request):
    """Server-rendered auth forms get a readable page, not raw problem JSON."""
    match=re.fullmatch(r'/(?:en|bn)/(sign-in|sign-up|password-reset|email-sign-in|independent-account)/',request.path)
    if not match or error.code!='rate_limited':return None
    from web.views import page,error_locale
    return page(request,error_locale(request),'web/auth.html',status=error.status,auth_mode=FORM_MODES[match[1]],error_key='sign_in_rate_limited')


def _policy(request):
    for expression,method,name,policy in _operations():
        if method==request.method and expression.fullmatch(_policy_path(request)):return name,policy
    return None,None


def _client_ip(request):
    # Only OriginMiddleware may attest a production identity. Raw CF/forwarding
    # headers and the proxy peer address are never a substitute for that attestation.
    value=getattr(request,'trusted_client_ip',None)
    if value is None and settings.LOCAL:value=request.META.get('REMOTE_ADDR')
    try:return str(ipaddress.ip_address(value))
    except (ValueError,TypeError):return None


def _public_auth_limit(request,name,policy):
    from accounts.services import check_rate
    from accounts.models import normalize_email_address
    identity=_client_ip(request)
    if identity is None:raise DomainError('client_context_unavailable','A validated client network identity is required. Please retry.',503)
    # Extra IP-wide limits prevent rotating destinations to bypass email/identity buckets.
    count=3 if name=='registration' else 20 if name=='email_action' else 30
    metadata=check_rate('public_'+name+'_ip',identity,count,3600)
    if name=='registration':return metadata
    try:
        if request.path.startswith('/api/v1/'):data=json_body(request)
        else:
            if len(request.body)>262144:raise DomainError('payload_too_large','The request exceeds256KiB.',413)
            data=request.POST
    except DomainError as error:error.rate_limit=metadata;raise
    email=data.get('email')
    if not isinstance(email,str):return metadata
    email=normalize_email_address(email)
    identifier=email+(':ip:'+identity if name=='authentication' else '')
    return check_rate('public_'+name+'_identity',identifier,policy['requests'],policy['window_seconds'])


class MemberRateLimitMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        name,policy=_policy(request)
        public_auth=name in PUBLIC_AUTH_POLICIES and _policy_path(request).startswith('/api/v1/auth/')
        if not name or (not public_auth and not request.user.is_authenticated):return self.get_response(request)
        try:
            if public_auth:metadata=_public_auth_limit(request,name,policy)
            else:
                identifier='member:'+str(request.user.public_id)
                if 'device' in policy['scope']:
                    identifier+=':device:'+str(getattr(getattr(request,'device',None),'pk',None) or request.session.get('device_id','unbound'))
                if 'IP' in policy['scope']:
                    client_ip=_client_ip(request)
                    if client_ip is None:raise DomainError('client_context_unavailable','A validated client network identity is required. Please retry.',503)
                    identifier+=':ip:'+client_ip
                from accounts.services import check_rate
                metadata=check_rate('api_'+name,identifier,policy['requests'],policy['window_seconds'])
        except DomainError as error:
            response=_web_form_problem(error,request) or problem(error,request);metadata=getattr(error,'rate_limit',None)
        except DatabaseError:
            return problem(DomainError('temporarily_unavailable','Please retry this operation.',503),request)
        else:response=self.get_response(request)
        if metadata:
            response['RateLimit-Limit']=str(metadata['limit'])
            response['RateLimit-Remaining']=str(metadata['remaining'])
            response['RateLimit-Reset']=str(metadata['reset'])
            if response.status_code==429:response['Retry-After']=str(metadata['reset'])
        return response
