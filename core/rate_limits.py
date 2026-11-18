"""Contract-defined authenticated rate policies, using the existing SQL counters."""
import json
import ipaddress
import re
from functools import lru_cache
from django.conf import settings
from django.db import DatabaseError
from core.api import DomainError,problem

MEMBER_POLICIES={'member_read','member_write','progress','sync','media_grant','checkout'}


@lru_cache(maxsize=1)
def _operations():
    contract=json.loads((settings.BASE_DIR/'contracts/openapi.yaml').read_text())
    rules=[]
    for path,operations in contract['paths'].items():
        expression='^/api/v1'+re.sub(r'\{[^}]+\}',r'[^/]+',path)+'$'
        for method,operation in operations.items():
            if not isinstance(operation,dict):continue
            policy=operation.get('x-rate-limit',{}).get('policy')
            if policy in MEMBER_POLICIES:
                rules.append((re.compile(expression),method.upper(),policy,contract['x-rate-policies'][policy]))
    return rules


def _policy(request):
    for expression,method,name,policy in _operations():
        if method==request.method and expression.fullmatch(request.path):return name,policy
    return None,None


def _client_ip(request):
    # Only OriginMiddleware may attest a production identity. Raw CF/forwarding
    # headers and the proxy peer address are never a substitute for that attestation.
    value=getattr(request,'trusted_client_ip',None)
    if value is None and settings.LOCAL:value=request.META.get('REMOTE_ADDR')
    try:return str(ipaddress.ip_address(value))
    except (ValueError,TypeError):return None


class MemberRateLimitMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if not request.user.is_authenticated:return self.get_response(request)
        name,policy=_policy(request)
        if not name:return self.get_response(request)
        identifier='member:'+str(request.user.public_id)
        if 'device' in policy['scope']:
            identifier+=':device:'+str(getattr(getattr(request,'device',None),'pk',None) or request.session.get('device_id','unbound'))
        if 'IP' in policy['scope']:
            client_ip=_client_ip(request)
            if client_ip is None:
                return problem(DomainError('client_context_unavailable','A validated client network identity is required. Please retry.',503),request)
            identifier+=':ip:'+client_ip
        try:
            from accounts.services import check_rate
            metadata=check_rate('api_'+name,identifier,policy['requests'],policy['window_seconds'])
        except DomainError as error:
            response=problem(error,request);metadata=getattr(error,'rate_limit',None)
        except DatabaseError:
            return problem(DomainError('temporarily_unavailable','Please retry this operation.',503),request)
        else:response=self.get_response(request)
        if metadata:
            response['RateLimit-Limit']=str(metadata['limit'])
            response['RateLimit-Remaining']=str(metadata['remaining'])
            response['RateLimit-Reset']=str(metadata['reset'])
            if response.status_code==429:response['Retry-After']=str(metadata['reset'])
        return response
