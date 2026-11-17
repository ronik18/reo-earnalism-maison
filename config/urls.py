from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('operations.urls')),
    path('api/v1/', include('accounts.urls')),
    path('api/v1/', include('library.urls')),
    path('api/v1/', include('reader.urls')),
    path('api/v1/', include('billing.urls')),
    path('api/v1/', include('learning.urls')),
    path('', include('web.urls')),
]
