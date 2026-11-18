"""ODM Model: a small, Django-ORM-shaped layer over the Store."""
import hashlib
import json

from django.core.exceptions import FieldDoesNotExist, MultipleObjectsReturned, ObjectDoesNotExist
from django.db import IntegrityError
from django.utils import timezone

from apps.core.store import Create, Delete, Update, get_store

from . import cache, registry, uow
from .fields import AutoField, DateTimeField, Field, ForeignKey, ManyToManyField

UNIQUE = '_unique'


class UniqueKey:
    """A uniqueness rule. value_fn(instance) returns a JSON-able value, or None when the
    rule does not apply (like a conditional UniqueConstraint)."""

    def __init__(self, name, value_fn):
        self.name = name
        self.value_fn = value_fn

    def marker_id(self, instance):
        value = self.value_fn(instance)
        if value is None:
            return None
        digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
        return f'{self.name}:{digest}'


class Options:
    def __init__(self, model, meta, app_label):
        self.model = model
        self.app_label = app_label
        self.object_name = model.__name__
        self.model_name = model.__name__.lower()
        self.label = f'{app_label}.{model.__name__}'
        self.collection = getattr(meta, 'collection', None) or f'{app_label}_{self.model_name}'
        self.ordering = list(getattr(meta, 'ordering', []))
        self.unique = list(getattr(meta, 'unique', []))
        self.fields = []
        self.pk = None

    def add_field(self, field):
        self.fields.append(field)
        if isinstance(field, AutoField):
            self.pk = field

    def get_field(self, name):
        if name == 'pk':
            return self.pk
        for field in self.fields:
            if field.name == name or field.attname == name:
                return field
        raise FieldDoesNotExist(f'{self.object_name} has no field named {name!r}')

    @property
    def concrete_fields(self):
        return [f for f in self.fields if not f.many_to_many]


class ForwardFK:
    def __init__(self, field):
        self.field = field

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        value = instance.__dict__.get(self.field.attname)
        if value is None:
            return None
        cached = instance._fk_cache.get(self.field.name)
        if cached is not None and cached.pk == value:
            return cached
        obj = self.field.remote_model.objects._by_id(value)
        if obj is None:
            raise self.field.remote_model.DoesNotExist(
                f'{self.field.remote_model.__name__} matching id={value} does not exist.')
        instance._fk_cache[self.field.name] = obj
        return obj

    def __set__(self, instance, value):
        if value is None:
            instance.__dict__[self.field.attname] = None
            instance._fk_cache.pop(self.field.name, None)
        elif isinstance(value, Model):
            instance.__dict__[self.field.attname] = value.pk
            instance._fk_cache[self.field.name] = value
        else:
            raise ValueError(f'Cannot assign {value!r}: "{self.field.name}" must be a model instance.')


class ManyDescriptor:
    def __init__(self, field):
        self.field = field

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        from .queryset import ManyRelatedManager
        return ManyRelatedManager(instance, self.field)


class ManagerDescriptor:
    def __get__(self, instance, owner):
        if instance is not None:
            raise AttributeError('Manager is not accessible via model instances')
        from .queryset import QuerySet
        return QuerySet(owner)


class ModelBase(type):
    def __new__(mcs, name, bases, attrs):
        if not any(isinstance(b, ModelBase) for b in bases):
            return super().__new__(mcs, name, bases, attrs)
        meta = attrs.pop('Meta', None)
        fields = [(k, v) for k, v in list(attrs.items()) if isinstance(v, Field)]
        for k, _ in fields:
            attrs.pop(k)
        cls = super().__new__(mcs, name, bases, attrs)
        module = attrs.get('__module__', '')
        parts = module.split('.')
        app_label = getattr(meta, 'app_label', None) or (parts[1] if parts[0] == 'apps' and len(parts) > 1 else parts[0])
        cls._meta = Options(cls, meta, app_label)
        if not any(k == 'id' for k, _ in fields):
            fields.insert(0, ('id', AutoField(null=True)))
        for fname, field in fields:
            field.contribute(cls, fname)
            cls._meta.add_field(field)
            if isinstance(field, ForeignKey):
                setattr(cls, fname, ForwardFK(field))
            elif isinstance(field, ManyToManyField):
                setattr(cls, fname, ManyDescriptor(field))
        cls.DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {'__module__': module})
        cls.MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {'__module__': module})
        cls.objects = ManagerDescriptor()
        registry.register(cls, app_label)
        return cls


