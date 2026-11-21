from django.urls import path
from . import views
urlpatterns=[
 path('session',views.session_view),path('auth/register',views.register_view),path('auth/login',views.login_view),
 path('auth/<str:purpose>/request',views.request_action),path('auth/<str:purpose>/confirm',views.consume_action),
 path('auth/email-links/consume',views.consume_action,{'purpose':'email-links'}),
 path('auth/google',views.google_start,name='google_login'),path('auth/google/callback',views.google_callback,name='google_callback'),
 path('auth/phone-challenges',views.provider_disabled),path('auth/phone-challenges/<uuid:challenge_id>/verify',views.provider_disabled),
 path('me/profile',views.profile),path('me/preferences',views.preferences),path('me/consents',views.consents),
 path('me/password',views.change_password),path('me/reauthenticate',views.reauthenticate),
 path('me/devices',views.devices),path('me/devices/<uuid:device_id>',views.revoke_device),
 path('me/privacy/requests',views.privacy_requests),path('me/privacy/requests/<uuid:privacy_request_id>',views.privacy_request),
 path('me/privacy/requests/<uuid:privacy_request_id>/cancel',views.privacy_cancel),path('me/privacy/requests/<uuid:privacy_request_id>/download',views.privacy_download),
 path('me/privacy/requests/<uuid:privacy_request_id>/file',views.privacy_file),path('contact',views.contact),
]

urlpatterns += [path("me/mfa/totp",views.mfa_totp),path("me/mfa/totp/confirm",views.mfa_confirm),path("me/mfa/verify",views.mfa_verify),path("me/mfa/recovery",views.mfa_recover)]

from . import guardian_views
urlpatterns += [
 path('me/guardian/policies',guardian_views.policies),
 path('me/guardian/authorizations',guardian_views.authorizations),
 path('me/guardian/authorizations/<uuid:authorization_id>',guardian_views.detail),
 path('me/guardian/authorizations/<uuid:authorization_id>/withdraw',guardian_views.withdraw),
 path('me/guardian/authorizations/<uuid:authorization_id>/claim-capability',guardian_views.claim_capability),
 path('me/guardian/authorizations/<uuid:authorization_id>/claim',guardian_views.claim),
 path('staff/guardian/authorizations/<uuid:authorization_id>/review',guardian_views.review),
]
urlpatterns += [
 path('me/guardian/authorizations/<uuid:authorization_id>/privacy-requests',guardian_views.privacy_requests),
 path('me/guardian/authorizations/<uuid:authorization_id>/privacy-requests/<uuid:privacy_request_id>',guardian_views.privacy_request),
 path('me/guardian/authorizations/<uuid:authorization_id>/privacy-requests/<uuid:privacy_request_id>/download',guardian_views.privacy_download),
 path('me/guardian/authorizations/<uuid:authorization_id>/privacy-requests/<uuid:privacy_request_id>/file',guardian_views.privacy_file),
]
