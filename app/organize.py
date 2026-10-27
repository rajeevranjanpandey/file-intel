"""Read-only folder planning from semantic clusters and filesystem dates."""
from datetime import datetime
from pathlib import Path
import re

from app.guard import resolve_source, sha256

DATE_FORMATS = {'YYYY-MM': '%Y-%m', 'YYYY-MM-DD': '%Y-%m-%d', 'YYYY/MM': '%Y/%m', 'YYYY': '%Y'}
LAYOUTS = ['Same content', 'Content topic / Date', 'Date / Content topic', 'Content topic', 'Date', 'Single folder']


def folder_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', value).strip(' .')[:80]
    if not value or value in ('.', '..', '.file-intel-trash'):
        raise ValueError('Enter a usable folder name.')
    return value


def plan(store, config, root, name, layout='Content topic / Date', date_format='YYYY-MM', include_unsorted=False,
         selected_paths=None):
    if layout not in LAYOUTS or date_format not in DATE_FORMATS:
        raise ValueError('Unknown folder layout or date format')
    destination = resolve_source(Path(root) / folder_name(name), config.roots)
    if '.file-intel-trash' in destination.parts or (destination.exists() and not destination.is_dir()):
        raise ValueError('Destination must be a folder outside quarantine')
    topical = 'Content topic' in layout
    groups = store.rows('SELECT * FROM clusters WHERE run_id=(SELECT max(run_id) FROM clusters)')
    if topical and (not groups or any(g['stale'] for g in groups)):
        raise ValueError('Refresh content groups before preparing a topic-based plan.')
    topics = {}
    used_names = set()
    for group in groups:
        if group['label'] == -1:
            continue
        label = group['llm_name'] or group['keyword_label'] or 'Related documents'
        title = folder_name(' '.join(label.split(',')[:3]) if ',' in label else label)
        title = re.sub(r'\s+', ' ', title).strip().title()
        # Distinct clusters must not silently merge when generated names coincide.
        if title.casefold() in used_names:
            title += f" ({group['cluster_id']})"
        used_names.add(title.casefold())
        for member in store.rows('SELECT document_id FROM cluster_members WHERE cluster_id=?', (group['cluster_id'],)):
            topics[member['document_id']] = title
    rows = store.rows('''SELECT f.path,f.mtime,f.sha256,d.document_id,d.text,d.text_sha256,d.extraction_status
        FROM files f JOIN documents d USING(file_id)
        WHERE f.status='present' AND f.parent_file_id IS NULL ORDER BY f.path''')
    if selected_paths is not None:
        selected = {str(resolve_source(p, config.roots)) for p in selected_paths}
        rows = [row for row in rows if row['path'] in selected]
    reserved = {r['path'].casefold() for r in store.rows('SELECT path FROM files')}
    reserved.update(r['dst'].casefold() for r in store.rows("SELECT dst FROM actions WHERE status IN ('proposed','approved','executing') AND dst IS NOT NULL"))
    pending = {r['src'] for r in store.rows("SELECT src FROM actions WHERE status IN ('proposed','approved','executing','undoing')")}
    eligible = []
    for row in rows:
        source = resolve_source(row['path'], config.roots)
        if source.is_relative_to(destination) or str(source) in pending or not source.is_file():
            continue
        eligible.append(row)
    if layout == 'Same content':
        matches = {}
        for row in eligible:
            # Empty, partial, or failed extraction cannot prove full-text equality.
            if row['extraction_status'] != 'ok' or not row['text_sha256'] or not (row['text'] or '').strip():
                continue
            if not row['sha256'] or sha256(row['path']) != row['sha256']:
                raise ValueError('A selected file changed. Scan & Index again before grouping the same content.')
            matches.setdefault(row['text_sha256'], []).append(row)
        topics = {}
        used_names = set()
        for digest, members in matches.items():
            if len(members) < 2:
                continue
            title = folder_name(Path(members[0]['path']).stem.replace('_', ' ').replace('-', ' ')).title()
            if title.casefold() in used_names:
                title += f' ({digest[:8]})'
            used_names.add(title.casefold())
            for member in members:
                topics[member['document_id']] = title
    result = []
    for row in eligible:
        source = Path(row['path'])
        topic = topics.get(row['document_id'], 'Unsorted')
        if layout == 'Same content' and row['document_id'] not in topics:
            continue
        if topical and topic == 'Unsorted' and not include_unsorted:
            continue
        stamp = datetime.fromtimestamp(row['mtime'] / 1e9).strftime(DATE_FORMATS[date_format])
        parts = {'Same content': [topic], 'Content topic / Date': [topic, stamp], 'Date / Content topic': [stamp, topic],
                 'Content topic': [topic], 'Date': [stamp], 'Single folder': []}[layout]
        target = destination.joinpath(*parts, source.name)
        number = 2
        while target.exists() or str(target).casefold() in reserved:
            target = target.with_name(f'{source.stem} ({number}){source.suffix}')
            number += 1
        target = resolve_source(target, config.roots)
        reserved.add(str(target).casefold())
        result.append({'Source': str(source), 'Destination': str(target),
                       'Content group' if layout == 'Same content' else 'Content topic': topic,
                       'Modified date': datetime.fromtimestamp(row['mtime'] / 1e9).strftime('%Y-%m-%d')})
    return result
