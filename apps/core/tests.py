"""Store contract and ODM behaviour tests (run on MemoryStore; the store contract tests
also run against Firestore when FIRESTORE_TEST=1 and credentials are configured)."""
import os
from decimal import Decimal
from datetime import date

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import SimpleTestCase

from apps.core import odm
from apps.core.store import Create, Delete, Set, Update, override_store
from apps.core.store.memory import JsonFileStore, MemoryStore


# ---- test models -------------------------------------------------------------
class Parent(odm.Model):
    name = odm.CharField(max_length=50)
    created_at = odm.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'coretest'
        ordering = ['name']
        unique = [odm.UniqueKey('parent_name', lambda o: o.name.lower() if o.name else None)]


class Tag(odm.Model):
    label = odm.CharField()

    class Meta:
        app_label = 'coretest'
        ordering = ['label']


class Child(odm.Model):
    parent = odm.ForeignKey(Parent, on_delete=odm.CASCADE, related_name='children')
    guardian = odm.ForeignKey(Parent, on_delete=odm.SET_NULL, null=True, related_name='wards')
    tags = odm.ManyToManyField(Tag, related_name='children')
    score = odm.IntegerField(positive=True, default=0)
    amount = odm.DecimalField(decimal_places=2, default=0)
    born = odm.DateField(null=True)
    data = odm.JSONField(default=dict)

    class Meta:
        app_label = 'coretest'
        ordering = ['-score']


class Locked(odm.Model):
    parent = odm.ForeignKey(Parent, on_delete=odm.PROTECT, related_name='locks')

    class Meta:
        app_label = 'coretest'


class StoreContractMixin:
    def make_store(self):
        raise NotImplementedError

    def setUp(self):
        self.store = self.make_store()

    def test_create_get_query_delete(self):
        s = self.store
        s.commit([Create('t_things', 1, {'id': 1, 'k': 'a', 'tags': [1, 2]}),
                  Create('t_things', 2, {'id': 2, 'k': 'b', 'tags': [2]})])
        self.assertEqual(s.get('t_things', 1)['k'], 'a')
        self.assertEqual(sorted(d['id'] for d in s.query('t_things')), [1, 2])
        self.assertEqual([d['id'] for d in s.query('t_things', ('k', '==', 'b'))], [2])
        self.assertEqual(sorted(d['id'] for d in s.query('t_things', ('tags', 'array_contains', 2))), [1, 2])
        s.commit([Update('t_things', 1, {'k': 'z'}, array_remove={'tags': [1]}), Delete('t_things', 2)])
        self.assertEqual(s.get('t_things', 1), {'id': 1, 'k': 'z', 'tags': [2]})
        self.assertIsNone(s.get('t_things', 2))

    def test_create_conflict_is_atomic(self):
        s = self.store
        s.commit([Create('t_things', 1, {'id': 1})])
        with self.assertRaises(IntegrityError):
            s.commit([Set('t_things', 3, {'id': 3}), Create('t_things', 1, {'id': 1})])
        self.assertIsNone(s.get('t_things', 3))

    def test_counters_and_versions(self):
        s = self.store
        self.assertEqual(s.allocate_ids('t_things', 3), [1, 2, 3])
        s.bump_counter('t_things', 10)
        self.assertEqual(s.allocate_ids('t_things'), [11])
        s.bump_counter('t_things', 5)
        self.assertEqual(s.allocate_ids('t_things'), [12])
        before = s.versions().get('t_things', 0)
        s.commit([Set('t_things', 1, {'id': 1})])
        self.assertEqual(s.versions()['t_things'], before + 1)


class MemoryStoreContractTests(StoreContractMixin, SimpleTestCase):
    def make_store(self):
        return MemoryStore()


class JsonFileStoreContractTests(StoreContractMixin, SimpleTestCase):
    def make_store(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), 'store.json')
        return JsonFileStore(path)

    def test_survives_reload(self):
        self.store.commit([Set('t_things', 1, {'id': 1, 'k': 'a'})])
        reloaded = JsonFileStore(self.store.path)
        self.assertEqual(reloaded.get('t_things', 1), {'id': 1, 'k': 'a'})


if os.environ.get('FIRESTORE_TEST') == '1':
    class FirestoreStoreContractTests(StoreContractMixin, SimpleTestCase):
        def make_store(self):
            from apps.core.store.firestore import FirestoreStore
            store = FirestoreStore()
            store.drop_all()
            return store


