"""Per-request cache scope for the ODM (see apps/core/odm/cache.py)."""
from apps.core.odm import cache


class StoreRequestCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cache.begin_request()
        try:
            return self.get_response(request)
        finally:
            cache.end_request()
