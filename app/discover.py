import hashlib
import os
from pathlib import Path
from app.guard import open_readonly
from app.store import now


def detect(data):
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    from magika import Magika
    if not hasattr(detect, '_model'):
        detect._model = Magika()
    result = detect._model.identify_bytes(data)
    output = result.output
    return output.label, float(result.score), getattr(output, 'mime_type', '')


def discover(config, store):
    """Incremental discovery. Never follows links or scans the soft-delete area."""
    changed = []
    for root in config.roots:
        if not root.is_dir():
            store.audit('discover', 'root_unavailable', {'root': str(root)})
            store.db.commit()
            continue  # An unmounted drive is not evidence that its files were deleted.
        started = now()
        seen, errors = set(), 0
        def onerror(exc):
            nonlocal errors
            errors += 1
            store.audit('discover', 'walk_error', {'error': str(exc)})
        root_changed = 0
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
            dirs[:] = sorted(d for d in dirs if d != '.file-intel-trash' and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                if name == '.DS_Store' or name.startswith('._'):
                    continue  # Finder metadata is not a user document.
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    continue
                seen.add(str(path))
                try:
                    stat = path.stat()
                    old = store.one('SELECT * FROM files WHERE path=?', (str(path),))
                    if old and old['size'] == stat.st_size and old['mtime'] == stat.st_mtime_ns and old['status'] in ('present', 'quarantined'):
                        continue
                    digest = hashlib.sha256()
                    sample = b''
                    with open_readonly(path, config.roots) as source:
                        for block in iter(lambda: source.read(1024 * 1024), b''):
                            if not sample:
                                sample = block
                            digest.update(block)
                    after = path.stat()
                    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError('File changed during scan; retry on next scan')
                    label, confidence, _ = detect(sample)
                    store.db.execute('''INSERT INTO files(root_id,path,size,mtime,permissions,sha256,magika_label,magika_confidence)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET root_id=excluded.root_id,size=excluded.size,mtime=excluded.mtime,
                    permissions=excluded.permissions,sha256=excluded.sha256,magika_label=excluded.magika_label,
                    magika_confidence=excluded.magika_confidence,status='present',failures=0''',
                    (str(root), str(path), stat.st_size, stat.st_mtime_ns, stat.st_mode, digest.hexdigest(), label, confidence))
                    file_id = store.one('SELECT file_id FROM files WHERE path=?', (str(path),))['file_id']
                    # Invalidate old content immediately, even when indexing is a later command.
                    store.db.execute('DELETE FROM documents WHERE file_id=?', (file_id,))
                    store.db.execute("UPDATE files SET status='missing' WHERE instr(path,?)=1 AND parent_file_id IS NOT NULL", (str(path) + '::',))
                    changed.append(file_id)
                    root_changed += 1
                except Exception as exc:
                    errors += 1
                    store.audit('discover', 'file_error', {'path': str(path), 'error': str(exc)})
        if not errors:
            for row in store.rows('SELECT file_id,path FROM files WHERE root_id=? AND parent_file_id IS NULL', (str(root),)):
                if row['path'] not in seen:
                    store.db.execute("UPDATE files SET status='missing' WHERE file_id=? OR instr(path,?)=1", (row['file_id'], row['path'] + '::'))
                    store.db.execute('UPDATE clusters SET stale=1')
        if root_changed:
            store.db.execute('UPDATE clusters SET stale=1')
        store.db.execute('INSERT INTO scan_runs(root_id,started,finished,files_seen,files_changed,errors) VALUES(?,?,?,?,?,?)',
                         (str(root), started, now(), len(seen), root_changed, errors))
        store.audit('discover', 'scan', {'root': str(root), 'seen': len(seen), 'changed': root_changed, 'errors': errors})
        store.db.commit()
    return changed
