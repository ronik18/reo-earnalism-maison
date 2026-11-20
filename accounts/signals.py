from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .services import bind_device


@receiver(user_logged_in,dispatch_uid='maison-bind-device')
def on_login(sender,request,user,**kwargs):
    bind_device(request,user)
    evidence=getattr(request,'_maison_admin_password_consent',None)
    if evidence is not None:
        from .password_consent import record_password_purpose_consent
        record_password_purpose_consent(user,'admin_sign_in',evidence)
        del request._maison_admin_password_consent


from django.apps import apps
if apps.is_installed('allauth.account'):
    from django.db.models.signals import post_save,post_delete
    from allauth.account.models import EmailAddress
    from .models import User

    @receiver(post_save,sender=EmailAddress,dispatch_uid='maison-email-authority-cache')
    def sync_verified_address(sender,instance,**kwargs):
        User.objects.filter(pk=instance.user_id,email__iexact=instance.email).update(is_verified=instance.verified)

    @receiver(post_delete,sender=EmailAddress,dispatch_uid='maison-email-authority-delete')
    def clear_verified_address(sender,instance,**kwargs):
        User.objects.filter(pk=instance.user_id,email__iexact=instance.email).update(is_verified=False)
