"""QuerySet: the subset of the Django QuerySet API that this project uses.

Evaluation reads the (cached) collection, overlays pending writes of the current unit of
work, then filters/orders in Python. Data volume is small (hundreds of documents), and
the versioned cache means repeated requests cost almost no store reads.
"""
import operator

from django.core.exceptions import FieldDoesNotExist

from apps.core.store import Update, get_store

from . import cache, uow
from .fields import ForeignKey, ManyToManyField

LOOKUPS = {'exact', 'iexact', 'isnull', 'in', 'gt', 'gte', 'lt', 'lte', 'contains', 'icontains'}


def _docs(model):
    """{id: raw doc} for a model's collection, with pending writes applied."""
    coll = model._meta.collection
    docs = cache.get_all(get_store(), coll)
    current = uow.current()
    if current is not None:
        docs = current.overlay(coll, docs)
    return docs


def _split(key):
    parts = key.split('__')
    if len(parts) > 1 and parts[-1] in LOOKUPS:
        return parts[:-1], parts[-1]
    return parts, 'exact'


def _coerce(model, parts, value):
    """Coerce a filter value with the target field's to_python (e.g. '9' -> 9)."""
    target = model
    field = None
    for i, part in enumerate(parts):
        if part == 'pk':
            part = 'id'
        try:
            field = target._meta.get_field(part)
        except FieldDoesNotExist:
            from .registry import reverse_accessor
            rev = reverse_accessor(target, part)
            if rev is None:
                raise
            src, rfield = rev
            target = src
            field = src._meta.pk
            continue
        if field.is_relation and i < len(parts) - 1:
            target = field.remote_model
    if field is None:
        return value
    if isinstance(field, (ForeignKey, ManyToManyField)):
        pk_field = field.remote_model._meta.pk
        if hasattr(value, 'pk'):
            return value.pk
        return pk_field.to_python(value) if value is not None else None
    if hasattr(value, 'pk'):
        return value.pk
    return field.to_python(value)


def _values(obj, parts):
    """Terminal values reached from obj along parts (lists fan out over M2M / reverse)."""
    current = [obj]
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        nxt = []
        for item in current:
            if item is None:
                nxt.append(None)
                continue
            if part == 'pk':
                part = 'id'
            meta = item._meta
            try:
                field = meta.get_field(part)
            except FieldDoesNotExist:
                field = None
            if field is None:
                # reverse relation (related_name) -> queryset of related objects
                related = list(getattr(item, part).all())
                if last:
                    nxt.extend(r.pk for r in related) if related else nxt.append(None)
                else:
                    nxt.extend(related) if related else nxt.append(None)
            elif isinstance(field, ManyToManyField):
                ids = list(item.__dict__.get(field.attname) or [])
                if last:
                    nxt.extend(ids) if ids else nxt.append(None)
                else:
                    objs = [o for o in (field.remote_model.objects._by_id(x) for x in ids) if o is not None]
                    nxt.extend(objs) if objs else nxt.append(None)
            elif isinstance(field, ForeignKey):
                if last or part == field.attname:
                    nxt.append(item.__dict__.get(field.attname))
                else:
                    nxt.append(getattr(item, field.name))
            else:
                nxt.append(item.__dict__.get(field.attname))
        current = nxt
    return current


def _match(value, lookup, target):
    if lookup == 'isnull':
        return (value is None) == bool(target)
    if lookup == 'exact':
        return value is None if target is None else value == target
    if lookup == 'iexact':
        if target is None:
            return value is None
        return isinstance(value, str) and value.lower() == str(target).lower()
    if lookup == 'in':
        return value in target
    if value is None:
        return False
    if lookup == 'contains':
        return str(target) in str(value)
    if lookup == 'icontains':
        return str(target).lower() in str(value).lower()
    return {'gt': operator.gt, 'gte': operator.ge, 'lt': operator.lt, 'lte': operator.le}[lookup](value, target)


