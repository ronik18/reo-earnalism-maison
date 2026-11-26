import hashlib
import hmac
import ipaddress
import re
import time
import uuid
from django.conf import settings
from django.http import HttpResponseNotModified, JsonResponse


def private_headers(response):
    current=response.get('Cache-Control','')
    if 'private' not in current.lower() or 'no-store' not in current.lower():
        response['Cache-Control']='private, no-store'
    response['CDN-Cache-Control']='no-store'
    response['Cloudflare-CDN-Cache-Control']='no-store'
    response['Pragma']='no-cache'
    vary={p.strip() for p in response.get('Vary','').split(',') if p.strip()}
    response['Vary']=', '.join(sorted(vary|{'Cookie','Authorization'}))
    return response


def public_asset_headers(request,response,edge):
    """Public live cover bytes (owner decision 26 Nov 2026): keep the view's rights-capped browser policy.

    The view admits only covers cleared in every publication territory. The
    shared edge copy is admitted only when its exact URL is recorded for
    publication/withdrawal purge; otherwise the edge must not store it.
    The bytes do not depend on the member, so Vary is not Cookie.
    """
    current=response.get('Cache-Control','').lower()
    if (response.status_code!=200 or getattr(response,'streaming',False) or int(edge)<=0
            or 'public' not in current or 'private' in current or 'no-store' in current):
        return private_headers(response)
    from .cache import public_cover_covered,record_public_cover
    etag=response.get('ETag')
    conditional=bool(etag) and request.headers.get('If-None-Match')==etag
    if conditional and public_cover_covered(request,response,int(edge)):
        # A 304 revalidation never writes the ledger; the existing row already covers the edge copy.
        response['Cloudflare-CDN-Cache-Control']=f'public, max-age={int(edge)}, stale-while-revalidate=0, stale-if-error=0'
        response['CDN-Cache-Control']=f'public, max-age={int(edge)}, stale-while-revalidate=0, stale-if-error=0'
        response['Vary']=', '.join(sorted(p.strip() for p in response.get('Vary','').split(',') if p.strip() and p.strip().lower()!='cookie')) or 'Accept-Encoding'
        not_modified=HttpResponseNotModified()
        for key,value in response.items():not_modified[key]=value
        return not_modified
    edge=record_public_cover(request,response,int(edge))
    if edge>0:
        response['Cloudflare-CDN-Cache-Control']=f'public, max-age={edge}, stale-while-revalidate=0, stale-if-error=0'
        response['CDN-Cache-Control']=f'public, max-age={edge}, stale-while-revalidate=0, stale-if-error=0'
    else:
        response['Cloudflare-CDN-Cache-Control']='no-store'
        response['CDN-Cache-Control']='no-store'
    response['Vary']=', '.join(sorted(p.strip() for p in response.get('Vary','').split(',') if p.strip() and p.strip().lower()!='cookie')) or 'Accept-Encoding'
    if conditional and edge<=0:
        # Not recordable for the edge (member/off-origin): a browser-only 304 is safe without a ledger row.
        not_modified=HttpResponseNotModified()
        for key,value in response.items():not_modified[key]=value
        return not_modified
    # A conditional request that had to write the ledger gets the full 200, so no 304 ever writes.
    return response


def cache_headers(request,response):
    vary={p.strip().lower() for p in response.get('Vary','').split(',') if p.strip()}
    if 'authorization' in vary or response.cookies or response.has_header('Set-Cookie'):
        return private_headers(response)
    edge=getattr(response,'_maison_public_asset_edge_ttl',None)
    if edge is not None:return public_asset_headers(request,response,edge)
    from .cache import finalize_public_response
    response=finalize_public_response(request,response)
    match=re.search(r'(?:^|,)\s*s-maxage=(\d+)(?:,|$)',response.get('Cache-Control',''))
    if not match or 'public' not in response.get('Cache-Control','') or int(match[1])<=0:
        return private_headers(response)
    ttl=int(match[1])
    response['Cache-Control']='public, max-age=0, must-revalidate'
    response['Cloudflare-CDN-Cache-Control']=f'public, max-age={ttl}, stale-while-revalidate=0, stale-if-error=0'
    response['CDN-Cache-Control']=f'public, max-age={ttl}, stale-while-revalidate=0, stale-if-error=0'
    # SessionMiddleware marks anonymous session access as Vary:Cookie, even when
    # no cookie or personal session was emitted. Capture has already verified
    # this exact response is anonymous and its actual public dependencies.
    response['Vary']=', '.join(sorted(p.strip() for p in response.get('Vary','').split(',') if p.strip() and p.strip().lower()!='cookie')) or 'Accept-Encoding'
    if response.get('Content-Type','').startswith('text/html'):response['Content-Language']='en'
    elif re.fullmatch('[a-z]{2}',request.GET.get('locale','')):response['Content-Language']=request.GET['locale']
    if not response.has_header('ETag') and response.get('Content-Type','').split(';')[0] in {'application/json','text/html'}:
        response['ETag']='W/"'+hashlib.sha256(response.content).hexdigest()+'"'
    etag=response.get('ETag')
    if etag:
        if request.headers.get('If-None-Match')==etag:
            conditional=HttpResponseNotModified()
            for key,value in response.items():conditional[key]=value
            return conditional
    return response


