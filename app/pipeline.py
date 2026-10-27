import json
from pathlib import Path
from app.discover import discover
from app.facts import refresh as refresh_facts
from app.extract import extract, ExtractionPool
from app.guard import enable_offline, sha256
from app.represent import Representer
from app.store import Store


def index(config, store=None, progress=None, rebuild=False, retry_failed=False):
    enable_offline()
    owned = store is None
    store = store or Store(config)
    pool = ExtractionPool(config)
    try:
        if retry_failed:
            store.db.execute("DELETE FROM documents WHERE file_id IN (SELECT file_id FROM files WHERE status='quarantined')")
            store.db.execute("UPDATE files SET status='present',failures=0 WHERE status='quarantined'")
            store.audit('extract', 'retry_requested')
            store.db.commit()
        if rebuild:
            store.db.execute("DELETE FROM documents WHERE file_id IN (SELECT file_id FROM files WHERE status='present')")
            store.db.execute('UPDATE clusters SET stale=1')
            store.audit('represent', 'rebuild_requested')
            store.db.commit()
        changed = discover(config, store)
        files = store.rows('''SELECT f.* FROM files f LEFT JOIN documents d ON d.file_id=f.file_id
            WHERE f.status='present' AND f.parent_file_id IS NULL AND d.document_id IS NULL''')
        if not files:
            refresh_facts(store)
            return {'changed': len(changed), 'indexed': 0, 'failed': 0}
        representer = Representer(config)  # Fail closed; never silently substitute lexical vectors.
        manifest = config.models / 'manifest.json'
        store.audit('guard', 'manifest_verified', {'sha256': sha256(manifest), 'model': representer.model_id})
        store.db.commit()
        count, failures = 0, 0
        for i, file in enumerate(files):
            if progress:
                progress(i, len(files), file['path'])
            error = None
            docs = None
            for attempt in range(2):
                try:
                    docs = extract(file, config, pool)
                    if sha256(file['path']) != file['sha256']:
                        raise ValueError('Source changed after discovery; rescan required')
                    break
                except Exception as exc:
                    docs = None
                    error = str(exc)
                    store.db.execute('UPDATE files SET failures=failures+1 WHERE file_id=?', (file['file_id'],))
                    store.audit('extract', 'failure', {'file_id': file['file_id'], 'attempt': attempt + 1, 'error': error})
                    store.db.commit()
            if docs is None:
                failures += 1
                store.db.execute("UPDATE files SET status='quarantined' WHERE file_id=?", (file['file_id'],))
                store.db.execute('INSERT INTO documents(file_id,title,text,text_sha256,extractor,extraction_status,provenance_json) VALUES(?,?,?,?,?,?,?)', (file['file_id'], Path(file['path']).name, '', '', 'none', 'failed:' + str(error)[:500], json.dumps({'attempts': 2})))
                store.audit('extract', 'quarantined', {'file_id': file['file_id'], 'error': error})
                store.db.commit()
                continue
            path_ids = {file['path']: file['file_id']}
            try:
                for doc in docs:
                    parent = doc.metadata.get('parent_path')
                    file_id = file['file_id']
                    if parent:
                        store.db.execute('''INSERT INTO files(root_id,path,size,mtime,sha256,magika_label,parent_file_id,status)
                        VALUES(?,?,?,?,?,?,?,'present') ON CONFLICT(path) DO UPDATE SET size=excluded.size,sha256=excluded.sha256,
                        magika_label=excluded.magika_label,parent_file_id=excluded.parent_file_id,status='present' ''',
                        (file['root_id'], doc.source_path, doc.metadata.get('size', 0), file['mtime'],
                         doc.metadata.get('byte_sha256'), doc.detected_type, path_ids[parent]))
                        file_id = store.one('SELECT file_id FROM files WHERE path=?', (doc.source_path,))['file_id']
                        path_ids[doc.source_path] = file_id
                    doc.file_id = file_id
                    doc.parent_file_id = path_ids.get(parent)
                    vectors, mean, tags = representer.represent(doc)
                    store.db.execute('DELETE FROM documents WHERE file_id=?', (file_id,))
                    cur = store.db.execute('''INSERT INTO documents(file_id,title,text,text_sha256,language,extractor,ocr_used,
                    extraction_status,provenance_json,sections_json,tables_json,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (file_id, doc.title, doc.normalized_text, doc.text_sha256, doc.language, doc.extractor, doc.ocr_used,
                     doc.extraction_status, json.dumps({**doc.processing_provenance, 'embedding_model': representer.model_id}),
                     json.dumps(doc.sections), json.dumps(doc.tables), json.dumps(doc.metadata)))
                    document_id = cur.lastrowid
                    for ordinal, (chunk, vector) in enumerate(zip(doc.chunks, vectors)):
                        chunk_id = store.db.execute('INSERT INTO chunks(document_id,ordinal,text,section_path,page,token_count) VALUES(?,?,?,?,?,?)',
                            (document_id, ordinal, chunk['text'], chunk.get('section_path', ''), chunk.get('page'), chunk.get('token_count', 0))).lastrowid
                        store.db.execute('INSERT INTO embeddings VALUES(?,?,?,?,?)', (chunk_id, document_id, representer.model_id, len(vector), vector.tobytes()))
                    if mean is not None:
                        store.db.execute('INSERT INTO embeddings VALUES(NULL,?,?,?,?)', (document_id, representer.model_id, len(mean), mean.tobytes()))
                    store.db.executemany('INSERT INTO tags VALUES(?,?,?)', [(document_id, tag, 'keyword') for tag in tags])
                    store.audit('extract', 'complete', {'file_id': file_id, 'status': doc.extraction_status, 'extractor': doc.extractor})
                    store.audit('represent', 'complete', {'document_id': document_id, 'chunks': len(doc.chunks), 'model_id': representer.model_id})
                    count += 1
                store.db.commit()
            except Exception:
                store.db.rollback()
                raise
        refresh_facts(store)
        return {'changed': len(changed), 'indexed': count, 'failed': failures}
    finally:
        pool.close()
        if owned:
            store.close()
