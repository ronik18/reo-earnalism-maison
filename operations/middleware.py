import hashlib
import hmac
import ipaddress
import re
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


def cache_headers(request,response):
    vary={p.strip().lower() for p in response.get('Vary','').split(',') if p.strip()}
    if 'authorization' in vary or response.cookies or response.has_header('Set-Cookie'):
        return private_headers(response)
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
    if response.get('Content-Type','').split(';')[0] in {'application/json','text/html'}:
        etag='W/"'+hashlib.sha256(response.content).hexdigest()+'"'
        response['ETag']=etag
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
        return self.get_response(request)
