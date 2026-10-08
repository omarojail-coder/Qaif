"""Small transactional SQLite repository. Every mutation has an audit record."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f'{prefix}-{uuid4().hex[:10]}'


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'qaif.sqlite3'
        with self.connect() as db:
            db.executescript('''
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS entities(kind TEXT, id TEXT, body TEXT NOT NULL,
                PRIMARY KEY(kind,id));
              CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT, actor TEXT,
                kind TEXT, entity_id TEXT, action TEXT, detail TEXT);
              CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT, expires REAL);
              CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, role TEXT, salt TEXT, hash TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def all(self, kind):
        with self.connect() as db:
            return [json.loads(r['body']) for r in db.execute(
                'SELECT body FROM entities WHERE kind=? ORDER BY rowid DESC', (kind,))]

    def get(self, kind, entity_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM entities WHERE kind=? AND id=?', (kind, entity_id)).fetchone()
            return json.loads(row['body']) if row else None

    def put(self, kind, value, actor='system', action='update'):
        value = {**value, 'updated_at': now()}
        with self.connect() as db:
            self.write(db, kind, value, actor, action)
        return value

    @staticmethod
    def write(db, kind, value, actor, action):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False)
        db.execute('INSERT INTO entities VALUES(?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body',
                   (kind, value['id'], body))
        db.execute('INSERT INTO audit(at,actor,kind,entity_id,action,detail) VALUES(?,?,?,?,?,?)',
                   (now(), actor, kind, value['id'], action, body))

    def transition(self, kind, entity_id, target, allowed, changes, actor):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT body FROM entities WHERE kind=? AND id=?', (kind, entity_id)).fetchone()
            if not row:
                raise KeyError(entity_id)
            value = json.loads(row['body'])
            if target not in allowed.get(value['status'], []):
                raise ValueError('الانتقال المطلوب غير مسموح في الحالة الحالية')
            value.update(changes)
            value.update(status=target, updated_at=now())
            self.write(db, kind, value, actor, f'transition:{target}')
            return value

    def history(self, entity_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT id,at,actor,kind,entity_id,action FROM audit WHERE entity_id=? ORDER BY id DESC LIMIT 100',
                (entity_id,))]
