"""In-memory store (tests) and a JSON-file-backed variant (local development)."""
import copy
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from django.db import IntegrityError

from .base import Create, Delete, Set, Store, Update, apply_update


class MemoryStore(Store):
    def __init__(self):
        self._data = {}        # coll -> {id: doc}
        self._counters = {}    # coll -> next id
        self._versions = {}    # coll -> version
        self._lock = threading.RLock()

    def get(self, coll, id):
        with self._lock:
            doc = self._data.get(coll, {}).get(id)
            return copy.deepcopy(doc) if doc is not None else None

    def query(self, coll, where=None):
        with self._lock:
            docs = list(self._data.get(coll, {}).values())
            if where is not None:
                name, op, value = where
                if op == '==':
                    docs = [d for d in docs if d.get(name) == value]
                elif op == 'array_contains':
                    docs = [d for d in docs if value in (d.get(name) or [])]
                else:
                    raise ValueError(f'Unsupported operator {op}')
            return copy.deepcopy(docs)

    def allocate_ids(self, coll, n=1):
        with self._lock:
            start = self._counters.get(coll, 1)
            self._counters[coll] = start + n
            self._after_write()
            return list(range(start, start + n))

    def bump_counter(self, coll, floor):
        with self._lock:
            self._counters[coll] = max(self._counters.get(coll, 1), int(floor) + 1)
            self._after_write()

    def commit(self, ops):
        if not ops:
            return
        with self._lock:
            for op in ops:
                if isinstance(op, Create) and op.id in self._data.get(op.coll, {}):
                    raise IntegrityError(f'Document {op.coll}/{op.id} already exists')
            for op in ops:
                coll = self._data.setdefault(op.coll, {})
                if isinstance(op, (Create, Set)):
                    coll[op.id] = copy.deepcopy(op.data)
                elif isinstance(op, Update):
                    if op.id in coll:
                        apply_update(coll[op.id], op)
                elif isinstance(op, Delete):
                    coll.pop(op.id, None)
            for name in {op.coll for op in ops}:
                self._versions[name] = self._versions.get(name, 0) + 1
            self._after_write()

    def versions(self):
        with self._lock:
            return dict(self._versions)

    def collections(self):
        with self._lock:
            return [c for c, docs in self._data.items() if docs]

    def drop_all(self):
        with self._lock:
            for name in self._data:
                self._versions[name] = self._versions.get(name, 0) + 1
            self._data.clear()
            self._counters.clear()
            self._after_write()

    def snapshot(self):
        with self._lock:
            return copy.deepcopy((self._data, self._counters))

    def restore(self, snap):
        with self._lock:
            self._data, self._counters = copy.deepcopy(snap)
            for name in set(self._data) | set(self._versions):
                self._versions[name] = self._versions.get(name, 0) + 1

    def _after_write(self):
        pass


def _encode(value):
    if isinstance(value, datetime):
        return {'$dt': value.isoformat()}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_encode(v) for v in value]
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {'$dt'}:
            return datetime.fromisoformat(value['$dt'])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


class JsonFileStore(MemoryStore):
    """MemoryStore persisted to a JSON file — for local development without Firestore."""

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self._mtime = None
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding='utf-8'))
        self._counters = raw.get('counters', {})
        versions = raw.get('versions', {})
        # Versions only grow, so the process cache never serves data older than the file.
        for name in set(versions) | set(self._versions):
            versions[name] = max(versions.get(name, 0), self._versions.get(name, 0) + 1)
        self._versions = versions
        self._data = {
            coll: {self._key(k): _decode(doc) for k, doc in docs.items()}
            for coll, docs in raw.get('data', {}).items()
        }
        self._mtime = self.path.stat().st_mtime_ns

    def _sync(self):
        """Reload when another process (a manage.py command) changed the file."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            return
        if mtime != self._mtime:
            with self._lock:
                self._load()

    def get(self, coll, id):
        self._sync()
        return super().get(coll, id)

    def query(self, coll, where=None):
        self._sync()
        return super().query(coll, where)

    def allocate_ids(self, coll, n=1):
        self._sync()
        return super().allocate_ids(coll, n)

    def bump_counter(self, coll, floor):
        self._sync()
        return super().bump_counter(coll, floor)

    def commit(self, ops):
        self._sync()
        return super().commit(ops)

    def versions(self):
        self._sync()
        return super().versions()

    @staticmethod
    def _key(k):
        return int(k) if k.lstrip('-').isdigit() else k

    def _after_write(self):
        raw = {
            'counters': self._counters,
            'versions': self._versions,
            'data': {coll: {str(k): _encode(doc) for k, doc in docs.items()} for coll, docs in self._data.items()},
        }
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime_ns
