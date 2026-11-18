"""Copy the old Django SQLite database into the document store, keeping every id.

Used by the `import_sqlite` and `verify_import` commands (and by the golden replay tests).
"""
import json
import sqlite3
from datetime import datetime, timezone

from apps.core.odm import registry
from apps.core.odm.model import UNIQUE
from apps.core.store import Create, Set

SEEDED = ('_meta', 'seeded')


def _table(model):
    if model._meta.label == 'accounts.User':
        return 'auth_user'
    return f'{model._meta.app_label}_{model._meta.model_name}'


def _rows(conn, table):
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY id')]
    except sqlite3.OperationalError:
        return None


def _m2m(conn, model, field):
    """{owner_id: [remote ids]} from Django's join table."""
    owner = model._meta.model_name
    remote = field.remote_model._meta.model_name
    table = f'{_table(model)}_{field.name}'
    result = {}
    for owner_id, remote_id in conn.execute(
            f'SELECT "{owner}_id", "{remote}_id" FROM "{table}" ORDER BY id'):
        result.setdefault(owner_id, []).append(remote_id)
    return result


def _user_groups(conn):
    result = {}
    for user_id, name in conn.execute(
            'SELECT ug.user_id, g.name FROM auth_user_groups ug JOIN auth_group g ON g.id = ug.group_id '
            'ORDER BY ug.id'):
        result.setdefault(user_id, []).append(name)
    return result


def build_docs(conn, model):
    """List of store documents for `model` built from its SQLite table (None if no table)."""
    rows = _rows(conn, _table(model))
    if rows is None:
        return None
    meta = model._meta
    m2m = {f.name: _m2m(conn, model, f) for f in meta.fields if f.many_to_many}
    groups = _user_groups(conn) if meta.label == 'accounts.User' else None
    docs = []
    for row in rows:
        doc = {}
        for field in meta.fields:
            if field.many_to_many:
                value = m2m[field.name].get(row['id'], [])
            elif groups is not None and field.name == 'groups':
                value = groups.get(row['id'], [])
            elif field.name == 'id':
                continue
            elif field.attname in row:
                value = row[field.attname]
                if field.__class__.__name__ == 'JSONField' and isinstance(value, str):
                    value = json.loads(value)
            else:
                value = field.get_default()
            doc[field.store_name] = field.to_store(value)
        doc['id'] = row['id']
        docs.append(doc)
    return docs


def max_sequence(conn, table, docs):
    seq = 0
    try:
        found = conn.execute('SELECT seq FROM sqlite_sequence WHERE name = ?', (table,)).fetchone()
        seq = found[0] if found else 0
    except sqlite3.OperationalError:
        pass
    return max([seq] + [d['id'] for d in docs])


def _blacklist_docs(conn):
    """Still-valid blacklisted refresh tokens, so logged-out tokens stay unusable."""
    try:
        rows = conn.execute(
            'SELECT o.jti, o.user_id, o.expires_at FROM token_blacklist_blacklistedtoken b '
            'JOIN token_blacklist_outstandingtoken o ON o.id = b.token_id').fetchall()
    except sqlite3.OperationalError:
        return []
    from django.utils.dateparse import parse_datetime
    now = datetime.now(timezone.utc)
    docs = []
    for jti, user_id, expires_at in rows:
        exp = parse_datetime(str(expires_at))
        if exp is None:
            continue
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp > now:
            docs.append({'id': jti, 'user_id': str(user_id) if user_id is not None else None,
                         'exp': exp, 'blacklisted_at': now})
    return docs


def plan_import(sqlite_path):
    """Returns (per_model, marker_ops, blacklist) where per_model = [(model, docs, counter)]."""
    conn = sqlite3.connect(sqlite_path)
    try:
        per_model, markers, problems = [], {}, []
        for model in registry.all_models():
            docs = build_docs(conn, model)
            if docs is None:
                problems.append(f'{model._meta.label}: jadval topilmadi ({_table(model)})')
                continue
            per_model.append((model, docs, max_sequence(conn, _table(model), docs)))
            for doc in docs:
                obj = model._from_doc(doc)
                for mid in obj._markers():
                    if mid in markers:
                        problems.append(f'{model._meta.label} id={doc["id"]}: takroriy unique ({mid.split(":")[0]}) '
                                        f'— id={markers[mid]["ref"]} bilan')
                        continue
                    markers[mid] = {'id': mid, 'coll': model._meta.collection, 'ref': doc['id']}
        return per_model, list(markers.values()), _blacklist_docs(conn), problems
    finally:
        conn.close()


def run_import(store, sqlite_path):
    per_model, markers, blacklist, problems = plan_import(sqlite_path)
    if problems:
        return problems, {}
    counts = {}
    for model, docs, counter in per_model:
        coll = model._meta.collection
        if docs:
            store.commit([Create(coll, d['id'], d) for d in docs])
        if counter:
            store.bump_counter(coll, counter)
        counts[model._meta.label] = len(docs)
    if markers:
        store.commit([Create(UNIQUE, m['id'], m) for m in markers])
    if blacklist:
        store.commit([Set('token_blacklist', d['id'], d) for d in blacklist])
    store.commit([Set(*SEEDED, {'id': SEEDED[1], 'source': 'import_sqlite',
                                'at': datetime.now(timezone.utc)})])
    counts['_unique'] = len(markers)
    counts['token_blacklist'] = len(blacklist)
    return [], counts


def _comparable(doc):
    out = {}
    for key, value in doc.items():
        if isinstance(value, datetime):
            value = value.astimezone(timezone.utc).isoformat()
        out[key] = value
    return out


def verify(store, sqlite_path):
    """Compare every SQLite row with the stored document. Returns a list of differences."""
    per_model, markers, _, problems = plan_import(sqlite_path)
    diffs = list(problems)
    for model, docs, counter in per_model:
        coll = model._meta.collection
        stored = {d['id']: d for d in store.query(coll)}
        if len(stored) != len(docs):
            diffs.append(f'{coll}: soni {len(stored)} != {len(docs)}')
        for doc in docs:
            got = stored.get(doc['id'])
            if got is None:
                diffs.append(f'{coll} id={doc["id"]}: yo\'q')
            elif _comparable(got) != _comparable(doc):
                bad = sorted(k for k in set(doc) | set(got) if _comparable(doc).get(k) != _comparable(got).get(k))
                diffs.append(f'{coll} id={doc["id"]}: farq {bad}')
    stored_markers = {m['id'] for m in store.query(UNIQUE)}
    missing = [m['id'] for m in markers if m['id'] not in stored_markers]
    if missing:
        diffs.append(f'_unique: {len(missing)} ta marker yo\'q')
    return diffs
