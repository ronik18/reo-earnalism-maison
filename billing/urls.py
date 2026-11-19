from django.urls import path
from . import views,invoices,subscriptions,documents
urlpatterns=[path('commerce/offers',views.offers),path('commerce/orders',views.orders),path('commerce/orders/<uuid:order_id>',views.order),
 path('commerce/orders/<uuid:order_id>/verify',views.verify_payment),path('me/entitlements',views.entitlements),
 path('commerce/refunds',views.refunds),path('commerce/refunds/<uuid:refund_id>',views.refund),path('staff/refunds/<uuid:refund_id>/approve',views.approve),
 path('commerce/plans',views.disabled),path('commerce/subscriptions',subscriptions.subscriptions),path('commerce/mandates',subscriptions.mandates),path('commerce/invoices',invoices.list_invoices),path('webhooks/razorpay',views.webhook)]

urlpatterns += [
 path('staff/mandates/<uuid:mandate_id>/provider-identity',subscriptions.provider_identity),
 path('staff/refunds/<uuid:refund_id>/reject',views.reject),
 path('staff/orders/<uuid:order_id>/reconcile',views.reconcile),
 path('commerce/subscriptions/<uuid:subscription_id>',subscriptions.subscription),
 path('commerce/subscriptions/<uuid:subscription_id>/cancel',subscriptions.cancel),
 path('commerce/subscriptions/<uuid:subscription_id>/verify',subscriptions.verify),
 path('commerce/mandates/<uuid:mandate_id>',subscriptions.revoke),
 path('commerce/invoices/<uuid:invoice_id>',invoices.get_invoice),
 path('commerce/invoices/<uuid:invoice_id>/download',invoices.download_invoice),
 path('commerce/invoices/<uuid:invoice_id>/file',invoices.invoice_file),
]

urlpatterns += [
 path('commerce/credit-notes',documents.list_credit_notes),
 path('commerce/credit-notes/<uuid:credit_note_id>',documents.get_credit_note),
 path('commerce/credit-notes/<uuid:credit_note_id>/download',documents.download_credit_note),
 path('commerce/credit-notes/<uuid:credit_note_id>/file',documents.credit_note_file),
 path('staff/invoices/<uuid:invoice_id>/issue',documents.issue_invoice),
 path('staff/refunds/<uuid:refund_id>/credit-note',documents.issue_credit_note),
]
