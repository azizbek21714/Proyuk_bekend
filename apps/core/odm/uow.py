"""Unit of work: `atomic()` replaces django.db.transaction.atomic.

Inside an atomic block writes are buffered and sent to the store in ONE commit when the
outermost block exits without an exception (nothing is written if it raises). Reads made
inside the block see the buffered writes. Nested blocks flatten into the outer one.
Outside any block every write commits immediately.
"""
import contextvars
from functools import wraps

from apps.core.store import Create, Delete, Set, Update, get_store
from apps.core.store.base import apply_update

from . import cache

_current = contextvars.ContextVar('odm_uow', default=None)


class UnitOfWork:
    def __init__(self):
        self.ops = []
        self.depth = 0

    def add(self, ops):
        self.ops.extend(ops)

    def overlay(self, coll, docs):
        """Apply pending ops for `coll` on top of {id: doc} (returns a new dict)."""
        relevant = [op for op in self.ops if op.coll == coll]
        if not relevant:
            return docs
        out = dict(docs)
        for op in relevant:
            if isinstance(op, (Create, Set)):
                out[op.id] = op.data
            elif isinstance(op, Update):
                if op.id in out:
                    doc = dict(out[op.id])
                    apply_update(doc, op)
                    out[op.id] = doc
            elif isinstance(op, Delete):
                out.pop(op.id, None)
        return out

    def pending_doc(self, coll, id, base):
        return self.overlay(coll, {id: base} if base is not None else {}).get(id)


def current():
    return _current.get()


def write(ops):
    """Send ops to the current unit of work, or commit them right away."""
    if not ops:
        return
    uow = _current.get()
    if uow is not None:
        uow.add(ops)
    else:
        _commit(ops)


def _commit(ops):
    try:
        get_store().commit(ops)
    finally:
        cache.invalidate({op.coll for op in ops})


class atomic:
    """Usable as `with atomic():` or as a decorator `@atomic`."""

    def __init__(self, func=None):
        self.func = func
        if func is not None:
            wraps(func)(self)

    def __call__(self, *args, **kwargs):
        with atomic():
            return self.func(*args, **kwargs)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return lambda *a, **kw: self(obj, *a, **kw)

    def __enter__(self):
        uow = _current.get()
        if uow is None:
            uow = UnitOfWork()
            self._token = _current.set(uow)
        else:
            self._token = None
        self._mark = len(uow.ops)   # savepoint: a failing nested block drops only its own ops
        uow.depth += 1
        return uow

    def __exit__(self, exc_type, exc, tb):
        uow = _current.get()
        uow.depth -= 1
        if self._token is None:
            if exc_type is not None:
                del uow.ops[self._mark:]
            return False          # nested: the outer block decides
        _current.reset(self._token)
        if exc_type is None:
            _commit(uow.ops)
        return False
