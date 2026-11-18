"""Replay the golden scenarios on the Firestore-backed code (MemoryStore) and compare.

    venv/Scripts/python.exe tools/golden/replay.py [-v] [scenario_name ...]

golden.sqlite3 is imported with import_sqlite logic into a MemoryStore once; every scenario
starts from a snapshot of it. Each response list must equal the stored golden JSON text.
"""
import difflib
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from common import GOLDEN_DB, RESPONSES_DIR, canonical, fake_clock, run_scenario  # noqa: E402

os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DEBUG'] = 'True'
os.environ['STORE_BACKEND'] = 'memory'
os.environ['ALLOWED_HOSTS'] = 'testserver,localhost'

import django  # noqa: E402

django.setup()

from apps.accounts.models import User  # noqa: E402
from apps.core.odm.cache import clear_cache  # noqa: E402
from apps.core.sqlite_import import run_import  # noqa: E402
from apps.core.store import override_store  # noqa: E402
from apps.core.store.memory import MemoryStore  # noqa: E402

from scenarios import SCENARIOS  # noqa: E402


def load_store():
    store = MemoryStore()
    problems, _ = run_import(store, GOLDEN_DB)
    if problems:
        raise SystemExit('Import problems: ' + '; '.join(problems))
    return store


def replay(store, base, name):
    store.restore(base)
    clear_cache()
    with override_store(store):
        with fake_clock():
            records = run_scenario(SCENARIOS[name], lambda email: User.objects.get(email=email))
    return canonical(records)


def main(args):
    verbose = '-v' in args
    names = [a for a in args if a != '-v'] or list(SCENARIOS)
    store = load_store()
    base = store.snapshot()
    failed = []
    for name in names:
        expected = (RESPONSES_DIR / f'{name}.json').read_text(encoding='utf-8')
        try:
            got = replay(store, base, name)
        except Exception as exc:  # crash in the runner itself
            failed.append(name)
            print(f'CRASH {name}: {exc!r}')
            continue
        if got == expected:
            continue
        failed.append(name)
        print(f'FAIL  {name}')
        if verbose:
            diff = difflib.unified_diff(expected.splitlines(), got.splitlines(), 'golden', 'new', lineterm='', n=2)
            print('\n'.join(list(diff)[:80]))
    print(f'\n{len(names) - len(failed)}/{len(names)} scenario mos keldi.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
