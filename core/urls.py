from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import TokenRefreshView
from attendance.views import LoggingTokenObtainPairView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/training/', include('training.urls')),
    path('api/attendance/', include('attendance.urls')),
    path('api/token/', LoggingTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)