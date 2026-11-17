from django.urls import path
from . import views
urlpatterns=[
 path('session',views.session_view),path('auth/register',views.register_view),path('auth/login',views.login_view),
 path('auth/<str:purpose>/request',views.request_action),path('auth/<str:purpose>/confirm',views.consume_action),
 path('auth/email-links/consume',views.consume_action,{'purpose':'email-links'}),
 path('auth/google',views.provider_disabled),path('auth/google/callback',views.provider_disabled),
 path('auth/phone-challenges',views.provider_disabled),path('auth/phone-challenges/<uuid:challenge_id>/verify',views.provider_disabled),
 path('me/profile',views.profile),path('me/preferences',views.preferences),path('me/consents',views.consents),
 path('me/password',views.change_password),path('me/reauthenticate',views.reauthenticate),
 path('me/devices',views.devices),path('me/devices/<uuid:device_id>',views.revoke_device),
 path('me/privacy/requests',views.privacy_requests),path('me/privacy/requests/<uuid:privacy_request_id>',views.privacy_request),
 path('me/privacy/requests/<uuid:privacy_request_id>/cancel',views.privacy_cancel),path('me/privacy/requests/<uuid:privacy_request_id>/download',views.privacy_download),
 path('me/privacy/requests/<uuid:privacy_request_id>/file',views.privacy_file),path('contact',views.contact),
]
