from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .services import bind_device


@receiver(user_logged_in,dispatch_uid='maison-bind-device')
def on_login(sender,request,user,**kwargs):
    bind_device(request,user)