class Model(metaclass=ModelBase):
    def __init__(self, **kwargs):
        self._fk_cache = {}
        self._loaded_markers = set()
        self._adding = True
        for field in self._meta.fields:
            self.__dict__[field.attname] = field.get_default()
        for key, value in kwargs.items():
            if key == 'pk':
                key = 'id'
            setattr(self, key, value)

    # -- identity ---------------------------------------------------------
    @property
    def pk(self):
        return self.__dict__.get('id')

    @pk.setter
    def pk(self, value):
        self.__dict__['id'] = value

    def __eq__(self, other):
        return isinstance(other, Model) and other._meta.model is self._meta.model and self.pk is not None and self.pk == other.pk

    def __hash__(self):
        return hash((self._meta.label, self.pk))

    def __repr__(self):
        return f'<{self.__class__.__name__}: {self}>'

    def __str__(self):
        return f'{self.__class__.__name__} object ({self.pk})'

    def __getattr__(self, name):
        # Reverse relations (related_name) are resolved lazily.
        if name.startswith('_'):
            raise AttributeError(name)
        found = registry.reverse_accessor(type(self), name)
        if found is None:
            raise AttributeError(f'{type(self).__name__!r} object has no attribute {name!r}')
        src, field = found
        from .queryset import QuerySet
        if field.many_to_many:
            return QuerySet(src).filter(**{field.name: self.pk})
        return QuerySet(src).filter(**{field.attname: self.pk})

    def serializable_value(self, field_name):
        try:
            field = self._meta.get_field(field_name)
        except FieldDoesNotExist:
            return getattr(self, field_name)
        return self.__dict__.get(field.attname)

    # -- store mapping ----------------------------------------------------
    @classmethod
    def _from_doc(cls, doc):
        obj = cls.__new__(cls)
        obj._fk_cache = {}
        obj._adding = False
        for field in cls._meta.fields:
            if field.store_name in doc:
                obj.__dict__[field.attname] = field.from_store(doc[field.store_name])
            else:
                obj.__dict__[field.attname] = field.get_default()
        obj.__dict__['id'] = doc['id']
        obj._loaded_markers = obj._markers()
        return obj

    def _doc(self, names=None):
        doc = {}
        for field in self._meta.fields:
            if names is None or field.name in names or field.attname in names:
                doc[field.store_name] = field.to_store(self.__dict__.get(field.attname))
        return doc

    def _markers(self):
        return {mid for key in self._meta.unique if (mid := key.marker_id(self)) is not None}

    # -- persistence ------------------------------------------------------
    def save(self, update_fields=None, force_insert=False, **kwargs):
        meta = self._meta
        store = get_store()
        adding = self._adding or self.pk is None or force_insert
        if adding and self.pk is None:
            self.pk = store.allocate_ids(meta.collection)[0]
        for field in meta.fields:
            if isinstance(field, DateTimeField):
                if field.auto_now or (adding and field.auto_now_add):
                    if adding or update_fields is None or field.name in update_fields:
                        self.__dict__[field.attname] = timezone.now()
        names = None if (adding or update_fields is None) else set(update_fields)
        for field in meta.fields:
            if field.many_to_many or isinstance(field, AutoField):
                continue
            if names is None or field.name in names or field.attname in names:
                field.check(self.__dict__.get(field.attname))

        markers = self._markers()
        new_markers = markers - self._loaded_markers
        old_markers = self._loaded_markers - markers
        self._check_markers_free(new_markers)

        ops = []
        if adding:
            doc = self._doc()
            doc['id'] = self.pk
            ops.append(Create(meta.collection, self.pk, doc))
        else:
            ops.append(Update(meta.collection, self.pk, self._doc(names)))
        for mid in new_markers:
            ops.append(Create(UNIQUE, mid, {'id': mid, 'coll': meta.collection, 'ref': self.pk}))
        for mid in old_markers:
            ops.append(Delete(UNIQUE, mid))
        uow.write(ops)
        self._adding = False
        self._loaded_markers = markers

    def _check_markers_free(self, marker_ids):
        if not marker_ids:
            return
        store = get_store()
        current = uow.current()
        for mid in marker_ids:
            existing = store.get(UNIQUE, mid)
            if current is not None:
                existing = current.pending_doc(UNIQUE, mid, existing)
            if existing is not None and not (existing.get('coll') == self._meta.collection and existing.get('ref') == self.pk):
                raise IntegrityError(f'UNIQUE constraint failed ({mid.split(":")[0]})')

    def delete(self):
        from .deletion import collect
        ops, count, per_model = collect([self])
        uow.write(ops)
        return count, per_model

    def refresh_from_db(self):
        cache.invalidate([self._meta.collection])
        doc = type(self).objects._raw(self.pk)
        if doc is None:
            raise self.DoesNotExist(f'{type(self).__name__} matching id={self.pk} does not exist.')
        fresh = type(self)._from_doc(doc)
        self.__dict__.update({f.attname: fresh.__dict__[f.attname] for f in self._meta.fields})
        self._fk_cache = {}
        self._loaded_markers = fresh._loaded_markers
