from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from config.dashboard_urls import teacher_urlpatterns
from config import role_urls


def health(request):
    """Render health check: server ishlayotganini bildiradi (login talab qilinmaydi)."""
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('api/health', health),

    # Rollar: hudud, rol berish, xabarlar, rol dashboardi
    path('api/auth/', include(role_urls.auth_patterns)),
    path('api/auth/', include('config.users_admin')),
    path('api/crud/', include(role_urls.crud_patterns)),
    path('api/dashboard/', include(role_urls.dashboard_patterns)),
    path('api/teacher/', include(role_urls.teacher_patterns)),
    path('api/hisobot/', include(role_urls.hisobot_patterns)),

    # Authentication
    path('api/auth/', include('config.auth_urls')),

    # CRUD endpointlar
    path('api/crud/', include('config.crud_urls')),

    # Dashboard
    path('api/dashboard/', include('config.dashboard_urls')),
    path('api/teacher/', include((teacher_urlpatterns, 'teacher'))),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
