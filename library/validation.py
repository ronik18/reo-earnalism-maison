"""Validate inputs against the reviewed, root-owned JSON OpenAPI artifact."""
import json
from functools import lru_cache
from pathlib import Path
from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker
from core.api import DomainError,json_body

@lru_cache(maxsize=1)
def contract():
    path=Path(settings.BASE_DIR)/'contracts'/'openapi.yaml'
    if not path.exists():
        path=Path(settings.BASE_DIR).parent/'docs/product/project-maison-2026-11-16/implementation/openapi.yaml'
    return json.loads(path.read_text())

def validate_schema(data,name):
    spec=contract()
    validator=Draft202012Validator({**spec,'$ref':f'#/components/schemas/{name}'},format_checker=FormatChecker())
    errors=sorted(validator.iter_errors(data),key=lambda e:str(list(e.path)))
    if errors:
        err=errors[0]
        raise DomainError('validation_error','Invalid '+name+' input.',422,{'field':'.'.join(map(str,err.path)),'reason':err.message[:300]})
    return data

def body(request,name):
    return validate_schema(json_body(request),name)
