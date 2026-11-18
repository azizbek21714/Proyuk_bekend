"""Versioned collection cache.

Every commit bumps a per-collection version counter in the store (one small document).
At the start of a request we read those versions once; a collection is re-read from the
store only if its version changed since this process last loaded it. Repeated requests
(e.g. the frontend paging through /fanlar/) then cost ONE read instead of one read per
document — important for Firestore's read quota — while every worker still sees the
latest data on each request.

Cached documents are shared and must be treated as read-only.
"""
import contextvars
import threading

_lock = threading.Lock()
_process = {}   # (store id, coll) -> {'v': version, 'docs': {id: doc}}
_request_versions = contextvars.ContextVar('odm_versions', default=None)


def clear_cache():
    """Forget everything (tests, store overrides)."""
    with _lock:
        _process.clear()
    _request_versions.set(None)


def begin_request():
    _request_versions.set(None)


def end_request():
    _request_versions.set(None)


def invalidate(colls):
    """Called after our own commit: re-read versions on next access."""
    _request_versions.set(None)


def _versions(store):
    versions = _request_versions.get()
    if versions is None:
        versions = store.versions()
        _request_versions.set(versions)
    return versions


def get_all(store, coll):
    """All raw docs of a collection as {id: doc}."""
    version = _versions(store).get(coll, 0)
    key = (id(store), coll)
    entry = _process.get(key)
    if entry is not None and entry['v'] == version:
        return entry['docs']
    docs = {doc['id']: doc for doc in store.query(coll)}
    with _lock:
        _process[key] = {'v': version, 'docs': docs}
    return docs


def get_one(store, coll, id):
    return get_all(store, coll).get(id)
