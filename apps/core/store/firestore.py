"""Google Cloud Firestore (Native mode) implementation of the Store interface.

Configuration (environment):
    FIREBASE_CREDENTIALS  service-account JSON (raw JSON text or base64 of it)
    FIREBASE_PROJECT_ID   optional; defaults to the project in the credentials
    FIRESTORE_DATABASE    optional database id, default "(default)"

Document id = str(id); the original id (int or str) is also kept in the "id" field.
Counters live in _counters/{collection} with a "next" field and are advanced in a
transaction, so ids are never reused.
"""
import base64
import json
import os
import threading
from datetime import datetime, timezone

from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError

from .base import Create, Delete, Set, Store, Update

COUNTERS = '_counters'
META = '_meta'          # _meta/versions: {collection: version}
MAX_BATCH = 500  # Firestore limit for writes in one atomic commit


def _credentials_info():
    raw = (os.environ.get('FIREBASE_CREDENTIALS') or '').strip()
    if not raw:
        raise ImproperlyConfigured('FIREBASE_CREDENTIALS muhit o\'zgaruvchisi berilmagan.')
    if not raw.startswith('{'):
        raw = base64.b64decode(raw).decode('utf-8')
    return json.loads(raw)


def _plain(value):
    """Firestore returns DatetimeWithNanoseconds; give callers plain aware datetimes."""
    if isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second,
                        value.microsecond, tzinfo=timezone.utc)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class FirestoreStore(Store):
    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

    @property
    def client(self):
        # Created lazily (after gunicorn forks), never at import time.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    from google.cloud import firestore
                    from google.oauth2 import service_account
                    info = _credentials_info()
                    creds = service_account.Credentials.from_service_account_info(info)
                    self._client = firestore.Client(
                        project=os.environ.get('FIREBASE_PROJECT_ID') or info.get('project_id'),
                        credentials=creds,
                        database=os.environ.get('FIRESTORE_DATABASE') or '(default)',
                    )
        return self._client

    def _ref(self, coll, id):
        return self.client.collection(coll).document(str(id))

    def get(self, coll, id):
        snap = self._ref(coll, id).get()
        return _plain(snap.to_dict()) if snap.exists else None

    def get_many(self, coll, ids):
        ids = list(ids)
        if not ids:
            return {}
        out = {}
        by_str = {str(i): i for i in ids}
        for snap in self.client.get_all([self._ref(coll, i) for i in ids]):
            if snap.exists:
                out[by_str[snap.id]] = _plain(snap.to_dict())
        return out

    def query(self, coll, where=None):
        from google.cloud.firestore_v1.base_query import FieldFilter
        ref = self.client.collection(coll)
        if where is not None:
            ref = ref.where(filter=FieldFilter(*where))
        return [_plain(snap.to_dict()) for snap in ref.stream()]

    def allocate_ids(self, coll, n=1):
        from google.cloud import firestore
        counter = self.client.collection(COUNTERS).document(coll)

        @firestore.transactional
        def take(transaction):
            snap = counter.get(transaction=transaction)
            start = (snap.to_dict() or {}).get('next', 1) if snap.exists else 1
            transaction.set(counter, {'next': start + n})
            return start

        start = take(self.client.transaction())
        return list(range(start, start + n))

    def bump_counter(self, coll, floor):
        from google.cloud import firestore
        counter = self.client.collection(COUNTERS).document(coll)

        @firestore.transactional
        def bump(transaction):
            snap = counter.get(transaction=transaction)
            current = (snap.to_dict() or {}).get('next', 1) if snap.exists else 1
            transaction.set(counter, {'next': max(current, int(floor) + 1)})

        bump(self.client.transaction())

    def commit(self, ops):
        from google.api_core import exceptions as gexc
        from google.cloud import firestore
        if not ops:
            return
        # Firestore allows 500 writes per atomic commit. Larger units (rare: e.g. a
        # cascade over hundreds of rows) are split; each chunk is still atomic.
        version_ref = self.client.collection(META).document('versions')
        chunk = MAX_BATCH - 1  # one write per batch is the version bump
        for start in range(0, len(ops), chunk):
            part = ops[start:start + chunk]
            batch = self.client.batch()
            batch.set(version_ref, {name: firestore.Increment(1) for name in {op.coll for op in part}}, merge=True)
            for op in part:
                ref = self._ref(op.coll, op.id)
                if isinstance(op, Create):
                    batch.create(ref, op.data)
                elif isinstance(op, Set):
                    batch.set(ref, op.data)
                elif isinstance(op, Update):
                    fields = dict(op.fields)
                    for name, values in op.array_remove.items():
                        fields[name] = firestore.ArrayRemove(list(values))
                    if fields:
                        # The ODM only updates documents it has just read, so they exist.
                        batch.update(ref, fields)
                elif isinstance(op, Delete):
                    batch.delete(ref)
            try:
                batch.commit()
            except (gexc.AlreadyExists, gexc.Conflict) as exc:
                raise IntegrityError(str(exc)) from exc

    def versions(self):
        snap = self.client.collection(META).document('versions').get()
        return snap.to_dict() or {} if snap.exists else {}

    def collections(self):
        return [c.id for c in self.client.collections()]

    def drop_all(self):
        for coll in self.client.collections():
            while True:
                docs = list(coll.limit(MAX_BATCH).stream())
                if not docs:
                    break
                batch = self.client.batch()
                for doc in docs:
                    batch.delete(doc.reference)
                batch.commit()
