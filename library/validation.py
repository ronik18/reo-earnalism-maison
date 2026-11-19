"""Validate inputs against the reviewed, root-owned JSON OpenAPI artifact."""
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker
from core.api import DomainError,json_body

# jsonschema's RFC3339 checker is an optional extra. Register this product's
# timezone-required representation explicitly instead of silently ignoring it.
FORMATS=FormatChecker()
_RFC3339=re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


@FORMATS.checks('date-time')
def valid_datetime(value):
    if not isinstance(value,str):return True
    if not _RFC3339.fullmatch(value):return False
    try:
        parsed=datetime.fromisoformat(value.replace('t','T').replace('z','Z').replace('Z','+00:00'))
        return parsed.utcoffset() is not None
    except (ValueError,OverflowError):return False


@lru_cache(maxsize=1)
def contract():
    path=Path(settings.BASE_DIR)/'contracts'/'openapi.yaml'
    if not path.exists():
        path=Path(settings.BASE_DIR).parent/'docs/product/project-maison-2026-11-16/implementation/openapi.yaml'
    return json.loads(path.read_text())

def validate_schema(data,name):
    spec=contract()
    validator=Draft202012Validator({**spec,'$ref':f'#/components/schemas/{name}'},format_checker=FORMATS)
    errors=sorted(validator.iter_errors(data),key=lambda e:str(list(e.path)))
    if errors:
        err=errors[0]
        raise DomainError('validation_error','Invalid '+name+' input.',422,{'field':'.'.join(map(str,err.path)),'reason':err.message[:300]})
    return data

def body(request,name):
    return validate_schema(json_body(request),name)
