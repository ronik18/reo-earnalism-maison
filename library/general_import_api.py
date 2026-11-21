"""Existing staff session/CSRF boundary for general source imports. Draft only."""
from core.api import api_response, expected_version, json_endpoint, operation_key
from .general_import import finalize_import, start_import
from .intake_api import staff_permission
from .validation import body


@json_endpoint(("POST",))
def start(request):
    staff_permission(request.user)
    data = body(request, "GeneralBookImportStartInput")
    status, result = start_import(request.user, data["manifest"], operation_key(request))
    return api_response(result, status, version=result["version"])


@json_endpoint(("POST",))
def finalize(request, edition_id):
    staff_permission(request.user)
    data = body(request, "GeneralBookImportFinalizeInput")
    status, result = finalize_import(request.user, edition_id, data, expected_version(request), operation_key(request))
    return api_response(result, status, version=result["version"])
