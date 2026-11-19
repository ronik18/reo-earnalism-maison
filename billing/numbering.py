"""Explicit finance-approved numbering; no inferred GST registration or year."""
import hashlib
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from core.api import DomainError
from .invoice_models import FinanceNumberSequence


def parameters(finance,kind,at=None):
    rule=finance.get('numbering',{});prefix=rule.get('credit_note_prefix' if kind=='credit_note' else 'prefix')
    import re
    if not isinstance(prefix,str) or not re.fullmatch('[A-Z0-9-]{1,12}',prefix):raise DomainError('finance_policy_required','Approved legal numbering prefix is required.',409)
    if rule.get('scheme')=='prefix_uuid':
        if rule.get('applicability')!='reviewed_non_gst' or not isinstance(rule.get('evidence_ref'),str) or not rule['evidence_ref'].strip():raise DomainError('finance_policy_required','UUID legal numbering requires an explicit reviewed non-GST applicability decision.',409)
        return rule,prefix,None
    month=rule.get('fiscal_year_start_month');width=rule.get('width')
    if rule.get('scheme')!='fy_sequence' or type(month)!=int or not 1<=month<=12 or type(width)!=int or not 1<=width<=10:raise DomainError('finance_policy_required','Approved fiscal-year sequence configuration is required.',409)
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    try:zone=ZoneInfo(rule['time_zone'])
    except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):raise DomainError('finance_policy_required','Approved fiscal-year time zone is required.',409)
    at=(at or timezone.now()).astimezone(zone);year=at.year-(at.month<month);fy=f'{year%100:02d}{(year+1)%100:02d}'
    if len(prefix)+len(fy)+width>16:raise DomainError('finance_policy_required','Configured legal serial exceeds16 characters.',409)
    version=rule.get('version',finance.get('version'))
    if not isinstance(version,str) or not version.strip() or len(version)>120:raise DomainError('finance_policy_required','Approved numbering version is required.',409)
    issuer=finance.get('issuer',{});identity=hashlib.sha256(str((issuer.get('legal_name'),issuer.get('country'),issuer.get('tax_id'))).encode()).hexdigest()
    return rule,prefix,{'issuer_key':identity,'policy_version':version,'kind':kind,'fiscal_year':fy}


def legacy_floor(scope):
    # Earlier counters did not retain their visible prefix. Keep those rows as
    # history and continue above their high-water mark rather than guessing a
    # prefix or restarting a possibly already-issued legal series.
    return FinanceNumberSequence.objects.filter(**scope,series_prefix__isnull=True).aggregate(n=Max('next_number'))['n'] or 1


def forecast(finance,kind,source_id,at=None):
    rule,prefix,key=parameters(finance,kind,at)
    if key is None:return prefix+'-'+str(source_id),None
    scope={name:key[name] for name in ('issuer_key','kind','fiscal_year')}
    row=FinanceNumberSequence.objects.filter(**scope,series_prefix=prefix).first()
    value=max(row.next_number if row else 1,legacy_floor(scope))
    if value>=10**rule['width']:raise DomainError('finance_policy_required','Approved legal serial range is exhausted.',409)
    return prefix+key['fiscal_year']+str(value).zfill(rule['width']),value


@transaction.atomic
def reserve(finance,kind,source_id,at=None,expected=None):
    rule,prefix,key=parameters(finance,kind,at)
    if key is None:return prefix+'-'+str(source_id)
    scope={name:key[name] for name in ('issuer_key','kind','fiscal_year')}
    row,_=FinanceNumberSequence.objects.select_for_update().get_or_create(
        **scope,series_prefix=prefix,defaults={'policy_version':key['policy_version'],'next_number':legacy_floor(scope)})
    value=max(row.next_number,legacy_floor(scope))
    if expected is not None and value!=expected:raise DomainError('version_conflict','Document numbering changed; retry with a fresh operation.',412)
    if value>=10**rule['width']:raise DomainError('finance_policy_required','Approved legal serial range is exhausted.',409)
    number=prefix+key['fiscal_year']+str(value).zfill(rule['width'])
    row.next_number=value+1;row.save(update_fields=['next_number']);return number
