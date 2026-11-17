from django.urls import path
from . import views
urlpatterns=[path('commerce/offers',views.offers),path('commerce/orders',views.orders),path('commerce/orders/<uuid:order_id>',views.order),
 path('commerce/orders/<uuid:order_id>/verify',views.disabled),path('me/entitlements',views.entitlements),
 path('commerce/refunds',views.refunds),path('commerce/refunds/<uuid:refund_id>',views.refund),path('staff/refunds/<uuid:refund_id>/approve',views.approve),
 path('commerce/plans',views.disabled),path('commerce/subscriptions',views.disabled),path('commerce/mandates',views.disabled),path('commerce/invoices',views.invoices),path('webhooks/razorpay',views.webhook)]
