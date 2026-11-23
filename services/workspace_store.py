"""Local persistence for projects, immutable job specifications, recipes, and text search."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import time
import uuid

from utils.app_config import AppConfig


def data_directory():
    path = Path(os.environ.get('ODT_DATA_DIR') or AppConfig.load_config().get('workspace_directory') or AppConfig.CONFIG_FILE.parent / 'workspace').expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


class WorkspaceStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / 'workspace.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    document TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                    recipe TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    state TEXT NOT NULL, spec TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '', result TEXT, error TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0, owner TEXT, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS job_state ON jobs(state,created);
                CREATE TABLE IF NOT EXISTS lease(id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT, heartbeat REAL);
                CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL, page_count INTEGER NOT NULL, indexed REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS document_labels(document_id INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('tag','collection')), value TEXT NOT NULL,
                    PRIMARY KEY(document_id,kind,value),
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE);
                CREATE VIRTUAL TABLE IF NOT EXISTS document_text USING fts5(document_id UNINDEXED,
                    page UNINDEXED, text, tokenize='unicode61');
            ''')
            columns={row[1] for row in db.execute('PRAGMA table_info(documents)')}
            for name in ['file_size','modified_ns']:
                if name not in columns:db.execute(f'ALTER TABLE documents ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0')
            db.execute('PRAGMA user_version=3')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout=10000')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_project(self, name, document, project_id=None):
        project_id = project_id or uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'name=excluded.name,document=excluded.document,updated=excluded.updated',
                       (project_id, name, json.dumps(document), time.time()))
        return project_id

    def projects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,name,updated FROM projects ORDER BY updated DESC')]

    def project(self, project_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
            if row is None:
                raise KeyError('Project no longer exists')
            return json.loads(row['document'])

    def save_workflow(self, name, recipe):
        from services.workflow_service import validate_recipe
        recipe = validate_recipe(recipe)
        if not name.strip():
            raise ValueError('Give the workflow a name.')
        with self.connect() as db:
            db.execute('INSERT INTO workflows VALUES(?,?,?,?) ON CONFLICT(name) DO UPDATE SET '
                       'recipe=excluded.recipe,updated=excluded.updated',
                       (uuid.uuid4().hex, name.strip(), json.dumps(recipe), time.time()))

    def workflows(self):
        with self.connect() as db:
            return [{**dict(row), 'recipe':json.loads(row['recipe'])}
                    for row in db.execute('SELECT * FROM workflows ORDER BY name')]

    def enqueue(self, title, spec):
        job_id, now = uuid.uuid4().hex, time.time()
        # JSON serialization also freezes mutable GUI state before it can change.
        with self.connect() as db:
            db.execute('INSERT INTO jobs(id,title,state,spec,created,updated) VALUES(?,?,?,?,?,?)',
                       (job_id, title, 'queued', json.dumps(spec), now, now))
        return job_id

    def jobs(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY created DESC')]

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:
                raise KeyError('Job no longer exists')
            value = dict(row)
            value['spec'] = json.loads(value['spec'])
            value['result'] = json.loads(value['result']) if value['result'] else None
            return value

    def acquire(self, owner, stale_after=20):
        """A single queue leader; other app instances can still enqueue and inspect."""
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM lease WHERE id=1').fetchone()
            if row and row['owner'] != owner and row['heartbeat'] > now - stale_after:
                return False
            db.execute('INSERT INTO lease VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'owner=excluded.owner,heartbeat=excluded.heartbeat',(owner,now))
            db.execute("UPDATE jobs SET state='interrupted',owner=NULL,message='Interrupted; resume from checkpoint',"
                       "updated=? WHERE state='running' AND (owner IS NULL OR owner<>?)",(now,owner))
        return True

    def claim(self, owner):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            lease = db.execute('SELECT owner FROM lease WHERE id=1').fetchone()
            if not lease or lease['owner'] != owner:
                return None
            db.execute('UPDATE lease SET heartbeat=? WHERE id=1',(time.time(),))
            row = db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='running',owner=?,attempts=attempts+1,updated=? WHERE id=?",
                       (owner,time.time(),row['id']))
            job_id = row['id']
        return self.job(job_id)

    def update_job(self, job_id, **changes):
        allowed = {'state','progress','message','error','result','owner'}
        if not changes or not set(changes) <= allowed:
            raise ValueError('Invalid job update')
        if 'result' in changes:
            changes['result'] = json.dumps(changes['result'])
        changes['updated'] = time.time()
        with self.connect() as db:
            db.execute('UPDATE jobs SET ' + ','.join(key+'=?' for key in changes) + ' WHERE id=?',
                       (*changes.values(),job_id))

    def retry(self, job_id):
        with self.connect() as db:
            changed = db.execute("UPDATE jobs SET state='queued',error='',message='Resuming from checkpoint',"
                                 "updated=? WHERE id=? AND state IN ('failed','paused','cancelled','interrupted','needs_review')",
                                 (time.time(),job_id)).rowcount
        if not changed:
            raise ValueError('Only stopped or failed jobs can be resumed.')

    def release(self, owner):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='interrupted',owner=NULL,updated=? WHERE state='running' AND owner=?",
                       (time.time(),owner))
            db.execute('DELETE FROM lease WHERE owner=?',(owner,))

    def index_document(self, path, fingerprint, page_texts):
        path = str(Path(path).resolve())
        stat=Path(path).stat() if Path(path).is_file() else None
        with self.connect() as db:
            db.execute('INSERT INTO documents(path,fingerprint,page_count,indexed) VALUES(?,?,?,?) '
                       'ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint,'
                       'page_count=excluded.page_count,indexed=excluded.indexed',
                       (path,fingerprint,len(page_texts),time.time()))
            db.execute('UPDATE documents SET file_size=?,modified_ns=? WHERE path=?',(stat.st_size if stat else 0,stat.st_mtime_ns if stat else 0,path))
            doc_id = db.execute('SELECT id FROM documents WHERE path=?',(path,)).fetchone()[0]
            db.execute('DELETE FROM document_text WHERE document_id=?',(doc_id,))
            db.executemany('INSERT INTO document_text(document_id,page,text) VALUES(?,?,?)',
                           [(doc_id,index+1,text) for index,text in enumerate(page_texts)])

    def search(self, query, limit=100, tag='', collection=''):
        filters, parameters = [], []
        for kind, value in [('tag', tag), ('collection', collection)]:
            if value:
                filters.append('EXISTS(SELECT 1 FROM document_labels l WHERE l.document_id=documents.id AND l.kind=? AND l.value=?)')
                parameters.extend([kind,value])
        where = (' AND ' + ' AND '.join(filters)) if filters else ''
        with self.connect() as db:
            if not query.strip():
                return [dict(row) for row in db.execute('SELECT id,path,fingerprint,page_count,indexed FROM documents WHERE 1=1'+where+
                    ' ORDER BY indexed DESC LIMIT ?',(*parameters,limit))]
            tokens = [token.replace('"','""') for token in query.split() if token]
            match = ' AND '.join('"'+token+'"' for token in tokens)
            return [dict(row) for row in db.execute('SELECT documents.id,documents.path,document_text.page,'
                "snippet(document_text,2,'[',']','…',18) AS excerpt FROM document_text "
                'JOIN documents ON documents.id=document_text.document_id WHERE document_text MATCH ?'+where+
                ' ORDER BY bm25(document_text) LIMIT ?', (match,*parameters,limit))]

    def set_labels(self,path,tags=(),collection=''):
        values = [('tag',tag.strip()) for tag in tags if tag.strip()]
        if collection.strip():values.append(('collection',collection.strip()))
        if len(values)>100 or any(len(value)>80 for _,value in values):
            raise ValueError('Use at most 100 labels of 80 characters each.')
        with self.connect() as db:
            row=db.execute('SELECT id FROM documents WHERE path=?',(str(Path(path).resolve()),)).fetchone()
            if not row:raise KeyError('Index the document before organizing it.')
            db.execute('DELETE FROM document_labels WHERE document_id=?',(row[0],))
            db.executemany('INSERT OR IGNORE INTO document_labels VALUES(?,?,?)',[(row[0],kind,value) for kind,value in values])

    def labels(self,path):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT kind,value FROM document_labels JOIN documents '
                'ON documents.id=document_labels.document_id WHERE documents.path=? ORDER BY kind,value',(str(Path(path).resolve()),))]

    def label_values(self,kind):
        with self.connect() as db:
            return [row[0] for row in db.execute('SELECT DISTINCT value FROM document_labels WHERE kind=? ORDER BY value',(kind,))]

    def duplicate_documents(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT path,fingerprint,page_count FROM documents WHERE fingerprint IN '
                '(SELECT fingerprint FROM documents GROUP BY fingerprint HAVING count(*)>1) ORDER BY fingerprint,path')]

    def delete_project(self,project_id):
        with self.connect() as db:db.execute('DELETE FROM projects WHERE id=?',(project_id,))

    def delete_job(self,job_id):
        with self.connect() as db:
            row=db.execute('SELECT state FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row and row[0] in ('running','queued'):
                raise ValueError('Stop the job before deleting its history.')
            db.execute('DELETE FROM jobs WHERE id=?',(job_id,))

    def forget_document(self, path):
        with self.connect() as db:
            row = db.execute('SELECT id FROM documents WHERE path=?',(str(Path(path).resolve()),)).fetchone()
            if row:
                db.execute('DELETE FROM document_text WHERE document_id=?',(row[0],))
                db.execute('DELETE FROM documents WHERE id=?',(row[0],))
