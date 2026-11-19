"""Finance-approved immutable snapshots; no inferred tax or numbering decisions."""
import copy
import hashlib
import json
import re
from django.conf import settings
from django.utils import timezone
from core.api import DomainError


def live_snapshot(offer,territory):
    policy=getattr(settings,'MERCHANT_FINANCE_POLICY',None)
    def unavailable():raise DomainError('finance_policy_required','Approved issuer, tax and invoice-numbering policy is required for this live offer.',409)
    if not isinstance(policy,dict) or policy.get('approved') is not True:unavailable()
    issuer=policy.get('issuer');numbering=policy.get('numbering');taxes=policy.get('offer_tax')
    if (not isinstance(policy.get('version'),str) or not policy['version'].strip() or not isinstance(issuer,dict)
        or any(not isinstance(issuer.get(key),str) or not issuer[key].strip() for key in ['legal_name','address','country'])
        or not isinstance(numbering,dict) or numbering.get('scheme') not in ['prefix_uuid','fy_sequence']
        or not isinstance(numbering.get('prefix'),str) or not re.fullmatch(r'[A-Z0-9-]{1,40}',numbering['prefix'])
        or not isinstance(taxes,dict)):unavailable()
    tax=taxes.get(str(offer.id))
    # A per-offer reviewed inclusive price supplies exact amounts; no speculative
    # rate, customer tax location, exemption, exchange rate or rounding is assumed.
    if (not isinstance(tax,dict) or tax.get('offer_version')!=offer.version or tax.get('territory')!=territory
        or tax.get('currency')!=offer.currency or tax.get('price_minor')!=offer.price_minor
        or tax.get('basis')!='inclusive' or type(tax.get('tax_minor')) is not int
        or not 0<=tax['tax_minor']<=offer.price_minor or not isinstance(tax.get('evidence_ref'),str)
        or not tax['evidence_ref'].strip() or not isinstance(tax.get('label'),str) or not tax['label'].strip()):unavailable()
    components=tax.get('components')
    if components is not None:
        if not isinstance(components,list) or any(not isinstance(item,dict) or not isinstance(item.get('label'),str) or not item['label'].strip() or type(item.get('tax_minor')) is not int or item['tax_minor']<0 or ('rate_bps' in item and (type(item['rate_bps']) is not int or not 0<=item['rate_bps']<=10000)) for item in components) or sum(item['tax_minor'] for item in components)!=tax['tax_minor']:unavailable()
    snapshot={'version':policy['version'],'issuer':copy.deepcopy(issuer),'numbering':copy.deepcopy(numbering),
        'tax':copy.deepcopy(tax),'net_minor':offer.price_minor-tax['tax_minor'],'tax_minor':tax['tax_minor'],
        'total_minor':offer.price_minor,'currency':offer.currency}
    from .numbering import parameters
    parameters(snapshot,'invoice')
    snapshot['sha256']=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return snapshot


def invoice_snapshot(order,at=None):
    snapshot=order.offer_snapshot.get('finance')
    if not isinstance(snapshot,dict):raise DomainError('finance_policy_required','Live order has no retained approved finance snapshot.',409)
    original={key:value for key,value in snapshot.items() if key!='sha256'}
    digest=hashlib.sha256(json.dumps(original,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if (snapshot.get('sha256')!=digest or snapshot.get('total_minor')!=order.total_minor or snapshot.get('currency')!=order.currency
        or type(snapshot.get('net_minor')) is not int or type(snapshot.get('tax_minor')) is not int
        or snapshot['net_minor']+snapshot['tax_minor']!=order.total_minor):
        raise DomainError('finance_policy_required','Live order finance snapshot is inconsistent.',409)
    from .numbering import forecast
    number,_=forecast(snapshot,'invoice',order.id,at)
    return {'order_id':str(order.id),'amount_minor':order.total_minor,'currency':order.currency,'issued_at':(at or timezone.now()).isoformat(),'recipient':{'member_id':str(order.user.public_id),'email':order.user.email,'name':order.user.display_name},
        'local_test_document':False,'sandbox':False,'finance':snapshot},number
