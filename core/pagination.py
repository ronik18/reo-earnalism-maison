"""Signed account-scoped descending timestamp/UUID keyset pages."""
from django.core import signing
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from .api import DomainError,public_uuid


def keyset_page(rows,params,scope,time_field,serialize):
    try:limit=int(params.get('limit','20'))
    except (ValueError,TypeError):raise DomainError('validation_error','limit must be1–100.',422)
    if not 1<=limit<=100:raise DomainError('validation_error','limit must be1–100.',422)
    cursor=params.get('cursor');query={str(k):str(v) for k,v in params.items() if k!='cursor'}
    if cursor:
        try:
            if len(cursor)>1024:raise ValueError()
            position=signing.loads(cursor,salt='maison-private-keyset',max_age=3600)
            if position['scope']!=scope or position['query']!=query:raise ValueError()
            stamp=parse_datetime(position['at'])
            if not stamp or timezone.is_naive(stamp):raise ValueError()
            identifier=public_uuid(position['id'])
        except (signing.BadSignature,ValueError,TypeError,KeyError,DomainError):
            raise DomainError('invalid_cursor','Invalid or expired page cursor.',400)
        rows=rows.filter(Q(**{time_field+'__lt':stamp})|Q(**{time_field:stamp,'pk__lt':identifier}))
    selected=list(rows.order_by('-'+time_field,'-pk')[:limit+1]);more=len(selected)>limit;selected=selected[:limit]
    next_cursor=None
    if more:
        last=selected[-1]
        next_cursor=signing.dumps({'scope':scope,'query':query,'at':getattr(last,time_field).isoformat(),'id':str(last.pk)},salt='maison-private-keyset',compress=True)
    return {'items':[serialize(row) for row in selected],'next_cursor':next_cursor,'has_more':more}
