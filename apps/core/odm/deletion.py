"""Deletion: CASCADE / SET_NULL / PROTECT and many-to-many cleanup, like Django's Collector.

All resulting writes are returned as one list of ops so the caller commits them together.
Updates come first and never touch documents that are being deleted.
"""
from django.db.models import ProtectedError

from apps.core.store import Delete, Update

from . import registry
from .fields import CASCADE, PROTECT, SET_NULL
from .model import UNIQUE
from .queryset import _docs


def collect(objs):
    to_delete = {}          # (model, pk) -> instance
    set_null = {}           # (model, pk) -> {store_name: None}
    m2m_remove = {}         # (model, pk) -> {store_name: set(ids)}
    docs_cache = {}

    def docs_of(model):
        if model not in docs_cache:
            docs_cache[model] = _docs(model)
        return docs_cache[model]

    stack = list(objs)
    while stack:
        obj = stack.pop()
        model = type(obj)
        key = (model, obj.pk)
        if key in to_delete:
            continue
        to_delete[key] = obj
        for src, field in registry.relations_to(model):
            if field.many_to_many:
                for doc in docs_of(src).values():
                    if obj.pk in (doc.get(field.store_name) or []):
                        m2m_remove.setdefault((src, doc['id']), {}).setdefault(field.store_name, set()).add(obj.pk)
                continue
            related = [doc for doc in docs_of(src).values() if doc.get(field.store_name) == obj.pk]
            if not related:
                continue
            if field.on_delete == CASCADE:
                stack.extend(src._from_doc(doc) for doc in related)
            elif field.on_delete == SET_NULL:
                for doc in related:
                    set_null.setdefault((src, doc['id']), {})[field.store_name] = None
            elif field.on_delete == PROTECT:
                protected = [src._from_doc(doc) for doc in related]
                raise ProtectedError(
                    f"Cannot delete some instances of model '{model.__name__}' because they are referenced "
                    f"through protected foreign keys: '{src.__name__}.{field.name}'.", set(protected))

    ops = []
    for (model, pk), fields in set_null.items():
        if (model, pk) not in to_delete:
            ops.append(Update(model._meta.collection, pk, fields))
    for (model, pk), removals in m2m_remove.items():
        if (model, pk) not in to_delete:
            ops.append(Update(model._meta.collection, pk, {}, array_remove={k: sorted(v) for k, v in removals.items()}))
    per_model = {}
    for (model, pk), obj in to_delete.items():
        ops.append(Delete(model._meta.collection, pk))
        for mid in obj._markers():
            ops.append(Delete(UNIQUE, mid))
        per_model[model._meta.label] = per_model.get(model._meta.label, 0) + 1
    return ops, len(to_delete), per_model
