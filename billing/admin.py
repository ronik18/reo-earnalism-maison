from django.contrib import admin
from .models import Offer,Order,Payment,PaymentEvent,Refund,Entitlement,Invoice,PaymentAllocation,LegacyLiability

@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display=('code','version','name','approved','active','test_only')
    def get_readonly_fields(self,request,obj=None):
        if obj and Order.objects.filter(offer=obj).exists():
            return ('code','version','currency','price_minor','duration_seconds','edition','track','formats','terms_version','kind')
        return ()

class FinancialHistoryAdmin(admin.ModelAdmin):
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False

for model in (Order,Payment,PaymentEvent,Refund,Entitlement,Invoice,PaymentAllocation,LegacyLiability):
    admin.site.register(model,FinancialHistoryAdmin)