def content_security_policy():
    assets=[]
    if getattr(settings,'R2_PUBLIC_ASSET_HOST',''):assets.append(settings.R2_PUBLIC_ASSET_HOST.rstrip('/'))
    private=[]
    if getattr(settings,'MEDIA_STORAGE_BACKEND','local')=='r2' and getattr(settings,'R2_ENDPOINT_URL',''):
        private.append(settings.R2_ENDPOINT_URL.rstrip('/'))
    scripts=["'self'",*assets];connect=["'self'",*private,*assets];frames=["'none'"];stream=[]
    if getattr(settings,'RAZORPAY_ENABLED',False):
        scripts.append('https://checkout.razorpay.com')
        connect.append('https://api.razorpay.com')
        frames=['https://api.razorpay.com','https://checkout.razorpay.com']
    stream_host=getattr(settings,'STREAM_CUSTOMER_HOST','')
    if (getattr(settings,'FEATURES',{}).get('video')
            and re.fullmatch(r'customer-[a-z0-9]+\.cloudflarestream\.com',stream_host)):
        stream=['https://'+stream_host]
        scripts.append('https://embed.cloudflarestream.com')
        connect.extend(stream)
        frames=([host for host in frames if host!="'none'"]+stream)
    directives={
        'default-src':["'self'"], 'img-src':["'self'",'data:',*assets],
        'style-src':["'self'",*assets], 'script-src':scripts,
        'font-src':["'self'",*assets], 'connect-src':connect,
        'media-src':["'self'",'blob:',*private,*stream], 'frame-src':frames,
        'base-uri':["'self'"], 'frame-ancestors':["'none'"], 'form-action':["'self'"],
    }
    return '; '.join(name+' '+' '.join(values) for name,values in directives.items())


class RequestContextMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        started=time.monotonic()
        try:
            value=uuid.UUID(request.headers.get('X-Request-ID',''))
            if value.version!=4:raise ValueError
        except (ValueError,AttributeError):value=uuid.uuid4()
        request.request_id=str(value)
        request.territory='IN' if settings.LOCAL else 'ZZ'
        request.trusted_client_ip=None
        response=self.get_response(request)
        # Outermost finalization sees cookies added by every inner middleware.
        response=cache_headers(request,response)
        response['X-Request-ID']=request.request_id
        response['X-Content-Type-Options']='nosniff'
        response.setdefault('Referrer-Policy',settings.SECURE_REFERRER_POLICY)
        response['Content-Security-Policy']=content_security_policy()
        routine_liveness = (request.method=='GET' and request.path=='/api/v1/health/live' and response.status_code==200)
        if getattr(settings,'SECURITY_EVENT_LOGGING',False) and not routine_liveness:
            from .security_events import emit_request_event
            emit_request_event(request,response,(time.monotonic()-started)*1000)
        return response


class PublicCacheStartMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        from .cache import begin_public_response
        begin_public_response(request)
        return self.get_response(request)


class OriginMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if not settings.LOCAL and request.path!='/api/v1/health/live':
            received=request.headers.get('X-Maison-Origin','')
            expected=settings.ORIGIN_SHARED_SECRET
            if not expected or len(received)>512 or not hmac.compare_digest(received.encode(),expected.encode()):
                return JsonResponse({'type':'about:blank','title':'Forbidden','status':403,
                    'code':'origin_forbidden','detail':'Use the configured application origin.',
                    'request_id':request.request_id,'retryable':False},status=403,content_type='application/problem+json')
            # The reviewed Cloudflare request transform overwrites both custom
            # origin/country headers. Direct callers cannot choose a country.
            country=request.headers.get('X-Maison-Country','')
            request.territory=country if re.fullmatch('[A-Z]{2}',country) and country!='XX' else 'ZZ'
            try:request.trusted_client_ip=str(ipaddress.ip_address(request.headers.get('CF-Connecting-IP','')))
            except ValueError:request.trusted_client_ip=None
        if (getattr(settings,'INDIA_FIRST_LAUNCH_ENABLED',False)
            and request.path not in {'/api/v1/health/live','/api/v1/health/ready'}
            and not re.fullmatch(r'/(en|bn)/(privacy|terms|contact)/',request.path)
            and request.territory not in settings.MAISON_SERVICE_TERRITORIES):
            # Availability is based on trusted edge location, never citizenship.
            # Reject before session/authentication or request-body collection.
            if request.path.startswith('/api/'):
                response=JsonResponse({'type':'about:blank','title':'Not yet available','status':403,
                    'code':'service_region_unavailable','detail':'Earnalism is not yet available in your country.',
                    'request_id':request.request_id,'retryable':False},status=403,content_type='application/problem+json')
            else:
                from django.shortcuts import render
                response=render(request,'web/region_unavailable.html',status=403)
            response['Cache-Control']='private, no-store'
            return response
        return self.get_response(request)
