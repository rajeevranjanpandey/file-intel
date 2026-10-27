import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.guard import enable_offline, verify_model
from app.config import load
from app.store import Store
from app import actions, BASE
import json
import re
from html import escape
from datetime import datetime
import streamlit as st
from ui.locations import location_button
from time import perf_counter

def plain_heading(value):
    return re.sub(r'([\\`*_{}\[\]()#+\-.!|>~])', r'\\\1', str(value))

def icon(name):
    paths = {
        'files': '<rect x="7" y="3" width="13" height="17" rx="3"/><path d="M4 7v13a2 2 0 0 0 2 2M11 8h5M11 12h5"/>',
        'folder': '<path d="M3 7V5a2 2 0 0 1 2-2h5l3 4h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
        'copy': '<rect x="8" y="8" width="12" height="12" rx="3"/><path d="M15 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
        'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        'check': '<path d="m8 12 3 3 5-6"/><circle cx="12" cy="12" r="9"/>',
        'spark': '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/>',
    }
    return f'<svg aria-hidden="true" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{paths[name]}</svg>'

def search_language(store, config):
    """Switch between the English model and the optional multilingual one, then rebuild the index."""
    options = {'minilm': 'English (default, fastest)', 'multilingual': 'Arabic and 50+ other languages'}
    ready = {}
    for name in options:
        try:
            verify_model(config.models, name)
            ready[name] = True
        except Exception:
            ready[name] = False
    choice = st.radio('Language for search, duplicates and collections', list(options), format_func=options.get,
                      index=list(options).index(config.embedding_model) if config.embedding_model in options else 0, key='language_choice')
    if not ready['multilingual']:
        st.caption('The multilingual model is not installed. While connected to the internet, run '
                   '`.venv/bin/python scripts/bundle_models.py --multilingual` once (about 470 MB). After that it works offline.')
    if choice == config.embedding_model:
        st.caption('This model is in use.')
        return
    if not ready[choice]:
        st.warning('Install this model first, using the command above.')
        return
    st.caption('Switching re-reads every file so that all meaning vectors come from the same model. Your files are not changed.')
    if st.button('Switch and rebuild index', icon=':material/sync:', type='primary'):
        from app.sources import set_embedding_model
        from app.pipeline import index
        from app.analyze import dedupe
        updated = set_embedding_model(choice)
        with st.spinner('Rebuilding the index on this device…'):
            index(updated, store, rebuild=True)
            dedupe(store, updated)
        st.success('Search now uses ' + options[choice] + '. Refresh collections to regroup your files.')
        st.rerun()


def quality_report():
    """Last measured evaluation, so accuracy claims are visible next to the product."""
    report_path = BASE / 'eval' / 'report.json'
    try:
        report = json.loads(report_path.read_text())
    except (OSError, ValueError):
        st.write('No evaluation has been run yet.')
        st.caption('Run `.venv/bin/python -m app.cli eval run` to measure duplicate, version, grouping and search quality.')
        return
    st.caption(report.get('corpus', ''))
    tiers = {'1': 'Exact copies', '2': 'Same text', '3': 'Edited versions', '4': 'Summaries & excerpts'}
    st.dataframe([{'Match type': tiers.get(k, k), 'Precision': v['precision'], 'Recall': v['recall'], 'Pairs expected': v['expected']}
                  for k, v in report.get('duplicate_metrics', {}).items()], hide_index=True, use_container_width=True)
    search = report.get('search') or {}
    if search:
        st.dataframe([{'Search mode': mode.title(), **values} for mode, values in search.items()], hide_index=True, use_container_width=True)
    versions = report.get('version_detection') or {}
    baseline = versions.get('cosine_threshold_baseline', {}).get(f"{report.get('semantic_threshold', 0.93):.2f}")
    if versions.get('relation_detector') and baseline:
        st.write(f"Version and summary detection · F1 {versions['relation_detector']['f1']:.2f}, "
                 f"compared with {baseline['f1']:.2f} for a cosine threshold of {report.get('semantic_threshold', 0.93):.2f} alone")
    if report.get('ask'):
        st.write(f"Ask your library · answered {report['ask']['answered']} questions · "
                 f"{report['ask']['citation_precision']:.0%} of cited passages from a relevant file ({report['ask']['mode']})")
    st.write(f"Topic grouping · adjusted Rand index {report.get('adjusted_rand_index', 0):.2f} · "
             f"purity {report.get('cluster_purity_including_noise', 0):.2f} · {report.get('noise_count', 0)} unassigned")
    st.caption('Measured on a small synthetic corpus. It shows the pipeline behaves as designed; it is not a benchmark of your library.')


