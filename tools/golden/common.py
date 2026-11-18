"""Golden-response tooling shared by capture (old ORM code) and replay (Firestore code).

A scenario is a list of HTTP steps run in-process with DRF's APIClient. Each step's
response is normalised (datetimes and JWT strings replaced by placeholders) and stored
as canonical JSON text, so the comparison is strict about values AND key order.
"""
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
BACKEND_DIR = HERE.parent.parent
GOLDEN_DB = HERE / 'golden.sqlite3'
FIXTURE_XLSX = HERE / 'fixture.xlsx'
RESPONSES_DIR = HERE / 'responses'

# All golden users share this password (set by make_dataset.py).
GOLDEN_PASSWORD = 'Golden-Pass-1!'

# Actor key -> email of a user that exists in the golden database.
ACTORS = {
    'super': 'super@golden.test',
    'admin_group': 'admin-group@golden.test',
    'dekan': 'dekan@golden.test',
    'kafedra': 'kafedra@golden.test',
    'oquv': 'oquv@golden.test',
    'teacher': 'teacher@golden.test',
    'teacher2': 'teacher2@golden.test',
    'noprofile': 'noprofile@golden.test',
    'inactive': 'inactive@golden.test',
}

_ISO_DT = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$')
_JWT = re.compile(r'^eyJ[\w-]+\.[\w-]+\.[\w-]+$')


def _normalise(value):
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, str):
        if _ISO_DT.match(value):
            return '<dt>'
        if _JWT.match(value):
            return '<jwt>'
    return value


def response_record(response):
    """Canonical, comparable form of a test-client response."""
    ctype = response.get('Content-Type', '') or ''
    if response.status_code >= 500:
        # Only the status matters for server errors (the body is a debug/traceback page).
        return {'status': response.status_code, 'content_type': None, 'www_authenticate': None,
                'kind': 'error', 'body': None}
    raw = response.content.decode('utf-8', errors='replace') if response.content else ''
    try:
        body = _normalise(json.loads(raw)) if raw else None
        kind = 'json'
    except ValueError:
        body = raw
        kind = 'text'
    return {
        'status': response.status_code,
        'content_type': ctype.split(';')[0],
        'www_authenticate': response.get('WWW-Authenticate'),
        'kind': kind,
        'body': body,
    }


def canonical(records):
    return json.dumps(records, ensure_ascii=False, indent=1)


class FakeClock:
    """Deterministic django.utils.timezone.now(): fixed base, +1 ms per call."""

    BASE = datetime(2026, 11, 18, 9, 0, 0, tzinfo=dt_timezone.utc)

    def __init__(self):
        self.ticks = 0

    def __call__(self):
        self.ticks += 1
        return self.BASE + timedelta(milliseconds=self.ticks)


@contextmanager
def fake_clock():
    clock = FakeClock()
    with mock.patch('django.utils.timezone.now', clock):
        yield clock


def _resolve(value, ctx):
    if isinstance(value, str) and value.startswith('$'):
        return ctx[value[1:]]
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    return value


@contextmanager
def _no_isolation():
    yield


def run_scenario(scenario, get_user, step_isolation=_no_isolation):
    """Run one scenario; return list of response records.

    get_user(email) -> user object accepted by APIClient.force_authenticate.
    step_isolation() -> context manager wrapped around each request (the ORM capture uses
    a savepoint so a request that fails with a DB error has no effect, like autocommit).
    """
    from django.core.cache import cache

    cache.clear()  # login throttle state
    ctx = {}
    records = []
    for step in scenario['steps']:
        with step_isolation():
            records.append(_run_step(step, ctx, get_user))
    return records


def _run_step(step, ctx, get_user):
    from rest_framework.test import APIClient

    if True:
        client = APIClient(raise_request_exception=False)  # 500s become responses, as in production
        actor = step.get('actor')
        if actor:
            client.force_authenticate(get_user(ACTORS[actor]))
        if step.get('bearer'):
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {_resolve(step['bearer'], ctx)}")
        if step.get('auth_header') is not None:
            client.credentials(HTTP_AUTHORIZATION=step['auth_header'])
        method = getattr(client, step['method'].lower())
        data = _resolve(step.get('data'), ctx)
        fmt = step.get('format', 'json')
        if fmt == 'multipart':
            data = dict(data or {})
            if data.pop('$file', None):
                data['file'] = open(FIXTURE_XLSX, 'rb')
            response = method(step['path'], data, format='multipart')
            if 'file' in data:
                data['file'].close()
        elif data is None:
            response = method(step['path'])
        else:
            response = method(step['path'], data, format='json')
        for key, field in (step.get('save') or {}).items():
            try:
                ctx[key] = json.loads(response.content)[field]
            except (ValueError, KeyError, TypeError):
                ctx[key] = None
        return response_record(response)