class OdmTests(SimpleTestCase):
    def setUp(self):
        self._ctx = override_store(MemoryStore())
        self._ctx.__enter__()

    def tearDown(self):
        self._ctx.__exit__(None, None, None)

    def test_crud_ordering_and_lookups(self):
        a = Parent.objects.create(name='Beta')
        b = Parent.objects.create(name='alpha')
        self.assertEqual([p.name for p in Parent.objects.all()], ['Beta', 'alpha'])  # binary order like SQLite
        self.assertEqual(Parent.objects.get(name__iexact='ALPHA').pk, b.pk)
        c1 = Child.objects.create(parent=a, score=5, amount='3.5', born='2026-01-02', data={'z': 1, 'a': [1, [2]]})
        c2 = Child.objects.create(parent=b, guardian=a, score=9)
        self.assertEqual([c.pk for c in Child.objects.all()], [c2.pk, c1.pk])
        self.assertEqual(list(a.children.all()), [c1])
        self.assertEqual(Child.objects.filter(parent__name='alpha').get(), c2)
        self.assertEqual(Child.objects.filter(parent_id=str(a.pk)).count(), 1)
        self.assertTrue(Child.objects.filter(guardian__isnull=True).exists())
        fresh = Child.objects.get(pk=c1.pk)
        self.assertEqual(fresh.amount, Decimal('3.50'))
        self.assertEqual(fresh.born, date(2026, 1, 2))
        self.assertEqual(list(fresh.data), ['z', 'a'])          # JSON key order kept
        self.assertEqual(fresh.parent.name, 'Beta')
        with self.assertRaises(ValueError):
            Child.objects.get(pk='abc')
        with self.assertRaises(Child.DoesNotExist):
            Child.objects.get(pk=999)

    def test_unique_marker(self):
        Parent.objects.create(name='Same')
        with self.assertRaises(IntegrityError):
            Parent.objects.create(name='SAME')
        p = Parent.objects.get(name='Same')
        p.name = 'Other'
        p.save()
        Parent.objects.create(name='same')     # old marker released
        self.assertEqual(Parent.objects.count(), 2)

    def test_positive_check(self):
        p = Parent.objects.create(name='P')
        with self.assertRaises(IntegrityError):
            Child.objects.create(parent=p, score=-1)

    def test_atomic_rollback_and_overlay(self):
        p = Parent.objects.create(name='P')
        with self.assertRaises(RuntimeError):
            with odm.atomic():
                Child.objects.create(parent=p)
                self.assertEqual(Child.objects.count(), 1)   # reads see pending writes
                raise RuntimeError
        self.assertEqual(Child.objects.count(), 0)
        with odm.atomic():
            Child.objects.create(parent=p)
            try:
                with odm.atomic():
                    Parent.objects.create(name='Q')
                    raise ValueError
            except ValueError:
                pass
        self.assertEqual(Child.objects.count(), 1)
        self.assertFalse(Parent.objects.filter(name='Q').exists())

    def test_m2m_and_cascades(self):
        t1, t2 = Tag.objects.create(label='b'), Tag.objects.create(label='a')
        p, g = Parent.objects.create(name='P'), Parent.objects.create(name='G')
        c = Child.objects.create(parent=p, guardian=g)
        c.tags.set([t1, t2])
        self.assertEqual([t.label for t in Child.objects.get(pk=c.pk).tags.all()], ['a', 'b'])
        self.assertEqual(list(t1.children.all()), [c])
        self.assertEqual(Child.objects.filter(tags__label='a').count(), 1)
        t1.delete()
        self.assertEqual([t.label for t in Child.objects.get(pk=c.pk).tags.all()], ['a'])
        g.delete()
        self.assertIsNone(Child.objects.get(pk=c.pk).guardian_id)
        Locked.objects.create(parent=p)
        with self.assertRaises(ProtectedError):
            p.delete()
        Locked.objects.all().delete()
        p.delete()
        self.assertEqual(Child.objects.count(), 0)
        Parent.objects.create(name='P')   # marker freed by delete

    def test_bulk_create_ignore_conflicts_and_update(self):
        Parent.objects.create(name='x')
        Parent.objects.bulk_create([Parent(name='X'), Parent(name='y')], ignore_conflicts=True)
        self.assertEqual(sorted(p.name for p in Parent.objects.all()), ['x', 'y'])
        p = Parent.objects.create(name='z')
        Child.objects.create(parent=p, score=1)
        Child.objects.filter(parent=p).update(score=7)
        self.assertEqual(Child.objects.get().score, 7)
