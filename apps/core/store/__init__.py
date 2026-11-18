"""Store selection.

STORE_BACKEND = firestore | jsonfile | memory   (default: jsonfile for local development)
STORE_JSON_PATH = path of the jsonfile store    (default: <backend>/.localstore.json)
"""
import os
import threading
from contextlib import contextmanager

from .base import Create, Delete, Set, Store, Update  # noqa: F401

_lock = threading.Lock()
_store = None
_override = []


def _build():
    from django.conf import settings
    backend = getattr(settings, 'STORE_BACKEND', 'jsonfile')
    if backend == 'firestore':
        from .firestore import FirestoreStore
        return FirestoreStore()
    if backend == 'memory':
        from .memory import MemoryStore
        return MemoryStore()
    if backend == 'jsonfile':
        from .memory import JsonFileStore
        path = getattr(settings, 'STORE_JSON_PATH', None) or os.path.join(settings.BASE_DIR, '.localstore.json')
        return JsonFileStore(path)
    raise ValueError(f'Unknown STORE_BACKEND: {backend}')


def get_store():
    global _store
    if _override:
        return _override[-1]
    if _store is None:
        with _lock:
            if _store is None:
                _store = _build()
    return _store


@contextmanager
def override_store(store):
    """Use `store` for the duration of the block (tests, import commands)."""
    from apps.core.odm.cache import clear_cache
    _override.append(store)
    clear_cache()
    try:
        yield store
    finally:
        _override.pop()
        clear_cache()