class _Filter:
    def __init__(self, model, kwargs, negate=False):
        self.negate = negate
        self.conds = []
        for key, value in kwargs.items():
            parts, lookup = _split(key)
            if lookup == 'in':
                target = [_coerce(model, parts, v) for v in value]
            elif lookup == 'isnull':
                target = bool(value)
            elif lookup in ('contains', 'icontains'):
                target = value
            else:
                target = _coerce(model, parts, value)
            self.conds.append((parts, lookup, target))

    def __call__(self, obj):
        ok = all(any(_match(v, lookup, target) for v in _values(obj, parts))
                 for parts, lookup, target in self.conds)
        return not ok if self.negate else ok


def _sort_key(obj, name):
    value = _values(obj, name.split('__'))[0]
    return (value is not None, value)


class QuerySet:
    def __init__(self, model, filters=None, ordering=None, distinct=False, empty=False):
        self.model = model
        self._filters = list(filters or [])
        self._ordering = ordering
        self._distinct = distinct
        self._empty = empty
        self._result = None

    def _clone(self, **kw):
        qs = self.__class__(self.model, self._filters, self._ordering, self._distinct, self._empty)
        for k, v in kw.items():
            setattr(qs, k, v)
        return qs

    def __deepcopy__(self, memo):
        # DRF deep-copies serializer fields; never carry an evaluated result along.
        return self._clone()

    # -- building -------------------------------------------------------
    def all(self):
        return self._clone()

    def none(self):
        return self._clone(_empty=True)

    def filter(self, *args, **kwargs):
        qs = self._clone()
        if kwargs:
            qs._filters = qs._filters + [_Filter(self.model, kwargs)]
        return qs

    def exclude(self, **kwargs):
        qs = self._clone()
        qs._filters = qs._filters + [_Filter(self.model, kwargs, negate=True)]
        return qs

    def filter_fn(self, predicate):
        """Python predicate filter (replaces Q(...) | Q(...))."""
        qs = self._clone()
        qs._filters = qs._filters + [predicate]
        return qs

    def order_by(self, *fields):
        return self._clone(_ordering=list(fields))

    def distinct(self, *fields):
        return self._clone(_distinct=True)

    def select_related(self, *args):
        return self._clone()

    def prefetch_related(self, *args):
        return self._clone()

    def using(self, alias):
        return self._clone()

    # -- evaluation -----------------------------------------------------
    def _evaluate(self):
        if self._result is not None:
            return self._result
        if self._empty:
            self._result = []
            return self._result
        objs = [self.model._from_doc(doc) for doc in _docs(self.model).values()]
        for flt in self._filters:
            objs = [o for o in objs if flt(o)]
        objs.sort(key=lambda o: o.pk)
        ordering = self._ordering if self._ordering is not None else self.model._meta.ordering
        for name in reversed(ordering):
            desc = name.startswith('-')
            key = name.lstrip('-')
            if key == 'pk':
                key = 'id'
            objs.sort(key=lambda o, k=key: _sort_key(o, k), reverse=desc)
        if self._distinct:
            seen, unique = set(), []
            for o in objs:
                if o.pk not in seen:
                    seen.add(o.pk)
                    unique.append(o)
            objs = unique
        self._result = objs
        return objs

    def __iter__(self):
        return iter(self._evaluate())

    def __len__(self):
        return len(self._evaluate())

    def __bool__(self):
        return bool(self._evaluate())

    def __getitem__(self, item):
        return self._evaluate()[item]

    def __repr__(self):
        return f'<QuerySet {self._evaluate()!r}>'

    def count(self):
        return len(self._evaluate())

    def exists(self):
        return bool(self._evaluate())

    def first(self):
        objs = self._evaluate() if (self._ordering is not None or self.model._meta.ordering) else self.order_by('id')._evaluate()
        return objs[0] if objs else None

    def last(self):
        objs = self._evaluate()
        return objs[-1] if objs else None

    def get(self, *args, **kwargs):
        objs = self.filter(**kwargs)._evaluate() if kwargs else self._evaluate()
        if not objs:
            raise self.model.DoesNotExist(f'{self.model.__name__} matching query does not exist.')
        if len(objs) > 1:
            raise self.model.MultipleObjectsReturned(f'get() returned more than one {self.model.__name__} -- it returned {len(objs)}!')
        return objs[0]

    def values(self, *fields):
        out = []
        for obj in self._evaluate():
            names = fields or [f.attname for f in self.model._meta.concrete_fields]
            out.append({name: _values(obj, name.split('__'))[0] for name in names})
        return out

    def values_list(self, *fields, flat=False):
        rows = [[_values(obj, f.split('__'))[0] for f in fields] for obj in self._evaluate()]
        return [r[0] for r in rows] if flat else [tuple(r) for r in rows]

    # -- internal lookups -----------------------------------------------
    def _by_id(self, id):
        doc = _docs(self.model).get(id)
        return self.model._from_doc(doc) if doc is not None else None

    def _raw(self, id):
        return _docs(self.model).get(id)

    # -- writing --------------------------------------------------------
    def create(self, **kwargs):
        obj = self.model(**kwargs)
        obj.save(force_insert=True)
        return obj

    def get_or_create(self, defaults=None, **kwargs):
        obj = self.filter(**kwargs).first()
        if obj is not None:
            return obj, False
        params = {k: v for k, v in kwargs.items() if '__' not in k}
        params.update(defaults or {})
        return self.create(**params), True

    def update_or_create(self, defaults=None, **kwargs):
        obj = self.filter(**kwargs).first()
        if obj is None:
            params = {k: v for k, v in kwargs.items() if '__' not in k}
            params.update(defaults or {})
            return self.create(**params), True
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
        obj.save()
        return obj, False

    def bulk_create(self, objs, ignore_conflicts=False):
        objs = list(objs)
        if not objs:
            return objs
        store = get_store()
        ids = iter(store.allocate_ids(self.model._meta.collection, sum(1 for o in objs if o.pk is None)))
        created = []
        for obj in objs:
            if obj.pk is None:
                obj.pk = next(ids)
            try:
                with uow.atomic():
                    obj._adding = True
                    obj.save(force_insert=True)
            except Exception:
                if not ignore_conflicts:
                    raise
                continue
            created.append(obj)
        return objs

    def update(self, **kwargs):
        objs = self._evaluate()
        ops = []
        for obj in objs:
            for key, value in kwargs.items():
                setattr(obj, key, value)
            for key in kwargs:
                obj._meta.get_field(key).check(obj.__dict__.get(obj._meta.get_field(key).attname))
            ops.append(Update(self.model._meta.collection, obj.pk, obj._doc(set(kwargs))))
        uow.write(ops)
        return len(objs)

    def delete(self):
        from .deletion import collect
        objs = self._evaluate()
        if not objs:
            return 0, {}
        ops, count, per_model = collect(objs)
        uow.write(ops)
        self._result = None
        return count, per_model


