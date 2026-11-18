"""Isolated URL configuration for actual Django error-handler regression tests."""
from django.core.exceptions import PermissionDenied
from django.urls import include,path


def denied(request,locale):
    raise PermissionDenied


def failed(request,locale):
    raise RuntimeError('Synthetic frontend error-handler fixture')


urlpatterns=[path('<str:locale>/test-denied/',denied),path('<str:locale>/test-failed/',failed),path('',include('web.urls'))]
handler404='web.views.not_found'
handler403='web.views.permission_denied'
handler500='web.views.server_error'
