"""Keep old localized links usable without maintaining a second reader journey."""
from django.http import HttpResponseRedirect


class UnifiedJourneyMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if request.path_info.startswith('/bn/'):
            # Preserve action tokens, query filters and POST bodies. Never cache
            # token-bearing compatibility redirects or consume actions here.
            destination='/en/'+request.path_info[4:]+('?' + request.META['QUERY_STRING'] if request.META.get('QUERY_STRING') else '')
            response=HttpResponseRedirect(destination,status=302 if request.method in ('GET','HEAD') else 307)
            response['Cache-Control']='private, no-store, max-age=0'
            response['Referrer-Policy']='strict-origin'
            return response
        return self.get_response(request)
