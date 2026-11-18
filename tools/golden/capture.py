"""Capture golden responses from the ORM backend (git tag pre-firestore).

    venv/Scripts/python.exe tools/golden/capture.py [scenario_name ...]

Every scenario runs inside a transaction that is rolled back afterwards, so each one
starts from the same golden.sqlite3 state.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(HERE))

from common import GOLDEN_DB, RESPONSES_DIR, canonical, fake_clock, run_scenario  # noqa: E402

os.environ['DATABASE_URL'] = f'sqlite:///{GOLDEN_DB.as_posix()}'
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DEBUG'] = 'True'
os.environ['ALLOWED_HOSTS'] = 'testserver,localhost'

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.db import transaction  # noqa: E402

from scenarios import SCENARIOS  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from django.db import connection  # noqa: E402


@contextmanager
def request_savepoint():
    """Emulate autocommit per request: a request that hits a DB error leaves no trace."""
    sid = transaction.savepoint()
    try:
        yield
    finally:
        if connection.needs_rollback:
            connection.needs_rollback = False
            transaction.savepoint_rollback(sid)
        else:
            transaction.savepoint_commit(sid)


def main(names):
    RESPONSES_DIR.mkdir(exist_ok=True)
    selected = names or list(SCENARIOS)
    for name in selected:
        with transaction.atomic():
            with fake_clock():
                records = run_scenario(SCENARIOS[name], lambda email: User.objects.get(email=email),
                                       step_isolation=request_savepoint)
            transaction.set_rollback(True)
        (RESPONSES_DIR / f'{name}.json').write_text(canonical(records), encoding='utf-8')
        print(f'{name:40} ' + ' '.join(str(r['status']) for r in records))


if __name__ == '__main__':
    main(sys.argv[1:])