class ManyRelatedManager:
    """Forward many-to-many manager (e.g. department.teachers)."""

    def __init__(self, instance, field):
        self.instance = instance
        self.field = field
        self.model = field.remote_model

    def _ids(self):
        return list(self.instance.__dict__.get(self.field.attname) or [])

    def all(self):
        ids = set(self._ids())
        return QuerySet(self.model).filter(pk__in=ids)

    def filter(self, **kwargs):
        return self.all().filter(**kwargs)

    def count(self):
        return self.all().count()

    def exists(self):
        return self.all().exists()

    def first(self):
        return self.all().first()

    def __iter__(self):
        return iter(self.all())

    def _save(self, ids):
        self.instance.__dict__[self.field.attname] = ids
        if self.instance.pk is not None and not self.instance._adding:
            uow.write([Update(self.instance._meta.collection, self.instance.pk, {self.field.store_name: list(ids)})])

    @staticmethod
    def _pk(value):
        return value.pk if hasattr(value, 'pk') else value

    def set(self, objs):
        self._save([self._pk(o) for o in objs])

    def add(self, *objs):
        ids = self._ids()
        for o in objs:
            if self._pk(o) not in ids:
                ids.append(self._pk(o))
        self._save(ids)

    def remove(self, *objs):
        drop = {self._pk(o) for o in objs}
        self._save([i for i in self._ids() if i not in drop])

    def clear(self):
        self._save([])
