"""Razorpay server adapter. No SDK retry of ambiguous financial mutations."""
import base64
import hashlib
import http.client
import json
import re
import ssl
import time
from urllib.parse import urlencode
from django.conf import settings
from core.api import DomainError


def enabled():return bool(getattr(settings,'RAZORPAY_ENABLED',False))


def configuration():
    mode=getattr(settings,'RAZORPAY_MODE','test');key=getattr(settings,'RAZORPAY_KEY_ID','');secret=getattr(settings,'RAZORPAY_KEY_SECRET','')
    if (not enabled() or mode not in {'test','live'} or not key.startswith('rzp_'+mode+'_') or not secret
        or not getattr(settings,'MERCHANT_ENTITY_CONFIG_VERSION','')):
        raise DomainError('provider_not_enabled','Merchant configuration is incomplete.',503)
    if mode=='live' and not getattr(settings,'RAZORPAY_LIVE_APPROVED',False):
        raise DomainError('provider_not_enabled','Live merchant activation is not approved.',503)
    return mode,key,secret


def provider_id(value,prefix):
    if not isinstance(value,str) or not re.fullmatch(re.escape(prefix)+r'_[A-Za-z0-9]{1,110}',value):
        raise DomainError('invalid_provider_identity','Provider identity is invalid.',422)
    return value


class RazorpayClient:
    def __init__(self):self.mode,self.key_id,self.secret=configuration()
    def request(self,method,path,payload=None):
        if method not in {'GET','POST'} or not path.startswith('/') or '\n' in path or '\r' in path:
            raise DomainError('invalid_provider_request','Invalid provider operation.',422)
        raw=json.dumps(payload,separators=(',',':')).encode() if payload is not None else None
        headers={'Authorization':'Basic '+base64.b64encode((self.key_id+':'+self.secret).encode()).decode(),'Accept':'application/json','Content-Type':'application/json'}
        deadline=time.monotonic()+8;connection=http.client.HTTPSConnection('api.razorpay.com',timeout=3,context=ssl.create_default_context())
        try:
            connection.request(method,'/v1'+path,body=raw,headers=headers)
            if connection.sock:connection.sock.settimeout(max(.1,deadline-time.monotonic()))
            response=connection.getresponse();parts=[];size=0
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError()
                if connection.sock:connection.sock.settimeout(remaining)
                block=response.read(65536)
                if not block:break
                size+=len(block)
                if size>1048576:raise ValueError('provider response too large')
                parts.append(block)
            if not 200<=response.status<300:
                raise DomainError('provider_request_failed','Merchant request was not accepted; reconcile before retrying mutations.',503 if response.status>=500 or response.status==429 else 422)
            data=json.loads(b''.join(parts))
            if not isinstance(data,dict):raise ValueError('not an object')
            return data
        except DomainError:raise
        except (OSError,TimeoutError,http.client.HTTPException,ValueError) as exc:
            raise DomainError('provider_outcome_unknown','Merchant outcome is unknown; reconciliation is pending.',503) from exc
        finally:connection.close()
    def create_order(self,order):
        return self.request('POST','/orders',{'amount':order.total_minor,'currency':order.currency,'receipt':str(order.id),
            'partial_payment':False,'notes':{'maison_order_id':str(order.id),'merchant_config':order.offer_snapshot['merchant_config']}})
    def find_order(self,order):
        # Receipt is not assumed to be a provider-global idempotency guarantee.
        # Only complete bounded search results may supply a matching provider order; absence never retries POST.
        params={'count':100,'from':max(0,int(order.created_at.timestamp())-60)}
        found=[]
        for skip in range(0,500,100):
            data=self.request('GET','/orders?'+urlencode({**params,'skip':skip}));items=data.get('items')
            if not isinstance(items,list):raise DomainError('provider_response_invalid','Merchant order collection is invalid.',503)
            found.extend(row for row in items if row.get('receipt')==str(order.id) and isinstance(row.get('notes'),dict) and row['notes'].get('maison_order_id')==str(order.id))
            if len(items)<100:break
        else:raise DomainError('provider_search_incomplete','Merchant search exceeded its safe bound; reconciliation requires review.',503)
        if len(found)>1:raise DomainError('provider_identity_ambiguous','Multiple merchant orders require review.',409)
        return found[0] if found else None
    def fetch_subscription(self,subscription_id):return self.request('GET','/subscriptions/'+provider_id(subscription_id,'sub'))
    def cancel_subscription(self,subscription_id):return self.request('POST','/subscriptions/'+provider_id(subscription_id,'sub')+'/cancel',{'cancel_at_cycle_end':True})
    def fetch_payment(self,payment_id):return self.request('GET','/payments/'+provider_id(payment_id,'pay'))
    def order_payments(self,order_id):return self.request('GET','/orders/'+provider_id(order_id,'order')+'/payments')
    def create_refund(self,refund):
        return self.request('POST','/payments/'+provider_id(refund.payment.provider_payment_id,'pay')+'/refund',{
            'amount':refund.amount_minor,'speed':'normal','receipt':str(refund.id),'notes':{'maison_refund_id':str(refund.id)}})
    def fetch_refund(self,refund_id):return self.request('GET','/refunds/'+provider_id(refund_id,'rfnd'))
    def find_refund(self,refund):
        payment=provider_id(refund.payment.provider_payment_id,'pay');found=[]
        for skip in range(0,500,100):
            data=self.request('GET',f'/payments/{payment}/refunds?'+urlencode({'count':100,'skip':skip}));items=data.get('items')
            if not isinstance(items,list):raise DomainError('provider_response_invalid','Merchant refund collection is invalid.',503)
            found.extend(row for row in items if row.get('receipt')==str(refund.id) and isinstance(row.get('notes'),dict) and row['notes'].get('maison_refund_id')==str(refund.id))
            if len(items)<100:break
        else:raise DomainError('provider_search_incomplete','Merchant search exceeded its safe bound; reconciliation requires review.',503)
        if len(found)>1:raise DomainError('provider_identity_ambiguous','Multiple merchant refunds require review.',409)
        return found[0] if found else None


def evidence_hash(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
