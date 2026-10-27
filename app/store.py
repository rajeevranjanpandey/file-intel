import hashlib
import json
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath
from app import BASE
from app.guard import sha256, resolve_source
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS files(
 file_id INTEGER PRIMARY KEY, root_id TEXT, path TEXT UNIQUE, size INTEGER, mtime INTEGER,
 permissions INTEGER, sha256 TEXT, magika_label TEXT, magika_confidence REAL,
 parent_file_id INTEGER REFERENCES files, status TEXT DEFAULT 'present', failures INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS documents(
 document_id INTEGER PRIMARY KEY, file_id INTEGER UNIQUE REFERENCES files ON DELETE CASCADE,
 title TEXT, text TEXT, text_sha256 TEXT, language TEXT, extractor TEXT, ocr_used INTEGER,
 extraction_status TEXT, provenance_json TEXT, sections_json TEXT, tables_json TEXT, metadata_json TEXT);
CREATE INDEX IF NOT EXISTS text_hash ON documents(text_sha256);
CREATE TABLE IF NOT EXISTS chunks(
 chunk_id INTEGER PRIMARY KEY, document_id INTEGER REFERENCES documents ON DELETE CASCADE,
 ordinal INTEGER, text TEXT, section_path TEXT, page INTEGER, token_count INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content=chunks, content_rowid=chunk_id);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
 INSERT INTO chunks_fts(rowid,text) VALUES(new.chunk_id,new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
 INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.chunk_id,old.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
 INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.chunk_id,old.text);
 INSERT INTO chunks_fts(rowid,text) VALUES(new.chunk_id,new.text); END;
CREATE TABLE IF NOT EXISTS embeddings(
 chunk_id INTEGER UNIQUE REFERENCES chunks ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents ON DELETE CASCADE, model_id TEXT, dim INTEGER, vector BLOB);
CREATE TABLE IF NOT EXISTS duplicates(
 left_id INTEGER REFERENCES documents ON DELETE CASCADE, right_id INTEGER REFERENCES documents ON DELETE CASCADE,
 tier INTEGER, score REAL, evidence_json TEXT, reviewed_at TEXT, decision TEXT,
 PRIMARY KEY(left_id,right_id));
CREATE TABLE IF NOT EXISTS clusters(
 cluster_id INTEGER PRIMARY KEY, run_id TEXT, label INTEGER, keyword_label TEXT, llm_name TEXT,
 llm_summary TEXT, llm_tags_json TEXT, evidence_json TEXT, confidence REAL, stale INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cluster_members(
 cluster_id INTEGER REFERENCES clusters, document_id INTEGER REFERENCES documents ON DELETE CASCADE, membership_prob REAL);
CREATE TABLE IF NOT EXISTS tags(document_id INTEGER REFERENCES documents ON DELETE CASCADE, tag TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS actions(
 action_id INTEGER PRIMARY KEY, kind TEXT, src TEXT, dst TEXT, status TEXT, proposed_by TEXT,
 approved_by TEXT, executed_at TEXT, undo_path TEXT, src_sha256 TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS scan_runs(run_id INTEGER PRIMARY KEY, root_id TEXT, started TEXT, finished TEXT,
 files_seen INTEGER, files_changed INTEGER, errors INTEGER);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, component TEXT,
 action TEXT, details_json TEXT, prev_hash TEXT, row_hash TEXT);
CREATE TABLE IF NOT EXISTS models(model_id TEXT PRIMARY KEY, kind TEXT, path TEXT, sha256 TEXT, licence TEXT, source TEXT);
'''

class Store:
    def __init__(self, config):
        config.validate()
        config.data.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(config.data / 'index.sqlite', timeout=60)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(SCHEMA)
        manifest = config.models / 'manifest.json'
        if manifest.is_file():
            for model_id, entry in json.loads(manifest.read_text()).get('models', {}).items():
                digest = hashlib.sha256(canonical(entry).encode()).hexdigest()
                existing = self.one('SELECT sha256 FROM models WHERE model_id=?', (model_id,))
                if existing and existing['sha256'] == digest:
                    continue  # Opening a page should not need a database write lock.
                self.db.execute('INSERT OR REPLACE INTO models VALUES(?,?,?,?,?,?)',
                    (model_id, model_id, entry['path'], digest,
                     entry.get('licence', ''), entry.get('source', '')))
        self.db.commit()
        self._relocate_project_roots(config)

    def _relocate_project_roots(self, config):
        """Relink a moved project only after every present source matches its saved hash."""
        for row in self.rows('SELECT DISTINCT root_id FROM files WHERE root_id IS NOT NULL'):
            old_root = row['root_id']
            if old_root in {str(r) for r in config.roots} or Path(old_root).is_dir():
                continue
            path_type = PureWindowsPath if '\\' in old_root or old_root[1:2] == ':' else PurePosixPath
            old = path_type(old_root)
            if not old.is_absolute():
                continue
            candidates = []
            for root in config.roots:
                if not root.is_relative_to(BASE) or not root.is_dir():
                    continue
                relative = root.relative_to(BASE).parts
                if relative and tuple(old.parts[-len(relative):]) == relative:
                    candidates.append(root)
            if len(candidates) != 1:
                continue
            root = candidates[0]
            # Existing approvals and undo locations belong to their original machine.
            actions = self.rows("SELECT src,dst FROM actions WHERE status IN ('proposed','approved','executing','undoing','executed')")
            if any(any(value and path_type(value).is_relative_to(old) for value in action.values()) for action in actions):
                continue
            files = self.rows('SELECT * FROM files WHERE root_id=?', (old_root,))
            paths = {}
            try:
                for file in files:
                    physical, separator, member = file['path'].partition('::')
                    candidate = root.joinpath(*path_type(physical).relative_to(old).parts)
                    if file['parent_file_id'] is None and file['status'] in ('present', 'quarantined'):
                        candidate = resolve_source(candidate, [root])
                        if not candidate.is_file() or candidate.is_symlink() or sha256(candidate) != file['sha256']:
                            raise ValueError('Source bytes differ or are unavailable')
                    new_path = str(candidate) + (separator + member if separator else '')
                    collision = self.one('SELECT file_id FROM files WHERE path=?', (new_path,))
                    if collision and collision['file_id'] != file['file_id']:
                        raise ValueError('Destination already indexed')
                    paths[file['path']] = new_path
            except (OSError, ValueError):
                continue
            try:
                for file in files:
                    self.db.execute('UPDATE files SET root_id=?,path=? WHERE file_id=?',
                                    (str(root), paths[file['path']], file['file_id']))
                    document = self.one('SELECT document_id,metadata_json FROM documents WHERE file_id=?', (file['file_id'],))
                    if document and document['metadata_json']:
                        metadata = json.loads(document['metadata_json'])
                        if metadata.get('parent_path') in paths:
                            metadata['parent_path'] = paths[metadata['parent_path']]
                            self.db.execute('UPDATE documents SET metadata_json=? WHERE document_id=?',
                                            (json.dumps(metadata), document['document_id']))
                self.audit('store', 'project_relocated', {'previous_root': old_root, 'root': str(root), 'files': len(files)})
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]
    def one(self, sql, args=()):
        row = self.db.execute(sql, args).fetchone()
        return dict(row) if row else None
    def audit(self, component, action, details=None, actor='system'):
        # Serialize chain updates together with their surrounding transaction.
        if not self.db.in_transaction:
            self.db.execute('BEGIN IMMEDIATE')
        previous = self.one('SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1')
        previous = previous['row_hash'] if previous else '0' * 64
        values = {'ts': now(), 'actor': actor, 'component': component, 'action': action,
                  'details_json': canonical(details or {})}
        digest = hashlib.sha256((previous + canonical(values)).encode()).hexdigest()
        self.db.execute('INSERT INTO audit_log(ts,actor,component,action,details_json,prev_hash,row_hash) VALUES(?,?,?,?,?,?,?)',
                        (*values.values(), previous, digest))
    def verify_audit(self):
        previous = '0' * 64
        for row in self.rows('SELECT * FROM audit_log ORDER BY id'):
            values = {k: row[k] for k in ('ts', 'actor', 'component', 'action', 'details_json')}
            digest = hashlib.sha256((previous + canonical(values)).encode()).hexdigest()
            if row['prev_hash'] != previous or row['row_hash'] != digest:
                return False
            previous = digest
        return True
    def close(self):
        self.db.close()
