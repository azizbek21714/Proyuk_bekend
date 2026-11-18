"""ODM field types. Each field converts between Python values and store-safe values.

Encoding in the store:
    DateTimeField -> aware UTC datetime (Firestore Timestamp)
    DateField     -> 'YYYY-MM-DD'
    DecimalField  -> quantised string ('140.00')
    JSONField     -> JSON text (keeps key order; avoids Firestore nested-array limits)
    ForeignKey    -> '<name>_id' integer or None
    ManyToMany    -> '<name>_ids' list of integers on the owning document
"""
import copy
import datetime as dt
import json
from decimal import Decimal

from django.db import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

NOT_PROVIDED = object()

CASCADE = 'CASCADE'
SET_NULL = 'SET_NULL'
PROTECT = 'PROTECT'


class Field:
    is_relation = False
    many_to_many = False

    def __init__(self, default=NOT_PROVIDED, null=False, choices=None, **kwargs):
        self.default = default
        self.null = null
        self.choices = choices
        self.name = None
        self.attname = None
        self.store_name = None
        self.model = None

    def contribute(self, model, name):
        self.model = model
        self.name = name
        self.attname = name
        self.store_name = name

    def get_default(self):
        if self.default is NOT_PROVIDED:
            return None if self.null else self.empty_value()
        return self.default() if callable(self.default) else copy.deepcopy(self.default)

    def empty_value(self):
        return None

    def to_python(self, value):
        """Coerce a value used in filters/assignment (strings from query params etc.)."""
        return value

    def to_store(self, value):
        # Like Django's get_prep_value: values assigned as strings ('2026-01-02', '5') are
        # converted when saved; the instance attribute itself is left as assigned.
        return self.to_python(value)

    def from_store(self, value):
        return value

    def check(self, value):
        """Database-level constraints (raise IntegrityError like the SQL backend)."""
        if value is None and not self.null:
            raise IntegrityError(f'NOT NULL constraint failed: {self.model.__name__}.{self.name}')


class CharField(Field):
    def __init__(self, max_length=None, blank=False, **kw):
        super().__init__(**kw)
        self.max_length = max_length

    def empty_value(self):
        return ''

    def to_python(self, value):
        return value if value is None or isinstance(value, str) else str(value)


TextField = CharField
EmailField = CharField


class IntegerField(Field):
    def __init__(self, positive=False, **kw):
        super().__init__(**kw)
        self.positive = positive

    def empty_value(self):
        return None

    def to_python(self, value):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise exc.__class__(f"Field '{self.name}' expected a number but got {value!r}.") from exc

    def check(self, value):
        super().check(value)
        value = self.to_python(value)
        if self.positive and value is not None and value < 0:
            raise IntegrityError(f'CHECK constraint failed: {self.name} >= 0')


class AutoField(IntegerField):
    pass


class BooleanField(Field):
    def empty_value(self):
        return False

    def to_python(self, value):
        if isinstance(value, str):
            return value.lower() in ('1', 'true', 't', 'yes')
        return bool(value) if value is not None else None


class DateField(Field):
    def to_python(self, value):
        if value is None or (isinstance(value, dt.date) and not isinstance(value, dt.datetime)):
            return value
        if isinstance(value, dt.datetime):
            return value.date()
        parsed = parse_date(str(value))
        if parsed is None:
            raise ValueError(f'Invalid date: {value!r}')
        return parsed

    def to_store(self, value):
        value = self.to_python(value)
        return value.isoformat() if value is not None else None

    def from_store(self, value):
        return parse_date(value) if isinstance(value, str) else value


class DateTimeField(Field):
    def __init__(self, auto_now=False, auto_now_add=False, **kw):
        if auto_now or auto_now_add:
            kw.setdefault('null', True)
        super().__init__(**kw)
        self.auto_now = auto_now
        self.auto_now_add = auto_now_add

    def to_python(self, value):
        if value is None or isinstance(value, dt.datetime):
            return value
        parsed = parse_datetime(str(value))
        if parsed is None:
            raise ValueError(f'Invalid datetime: {value!r}')
        return parsed

    def to_store(self, value):
        value = self.to_python(value)
        if value is None:
            return None
        if timezone.is_naive(value):
            value = timezone.make_aware(value, dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def from_store(self, value):
        if isinstance(value, str):
            value = parse_datetime(value)
        if isinstance(value, dt.datetime) and timezone.is_naive(value):
            value = value.replace(tzinfo=dt.timezone.utc)
        return value


class DecimalField(Field):
    def __init__(self, max_digits=None, decimal_places=2, **kw):
        super().__init__(**kw)
        self.decimal_places = decimal_places

    def to_python(self, value):
        if value is None or isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def to_store(self, value):
        if value is None:
            return None
        quantum = Decimal(1).scaleb(-self.decimal_places)
        return str(self.to_python(value).quantize(quantum))

    def from_store(self, value):
        return Decimal(value) if value is not None else None


class JSONField(Field):
    def to_store(self, value):
        return json.dumps(value, ensure_ascii=False)

    def from_store(self, value):
        if value is None:
            return None
        return json.loads(value) if isinstance(value, str) else value


class FileField(CharField):
    """Stores only the file name (the API never writes files)."""

    def empty_value(self):
        return None


class ForeignKey(Field):
    is_relation = True

    def __init__(self, to, on_delete, related_name=None, null=False, **kw):
        super().__init__(null=null, **kw)
        self.to = to                    # 'app.Model' / 'Model' / class
        self.on_delete = on_delete
        self.related_name = related_name

    def contribute(self, model, name):
        super().contribute(model, name)
        self.attname = f'{name}_id'
        self.store_name = self.attname

    @property
    def remote_model(self):
        from .registry import resolve
        return resolve(self.to)

    def get_default(self):
        return None

    def to_python(self, value):
        if value is None:
            return None
        if hasattr(value, 'pk'):
            return value.pk
        return self.remote_model._meta.pk.to_python(value)


OneToOneField = ForeignKey


class ManyToManyField(Field):
    """Stored as a list of ids on the owning document (`<name>_ids`)."""
    is_relation = True
    many_to_many = True

    def __init__(self, to, related_name=None, **kw):
        super().__init__(**kw)
        self.to = to
        self.related_name = related_name

    def contribute(self, model, name):
        super().contribute(model, name)
        self.attname = f'{name}_ids'
        self.store_name = self.attname

    @property
    def remote_model(self):
        from .registry import resolve
        return resolve(self.to)

    def get_default(self):
        return []

    def to_store(self, value):
        return list(value or [])

    def from_store(self, value):
        return list(value or [])
