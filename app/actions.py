"""The only source-writing module. All operations require explicit persisted approval."""
import os
import sys
from app.guard import resolve_source, sha256
from app.store import now


def propose(store, config, kind, src, dst=None, actor='user'):
    if kind not in ('move', 'rename', 'delete'):
        raise ValueError('Supported actions: move, rename, delete (soft-delete)')
    source = resolve_source(src, config.roots)
    if not source.is_file() or '.file-intel-trash' in source.parts:
        raise ValueError('Source must be a regular file outside quarantine')
    if kind != 'delete':
        destination = resolve_source(dst, config.roots)
        if destination.exists() or destination == source or '.file-intel-trash' in destination.parts:
            raise ValueError('Destination exists or is reserved')
        if store.one('SELECT file_id FROM files WHERE path=?', (str(destination),)):
            raise ValueError('Destination is reserved by an indexed file; choose a new path')
        if kind == 'rename' and source.parent != destination.parent:
            raise ValueError('Rename must remain in the same directory')
    else:
        destination = None
    digest = sha256(source)
    action_id = store.db.execute('''INSERT INTO actions(kind,src,dst,status,proposed_by,src_sha256)
       VALUES(?,?,?,'proposed',?,?)''', (kind, str(source), str(destination) if destination else None, actor, digest)).lastrowid
    if kind == 'delete':
        root = next(r for r in config.roots if source.is_relative_to(r))
        destination = root / '.file-intel-trash' / str(action_id) / source.name
        store.db.execute('UPDATE actions SET dst=? WHERE action_id=?', (str(destination), action_id))
    store.audit('actions', 'proposed', {'action_id': action_id, 'kind': kind, 'src': str(source), 'dst': str(destination)}, actor)
    store.db.commit()
    return action_id


def approve(store, action_id, actor='user'):
    if not actor.strip() or actor in ('llm', 'system'):
        raise ValueError('A human actor is required')
    count = store.db.execute("UPDATE actions SET status='approved',approved_by=? WHERE action_id=? AND status='proposed'", (actor, action_id)).rowcount
    if count != 1:
        raise ValueError('Only proposed actions can be approved')
    store.audit('actions', 'approved', {'action_id': action_id}, actor)
    store.db.commit()


def reject(store, action_id, actor='user'):
    count = store.db.execute("UPDATE actions SET status='rejected' WHERE action_id=? AND status IN ('proposed','approved')", (action_id,)).rowcount
    if count != 1:
        raise ValueError('Only pending actions can be rejected')
    store.audit('actions', 'rejected', {'action_id': action_id}, actor)
    store.db.commit()


def _move_exclusive(src, dst):
    """Atomic, no-overwrite rename on the deployment target. No cross-device copying."""
    if sys.platform == 'darwin':
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.renamex_np(os.fsencode(src), os.fsencode(dst), 0x00000004) != 0:  # RENAME_EXCL
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    elif sys.platform == 'linux':
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.renameat2(-100, os.fsencode(src), -100, os.fsencode(dst), 1) != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
    elif sys.platform == 'win32':
        os.rename(src, dst)  # Windows rename fails if destination exists.
    else:
        raise ValueError('No safe exclusive rename implementation for this platform')


def _update_index(store, src, dst, kind, config):
    row = store.one('SELECT file_id FROM files WHERE path=?', (str(src),))
    if row:
        if kind == 'delete':
            store.db.execute("UPDATE files SET status='missing' WHERE file_id=? OR instr(path,?)=1", (row['file_id'], str(src) + '::'))
        else:
            paths = store.rows('SELECT file_id,path FROM files WHERE file_id=? OR instr(path,?)=1', (row['file_id'], str(src) + '::'))
            for file in paths:
                new_path = str(dst) + file['path'][len(str(src)):]
                store.db.execute("UPDATE files SET path=?,root_id=?,status='present' WHERE file_id=?", (new_path, str(next(r for r in config.roots if dst.is_relative_to(r))), file['file_id']))
        store.db.execute('UPDATE clusters SET stale=1')


