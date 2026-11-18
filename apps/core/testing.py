"""Test base class: every test runs on a fresh MemoryStore seeded like a new deployment."""
from django.core.cache import cache
from django.test import SimpleTestCase

from apps.core.store import override_store
from apps.core.store.memory import MemoryStore


class StoreTestCase(SimpleTestCase):
    def run(self, result=None):
        with override_store(MemoryStore()):
            from apps.core.management.commands.seed_defaults import seed
            seed()
            cache.clear()  # login throttle state
            return super().run(result)