def main():
    enable_offline()
    st.set_page_config(page_title='File Intel', page_icon='◈', layout='wide')
    st.markdown('<style>' + (Path(__file__).parent / 'theme.css').read_text() + '</style>', unsafe_allow_html=True)
    config = load()
    store = Store(config)
    def open_library():
        st.session_state['current_page'] = 'Overview'

    def filter_from_toolbar():
        open_library()
        st.session_state['library_view'] = 'All files'

    def scan_library(retry_failed=False):
        from app.pipeline import index
        progress = st.progress(0, text='Starting…')
        with st.spinner('Reading your documents on this device…'):
            result = index(config, store, lambda i, n, p: progress.progress(i / max(n, 1), text=Path(p).name),
                           retry_failed=retry_failed)
        progress.progress(1.0, text='Index updated')
        if result['failed']:
            st.warning(f"{result['indexed']} files indexed. {result['failed']} could not be read; see Settings for details.")
        elif not result['changed'] and not result['indexed']:
            st.success('Your library is up to date. No files have changed.')
        else:
            st.success(f"Scan complete · {result['indexed']} files indexed on this device.")

    try:
        with st.sidebar:
            st.markdown(f'<div class="brand"><span class="brand-mark">{icon("files")}</span>File Intel</div><div class="nav-label">LIBRARY</div>', unsafe_allow_html=True)
            nav = {'Overview': 'Library', 'Search': 'Search', 'Duplicates': 'Duplicates', 'Clusters': 'Collections', 'Organize': 'Organize', 'Approvals': 'Activity', 'System': 'Settings'}
            nav_icons = ['folder_open', 'search', 'content_copy', 'folder_copy', 'grid_view', 'task_alt', 'settings']
            page = st.session_state.get('current_page', 'Overview')
            for target, symbol in zip(nav, nav_icons):
                if target == 'Organize':
                    st.markdown('<div class="nav-label">MANAGE</div>', unsafe_allow_html=True)
                if st.button(nav[target], icon=f':material/{symbol}:', key='nav_' + target, use_container_width=True, type='primary' if page == target else 'secondary'):
                    st.session_state['current_page'] = target
                    if target == 'Overview':
                        st.session_state['library_view'] = 'Overview'
                    st.rerun()
            st.markdown('<div class="nav-label">LOCATIONS</div>', unsafe_allow_html=True)
            for i, root in enumerate(config.roots):
                location_button(root, config, 'sidebar_' + str(i), label=root.name)
            from ui.sources import render_connections
            render_connections(config, 'sidebar_sources')
            st.markdown('<div class="device-card"><div class="device-title">On-device intelligence</div><div class="device-status"><span>✓</span> Private processing</div><div class="device-status"><span>✓</span> Available offline</div></div>', unsafe_allow_html=True)
        with st.container(key='top_toolbar'):
            switch, finder, scan = st.columns([1.25, 2.5, 1])
            view = switch.segmented_control('Library view', ['Overview', 'All files'], default='Overview', key='library_view', on_change=open_library, label_visibility='collapsed', selection_mode='single')
            finder.text_input('Search files', placeholder='Search files · e.g. invoice, PDF', key='toolbar_filter', on_change=filter_from_toolbar, label_visibility='collapsed')
            scan_clicked = scan.button('Scan & Index', icon=':material/create_new_folder:', type='primary', use_container_width=True, key='toolbar_scan')
        if st.session_state.get('sources_notice'):
            st.success(st.session_state.pop('sources_notice'))
        if scan_clicked:
            scan_library()
        with st.container(key='page_context'):
            crumb, help_area = st.columns([4, 1])
            crumb.markdown(f'<div class="topline"><span>Workspace &nbsp; / &nbsp; {escape(nav[page])}</span></div>', unsafe_allow_html=True)
            with help_area.popover('How it works', icon=':material/info:', use_container_width=True):
                st.subheader('From files to a searchable library')
                st.markdown('<div class="workflow"><div class="stage"><strong>1 · 📥 Index</strong><p>Read your connected folders and extract searchable text.</p></div><div class="stage"><strong>2 · 🔎 Discover</strong><p>Search words and meaning. Review the matching passages.</p></div><div class="stage"><strong>3 · 🗂 Collect</strong><p>Find related content across file types and review duplicates.</p></div><div class="stage"><strong>4 · 📁 Organize</strong><p>Preview topic and date folders, then approve moves in Activity.</p></div></div>', unsafe_allow_html=True)
                st.write('Start in Library → Scan & index files. Then use Search, Collections, or Organize.')
                st.caption('Collections are suggested groups, not physical folders. Organize creates folders when approved moves run. Undo is available in Activity.')
                st.write('On-device intelligence means document text and search queries are processed by local models. Search reads the saved index; scan again after files change.')
        if page == 'Overview':
            if notice := st.session_state.pop('library_notice', None):
                st.success(notice)
            if view != 'All files':
                indexed_count = store.one("SELECT count(*) n FROM documents d JOIN files f USING(file_id) WHERE f.status='present'")['n']
                pair_count = store.one('SELECT count(*) n FROM duplicates')['n']
                st.markdown(f'<div class="intro"><h1>Your library, connected.</h1><p><b>{indexed_count} documents</b> indexed on this device, with <b>{pair_count} copies, versions and summaries</b> ready to review.</p></div>', unsafe_allow_html=True)
                stats = []
                for symbol, title, sql in zip(['files', 'copy', 'clock', 'check'], ['Indexed documents', 'Duplicate pairs', 'Pending actions', 'Extraction issues'], [
                    "SELECT count(*) n FROM documents d JOIN files f USING(file_id) WHERE f.status='present'",
                    'SELECT count(*) n FROM duplicates', "SELECT count(*) n FROM actions WHERE status IN ('proposed','approved')",
                    "SELECT count(*) n FROM files WHERE status='quarantined'"]):
                    stats.append(f'<div class="stat"><span class="stat-icon">{icon(symbol)}</span><div><div class="stat-label">{title}</div><div class="stat-value">{store.one(sql)["n"]}</div></div></div>')
                st.markdown('<div class="summary-grid">' + ''.join(stats) + '</div>', unsafe_allow_html=True)
                st.markdown('<div class="section-title">Library tools</div>', unsafe_allow_html=True)
                a, b, c = st.columns(3)
                if a.button('Scan & index files', icon=':material/create_new_folder:', type='primary', use_container_width=True):
                    scan_library()
                if b.button('Find duplicates', icon=':material/content_copy:', use_container_width=True):
                    from app.analyze import dedupe
                    with st.spinner('Comparing documents…'):
                        st.session_state['library_notice'] = f'{dedupe(store, config)} evidence-bearing pairs found.'
                    st.rerun()
                if c.button('Group related files', icon=':material/folder_copy:', use_container_width=True):
                    from app.analyze import cluster
                    with st.spinner('Clustering and generating local labels…'):
                        result = cluster(store, config)
                        st.success(f'{sum(g["label"] >= 0 for g in result)} content collections ready to explore.')
                groups = store.rows('''SELECT c.*,count(cm.document_id) n FROM clusters c LEFT JOIN cluster_members cm USING(cluster_id)
                    WHERE run_id=(SELECT max(run_id) FROM clusters) AND label!=-1 GROUP BY c.cluster_id ORDER BY n DESC LIMIT 4''')
                if groups:
                    st.markdown('<div class="section-title">Collections <span style="font-size:12px;font-weight:400;color:#98989d;margin-left:10px">Connected by content</span></div>', unsafe_allow_html=True)
                    cards = []
                    for group in groups:
                        label = group['llm_name'] or group['keyword_label']
                        label = ' · '.join(label.split(',')[:2]).title()
                        formats = store.rows('''SELECT DISTINCT f.magika_label kind FROM cluster_members cm JOIN documents d USING(document_id) JOIN files f USING(file_id) WHERE cm.cluster_id=?''', (group['cluster_id'],))
                        kinds = ', '.join(sorted((r['kind'] or 'file').upper() for r in formats))
                        cards.append(f'<div class="collection"><div class="folder-icon" title="Suggested content collection; files have not been moved"></div><div class="collection-title">{escape(label)}</div><div class="collection-meta">{group["n"]} documents · {escape(kinds)}<br><span class="suggested-tag">{"Needs refresh" if group["stale"] else "Suggested collection"}</span></div></div>')
                    st.markdown('<div class="collection-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
            st.markdown('<div class="section-title">All files</div>', unsafe_allow_html=True)
            st.caption('Kind is the detected format. Modified is the file’s last edit date. Indexed means its text is ready to search.')
            library_filter = st.session_state.get('toolbar_filter', '')
            file_types = [r['kind'] for r in store.rows("SELECT DISTINCT upper(magika_label) kind FROM files WHERE status='present' AND magika_label IS NOT NULL ORDER BY kind")]
            selected_kind = st.pills('File type', ['All kinds'] + file_types, default='All kinds', key='library_kind', label_visibility='collapsed') or 'All kinds'
            st.caption('Examples: TXT · notes, PDF · invoices, DOCX · documents, PPTX · slides, XLSX · spreadsheets.')
            rows = store.rows('''SELECT f.path AS File,f.magika_label AS Type,d.extraction_status AS Status,f.mtime AS Modified,
                d.extractor AS Extractor FROM files f LEFT JOIN documents d USING(file_id) WHERE f.status='present' ORDER BY f.path''')
            if rows:
                library = []
                for row in rows:
                    path = Path(row['File'])
                    source_root = next((r for r in config.roots if path.is_relative_to(r)), None)
                    library.append({**row, 'File': str(path.relative_to(source_root)) if source_root else str(path)})
                filtered = [r for r in library if library_filter.casefold() in (r['File'] + ' ' + (r['Type'] or '')).casefold() and (selected_kind == 'All kinds' or (r['Type'] or '').upper() == selected_kind)]
                from ui.pager import pager
                first, last = pager(len(filtered), 12, 'library_page', 'files')
                table = '<table class="file-table"><thead><tr><th>Name</th><th>Kind</th><th>Modified</th><th>Status</th></tr></thead><tbody>'
                for row in filtered[first:last]:
                    path = Path(row['File'])
                    kind = escape((row['Type'] or 'file').upper())
                    date = datetime.fromtimestamp(row['Modified'] / 1e9).strftime('%d %b %Y') if row['Modified'] else '—'
                    status = 'Indexed' if row['Status'] == 'ok' else row['Status'] or 'Pending'
                    table += f'<tr><td><div class="file-identity"><span class="doc-icon">{'MD' if kind == 'MARKDOWN' else kind[:4]}</span><div class="file-info">{escape(path.name)}<span class="file-sub">{escape(str(path.parent)) if str(path.parent) != "." else "Library"}</span></div></div></td><td>{'MD' if kind == 'MARKDOWN' else kind}</td><td>{date}</td><td><span class="ready">{escape(status)}</span></td></tr>'
                st.markdown('<div class="file-table-wrap">' + table + '</tbody></table></div>', unsafe_allow_html=True)
                st.markdown('<div class="table-hint">↔ Scroll the table sideways to see dates and status.</div>', unsafe_allow_html=True)
                noun = 'file' if len(filtered) == 1 else 'files'
                st.caption(f'{len(filtered)} {noun}' + (' matching your filters' if library_filter or selected_kind != 'All kinds' else ' in your library'))
                if not filtered:
                    st.info('No files match. Choose All kinds or clear the search in the top toolbar.')
                st.download_button('Export inventory · JSON', json.dumps(rows, indent=2), 'file-inventory.json', 'application/json')
            else:
                st.info('Your demo folder is ready. Select Scan & index files to begin.')
        elif page == 'Search':
            st.title('Search')
            from ui.discover import TOOLS, render_ask, render_similar, more_like_this_button, render_fact_matches
            if 'goto_tool' in st.session_state:
                st.session_state['search_tool'] = st.session_state.pop('goto_tool')
            tool = st.segmented_control('Search mode', TOOLS, default='Search', key='search_tool', label_visibility='collapsed') or 'Search'
            if tool == 'Ask your library':
                render_ask(store, config)
            elif tool == 'More like this':
                render_similar(store, config)
            if tool == 'Search':
                st.caption('Find a document by its words, or by what it means.')
                query = st.text_input('What are you looking for?', placeholder='An invoice number, a filename, or an idea…')
                a, b = st.columns(2)
                mode = a.selectbox('Search method', ['hybrid', 'keyword', 'semantic'], format_func=lambda v: {'hybrid': 'Words + meaning', 'keyword': 'Words only', 'semantic': 'Meaning only'}[v])
                types = [''] + [r['magika_label'] for r in store.rows("SELECT DISTINCT magika_label FROM files WHERE status='present'")]
                kind = b.selectbox('File type', types, format_func=lambda x: x or 'All file types')
                facts = store.rows('''SELECT t.tag,count(DISTINCT t.document_id) n FROM tags t JOIN documents d USING(document_id)
                    JOIN files f USING(file_id) WHERE t.source='fact' AND f.status='present' GROUP BY t.tag ORDER BY t.tag''')
                fact_counts = {r['tag']: r['n'] for r in facts}
                fact_filter = st.selectbox('Key fact', [''] + list(fact_counts), key='fact_filter',
                    format_func=lambda x: f'{x[0].upper()}{x[1:]}  ·  {fact_counts[x]} file' + ('s' if fact_counts[x] > 1 else '') if x else 'Any amount, date, reference or organisation',
                    help='Amounts, dates, reference numbers, organisations and email addresses found in your files.')
                with st.expander('Filter by folder, date, topic or tag'):
                    left, right = st.columns(2)
                    root_filter = left.selectbox('Source folder', [''] + [str(p) for p in config.roots], format_func=lambda x: Path(x).name if x else 'All folders')
                    tags = [''] + [r['tag'] for r in store.rows("SELECT DISTINCT tag FROM tags WHERE source!='fact' ORDER BY tag")]
                    tag_filter = right.selectbox('Tag', tags, format_func=lambda x: x or 'All tags')
                    groups = store.rows('SELECT cluster_id,keyword_label,llm_name FROM clusters WHERE run_id=(SELECT max(run_id) FROM clusters)')
                    names = {r['cluster_id']: r['llm_name'] or r['keyword_label'] for r in groups}
                    cluster_filter = left.selectbox('Topic group', [None] + list(names), format_func=lambda x: names.get(x, 'All groups'))
                    start_date = left.date_input('Modified on or after', value=None)
                    end_date = right.date_input('Modified on or before', value=None)
                if fact_filter and not query:
                    render_fact_matches(store, config, fact_filter)
                if query:
                    from app.search import search
                    stages = {k: {'name': n, 'state': 'pending', 'detail': 'Waiting'} for k, n in [('scope', '1 · Scope'), ('keyword', '2 · Match words'), ('semantic', '3 · Compare meaning'), ('rank', '4 · Rank documents'), ('results', '5 · Show evidence')]}
                    workflow = st.empty()
                    started = perf_counter()
                    def show_progress(stage, state, detail):
                        stages[stage].update(state=state, detail=detail)
                        symbols = {'pending': '○', 'running': '◉', 'complete': '✓', 'skipped': '—', 'error': '!'}
                        workflow.markdown('<div class="workflow">' + ''.join(f'<div class="stage {r["state"]}"><strong>{symbols[r["state"]]} {r["name"]}</strong><p>{escape(r["detail"])}</p></div>' for r in stages.values()) + '</div>', unsafe_allow_html=True)
                    try:
                        results = search(store, config, query, mode=mode, type_filter=kind, root_filter=root_filter, tag_filter=tag_filter, cluster_filter=cluster_filter, date_from=str(start_date) if start_date else '', date_to=str(end_date) if end_date else '', progress=show_progress, fact_filter=fact_filter)
                    except Exception:
                        active = next((k for k, v in stages.items() if v['state'] == 'running'), 'results')
                        show_progress(active, 'error', 'Could not finish. Check the message below.')
                        raise
                    st.success(f'Search complete · {len(results)} results · {perf_counter() - started:.1f} seconds · processed on this device')
                    st.caption(f'{len(results)} matching documents')
                    for row in results:
                        with st.container(border=True):
                            st.subheader(plain_heading(row['title']))
                            where, alike = st.columns(2)
                            with where:
                                location_button(row['path'], config, 'search_' + str(row['document_id']))
                            with alike:
                                more_like_this_button(row['document_id'], 'search_' + str(row['document_id']))
                            st.text(row['evidence'][:1500])
                            reasons = []
                            if row.get('keyword_rank'):
                                reasons.append('Matching words')
                            if row.get('semantic_rank'):
                                reasons.append('Related meaning')
                            st.caption('Why this appears: ' + (' + '.join(reasons) or 'Filename match') + (f" · Page {row['page']}" if row.get('page') else ''))
                            with st.expander('Match details'):
                                st.caption(f"Ranking score {row['score']:.4f} · Word rank {row.get('keyword_rank') or '—'} · Meaning similarity {row.get('cosine', '—')}")
                    if not results:
                        st.info('No matching documents. Check that your files have been indexed.')
        elif page == 'Duplicates':
            from ui.duplicates import render
            render(store, config, icon)
        elif page == 'Clusters':
            from ui.collections import render
            render(store, config, icon)
        elif page == 'Organize':
            from ui.organize import render
            render(store, config)
        elif page == 'Approvals':
            st.title('Activity')
            st.caption('Review proposed changes, approve moves, and restore files.')
            with st.expander('Propose a move, rename, or soft-delete'):
                with st.form('proposal'):
                    kind = st.selectbox('Action', ['move', 'rename', 'delete'])
                    src = st.text_input('Source path')
                    dst = st.text_input('Destination path (unused for delete)')
                    if st.form_submit_button('Create proposal'):
                        st.success(f'Created action {actions.propose(store, config, kind, src, dst or None)}')
            for row in store.rows('SELECT * FROM actions ORDER BY action_id DESC'):
                with st.container(border=True):
                    st.subheader(f"#{row['action_id']} · {row['kind'].title()} · {row['status']}")
                    st.text(Path(row['src']).name + (' → ' + Path(row['dst']).name if row['dst'] else ' → Local recovery storage'))
                    location_button(row['dst'] if row['status'] == 'executed' and row['dst'] else row['src'], config, 'activity_' + str(row['action_id']))
                    if row['dst']:
                        destination = Path(row['dst'])
                        root = next((r for r in config.roots if destination.is_relative_to(r)), None)
                        if root:
                            st.caption('Destination folder: ' + root.name + ' / ' + str(destination.parent.relative_to(root)))
                    st.caption('Expected SHA-256: ' + row['src_sha256'])
                    a, b = st.columns(2)
                    if row['status'] == 'proposed' and a.button('Approve', key=f"approve{row['action_id']}"):
                        actions.approve(store, row['action_id'])
                        st.rerun()
                    if row['status'] == 'approved' and a.button('Execute approved action', key=f"apply{row['action_id']}"):
                        actions.apply(store, config, row['action_id'])
                        st.rerun()
                    if row['status'] == 'executed' and a.button('Undo', key=f"undo{row['action_id']}"):
                        actions.undo(store, config, row['action_id'])
                        st.rerun()
                    if row['status'] in ('proposed', 'approved') and b.button('Reject', key=f"reject{row['action_id']}"):
                        actions.reject(store, row['action_id'])
                        st.rerun()
            if st.button('Recover interrupted actions'):
                st.json(actions.recover(store, config))
        else:
            st.title('Settings')
            st.write('The essentials, at a glance.')
            # Two columns fill wide windows: status and folders on the left, reports and tools on the right.
            main, side = st.columns(2, gap='large')
            with main:
                st.markdown('<div class="setting-summary"><div class="setting-row"><span class="setting-symbol">🔒</span><div><div class="setting-name">Private processing</div><div class="setting-detail">AI runs on this device.</div></div></div><div class="setting-row"><span class="setting-symbol">✓</span><div><div class="setting-name">Available offline</div><div class="setting-detail">No internet needed.</div></div></div></div>', unsafe_allow_html=True)
                with st.container(border=True):
                    st.subheader('📁  Your folders')
                    for i, root in enumerate(config.roots):
                        location_button(root, config, 'settings_' + str(i), label=root.name)
                    render_connections(config, 'settings_sources')
                    st.caption('Connect several folders, then Scan & Index. Use Organize to select individual files across them.')
                issues = store.rows("SELECT f.path,f.magika_label,f.status,f.failures,d.extraction_status FROM files f LEFT JOIN documents d USING(file_id) WHERE f.status='quarantined'")
                audit_ok = store.verify_audit()
                with st.container(border=True):
                    st.subheader('✓  File reading')
                    if issues:
                        st.warning(f'{len(issues)} file(s) could not be read.')
                        if st.button('Retry unreadable files', icon=':material/refresh:'):
                            scan_library(retry_failed=True)
                            st.rerun()
                    else:
                        st.write('No reading errors found.')
                    if not audit_ok:
                        st.error('The activity record could not be verified. See Help & diagnostics below.')
                    if st.button('Run AI check', icon='🔎', help='Verify the local files used for search, topic names, and document reading.'):
                        results = []
                        with st.spinner('Checking local AI files…'):
                            for name, label in [('minilm', 'Document search'), ('qwen', 'Topic naming'), ('docling', 'Document reading'), ('ocr', 'Text in images')]:
                                try:
                                    verify_model(config.models, name)
                                    results.append({'Feature': label, 'Result': 'Ready', 'Details': ''})
                                except Exception as exc:
                                    results.append({'Feature': label, 'Result': 'Needs attention', 'Details': str(exc)})
                        st.session_state['health_check'] = results
                    checked = st.session_state.get('health_check')
                    if checked:
                        if all(r['Result'] == 'Ready' for r in checked):
                            st.success('AI files are ready.')
                        else:
                            for row in checked:
                                if row['Result'] != 'Ready':
                                    st.error(f'{row["Feature"]} needs attention. See Help & diagnostics below.')
                    if issues:
                        with st.expander('Review files that need attention'):
                            for row in issues:
                                st.text(Path(row['path']).name)
                                st.caption('Check that the file is downloaded and opens normally, then select Retry unreadable files.')
            with side:
                    with st.expander('Quality report', icon=':material/insights:', expanded=True):
                        quality_report()
                    with st.expander('Export review report', icon=':material/download:'):
                        from app.report import gather, to_csv, to_html
                        report = gather(store)
                        st.caption(f"{len(report['pairs'])} matches, {len(report['collections'])} collections and the latest quality "
                                   'measurements. The report lists file names only, never file contents.')
                        left, right = st.columns(2)
                        left.download_button('Decisions · CSV', to_csv(report), 'file-intel-decisions.csv', 'text/csv', use_container_width=True)
                        right.download_button('Full report · HTML', to_html(report), 'file-intel-report.html', 'text/html', use_container_width=True,
                                              help='Open it in a browser and use Print to save a PDF.')
                    with st.expander('Search language', icon=':material/translate:'):
                        search_language(store, config)
                    with st.expander('Help & diagnostics'):
                        st.write('Search or reading not working? Run AI check above.')
                        st.caption('Files move only after approval in Activity. Details below are for troubleshooting.')
                        st.write('Activity record: ' + ('verified' if audit_ok else 'verification failed'))
                        if checked:
                            st.dataframe(checked, hide_index=True, use_container_width=True)
                        if issues:
                            st.dataframe(issues, hide_index=True, use_container_width=True)
                        st.write('Recent activity log')
                        st.dataframe(store.rows('SELECT ts,component,action,actor FROM audit_log ORDER BY id DESC LIMIT 100'), hide_index=True, use_container_width=True)
    except Exception as exc:
        st.error(str(exc))
    finally:
        store.close()


if __name__ == '__main__':
    main()