def apply(store, config, action_id):
    store.db.execute('BEGIN IMMEDIATE')
    try:
        action = store.one('SELECT * FROM actions WHERE action_id=?', (action_id,))
        if not action or action['status'] != 'approved':
            raise ValueError('Action must be approved first')
        src = resolve_source(action['src'], config.roots)
        dst = resolve_source(action['dst'], config.roots)
        if not src.is_file() or sha256(src) != action['src_sha256']:
            raise ValueError('Source changed since proposal')
        if store.one('SELECT file_id FROM files WHERE path=?', (str(dst),)):
            raise ValueError('Destination is reserved by an indexed file')
        if dst.exists():
            raise ValueError('Destination already exists')
        dst.parent.mkdir(parents=True, exist_ok=True)
        resolve_source(dst, config.roots)
        if src.stat().st_dev != dst.parent.stat().st_dev:
            raise ValueError('Cross-device moves are disabled; choose a destination on the same volume')
        store.db.execute("UPDATE actions SET status='executing',undo_path=? WHERE action_id=?", (str(src), action_id))
        store.audit('actions', 'execution_intent', {'action_id': action_id})
        store.db.commit()  # Durable intent before the filesystem mutation.
        _move_exclusive(src, dst)
        store.db.execute("UPDATE actions SET status='executed',executed_at=? WHERE action_id=?", (now(), action_id))
        _update_index(store, src, dst, action['kind'], config)
        store.audit('actions', 'executed', {'action_id': action_id})
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise


def undo(store, config, action_id):
    store.db.execute('BEGIN IMMEDIATE')
    try:
        action = store.one('SELECT * FROM actions WHERE action_id=?', (action_id,))
        if not action or action['status'] != 'executed':
            raise ValueError('Only executed actions can be undone')
        original = resolve_source(action['src'], config.roots)
        current = resolve_source(action['dst'], config.roots)
        if original.exists() or not current.is_file() or sha256(current) != action['src_sha256']:
            raise ValueError('Undo blocked: path occupied or moved file changed')
        original.parent.mkdir(parents=True, exist_ok=True)
        store.db.execute("UPDATE actions SET status='undoing' WHERE action_id=?", (action_id,))
        store.audit('actions', 'undo_intent', {'action_id': action_id})
        store.db.commit()
        _move_exclusive(current, original)
        if action['kind'] == 'delete':
            store.db.execute("UPDATE files SET status='present' WHERE path=? OR instr(path,?)=1", (str(original), str(original) + '::'))
        else:
            _update_index(store, current, original, 'move', config)
        store.db.execute("UPDATE actions SET status='undone' WHERE action_id=?", (action_id,))
        store.audit('actions', 'undone', {'action_id': action_id})
        store.db.commit()
    except Exception:
        store.db.rollback()
        raise


def recover(store, config):
    """Reconcile durable intents after an interrupted process without guessing ambiguous states."""
    result = []
    for action in store.rows("SELECT * FROM actions WHERE status IN ('executing','undoing')"):
        src = resolve_source(action['src'], config.roots)
        dst = resolve_source(action['dst'], config.roots)
        at_src = src.is_file() and sha256(src) == action['src_sha256']
        at_dst = dst.is_file() and sha256(dst) == action['src_sha256']
        if at_src == at_dst:
            result.append({'id': action['action_id'], 'status': 'ambiguous; inspect paths'})
            continue
        if action['status'] == 'executing':
            state = 'executed' if at_dst else 'approved'
            if at_dst:
                _update_index(store, src, dst, action['kind'], config)
        else:
            state = 'undone' if at_src else 'executed'
            if at_src:
                if action['kind'] == 'delete':
                    store.db.execute("UPDATE files SET status='present' WHERE path=?", (str(src),))
                else:
                    _update_index(store, dst, src, 'move', config)
        store.db.execute('UPDATE actions SET status=? WHERE action_id=?', (state, action['action_id']))
        store.audit('actions', 'recovered', {'action_id': action['action_id'], 'state': state})
        result.append({'id': action['action_id'], 'status': state})
    store.db.commit()
    return result
