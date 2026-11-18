"""Storage interface used by the ODM.

Documents are plain dicts. Model collections use integer ids; internal collections
(_unique markers, token_blacklist) may use string ids. Values are store-safe: str, int,
float, bool, None, list, dict and timezone-aware datetime (encoded by the ODM fields).
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Create:
    """Insert a new document; the whole commit fails with IntegrityError if it exists."""
    coll: str
    id: Any
    data: dict


@dataclass
class Set:
    """Insert or overwrite a document."""
    coll: str
    id: Any
    data: dict


@dataclass
class Update:
    """Change some fields of an existing document (missing document: no-op)."""
    coll: str
    id: Any
    fields: dict
    array_remove: dict = field(default_factory=dict)   # field -> list of values to remove


@dataclass
class Delete:
    coll: str
    id: Any


class Store:
    """Abstract store. Implementations: MemoryStore, JsonFileStore, FirestoreStore."""

    def get(self, coll, id):
        raise NotImplementedError

    def get_many(self, coll, ids):
        return {i: doc for i in ids if (doc := self.get(coll, i)) is not None}

    def query(self, coll, where=None):
        """All documents of a collection, optionally filtered by ONE server-side clause
        where=(field, op, value) with op in {'==', 'array_contains'}."""
        raise NotImplementedError

    def allocate_ids(self, coll, n=1):
        """Reserve n consecutive integer ids (never reused)."""
        raise NotImplementedError

    def bump_counter(self, coll, floor):
        """Make sure the next allocated id is greater than `floor`."""
        raise NotImplementedError

    def commit(self, ops):
        """Apply all ops atomically. Raises django.db.IntegrityError on a Create conflict.
        Also bumps the version of every collection touched (see versions())."""
        raise NotImplementedError

    def versions(self):
        """{collection: version} — bumped on every commit that touches the collection.
        Lets processes cache whole collections and re-read only what changed."""
        raise NotImplementedError

    def collections(self):
        raise NotImplementedError

    def drop_all(self):
        """Delete every document (used by tests and import --wipe)."""
        raise NotImplementedError


def apply_update(doc, op):
    """Apply an Update op to a document dict in place (shared by in-memory stores)."""
    doc.update(op.fields)
    for name, values in op.array_remove.items():
        doc[name] = [v for v in (doc.get(name) or []) if v not in values]
