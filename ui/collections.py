"""Content collections with browsable folders and explicit source paths."""
from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path

import streamlit as st
from ui.locations import location_button
from ui.pager import pager
from ui.discover import more_like_this_button


def collection_title(row):
    if row['label'] == -1:
        return 'Not yet grouped'
    return row['llm_name'] or ' · '.join((row['keyword_label'] or 'Related documents').split(',')[:3]).title()


def render(store, config, icon):
    groups = store.rows('SELECT * FROM clusters WHERE run_id=(SELECT max(run_id) FROM clusters) ORDER BY label=-1,label')
    members = defaultdict(list)
    for item in store.rows('''SELECT cm.cluster_id,cm.membership_prob,f.path,f.magika_label,f.mtime,f.size,f.status,
        d.document_id,substr(d.text,1,300) excerpt FROM cluster_members cm JOIN documents d USING(document_id)
        JOIN files f USING(file_id) JOIN clusters c USING(cluster_id)
        WHERE c.run_id=(SELECT max(run_id) FROM clusters) AND f.status='present' ORDER BY f.path'''):
        members[item['cluster_id']].append(item)
    topics = [g for g in groups if g['label'] != -1]
    grouped_ids = {m['document_id'] for g in topics for m in members[g['cluster_id']]}
    kinds = {m['magika_label'] for items in members.values() for m in items if m['magika_label']}
    ungrouped = sum(len(members[g['cluster_id']]) for g in groups if g['label'] == -1)
    st.markdown(f'<div class="duplicate-hero collections-hero"><div><div class="duplicate-eyebrow">CONNECTED BY CONTENT</div>'
                '<h1>A place for every idea.</h1><p>Your files, brought together by what they mean.</p>'
                '<div class="duplicate-hero-meta"><span>Across file types</span><span>Original locations preserved</span><span>On-device intelligence</span></div></div>'
                f'<div class="duplicate-art" aria-hidden="true"><div class="duplicate-sheet back">{icon("files")}</div>'
                f'<div class="duplicate-sheet front">{icon("folder")}</div><span class="duplicate-art-check">✓</span></div></div>', unsafe_allow_html=True)
    stats = [(len(topics), 'Content collections', 'folder'), (len(grouped_ids), 'Files connected by topic', 'files'),
             (len(kinds), 'File formats represented', 'spark'), (ungrouped, 'Files not yet grouped', 'clock')]
    st.markdown('<div class="summary-grid collections-summary">' + ''.join(
        f'<div class="stat"><span class="stat-icon">{icon(symbol)}</span><div><div class="stat-label">{label}</div><div class="stat-value">{count}</div></div></div>'
        for count, label, symbol in stats) + '</div>', unsafe_allow_html=True)
    left, right = st.columns([3, 1], vertical_alignment='bottom')
    query = left.text_input('Find a collection', placeholder='Search a topic, filename, or path…', key='collection_filter')
    if right.button('Refresh collections', icon=':material/refresh:', use_container_width=True):
        from app.analyze import cluster
        with st.spinner('Finding related content on this device…'):
            cluster(store, config)
        st.rerun()
    if not groups:
        st.info('No collections yet. Select Refresh collections to group your indexed files by content.')
        return
    filtered = [g for g in groups if query.casefold() in (collection_title(g) + ' ' + (g['keyword_label'] or '') + ' ' + ' '.join(m['path'] for m in members[g['cluster_id']])).casefold()]
    if not filtered:
        st.info('No collections match. Try a topic, filename, or part of a folder path.')
        return
    selected = st.session_state.get('selected_collection')
    if selected not in {g['cluster_id'] for g in filtered}:
        selected = filtered[0]['cluster_id']
        st.session_state['selected_collection'] = selected
    st.markdown('<div class="section-title">Your collections</div>', unsafe_allow_html=True)
    st.caption('Suggested topic groups. Use Organize to turn a collection into physical folders.')
    start, end = pager(len(filtered), 3, 'collection_page', 'collections')
    visible = filtered[start:end]
    if selected not in {g['cluster_id'] for g in visible}:
        selected = visible[0]['cluster_id']
        st.session_state['selected_collection'] = selected
    with st.container(key='collection_tiles'):
        for column, group in zip(st.columns(3), visible):
            cid = group['cluster_id']
            items = members[cid]
            formats = sorted({(m['magika_label'] or 'file').upper() for m in items})
            folders = len({str(Path(m['path']).parent) for m in items})
            folder_noun = 'source folder' if folders == 1 else 'source folders'
            status = 'Needs refresh' if group['stale'] else ('Needs a topic' if group['label'] == -1 else 'Suggested topic')
            with column.container(border=True, key='collection_tile_' + str(cid)):
                folder, navigation = st.columns([3, 1], vertical_alignment='center')
                with folder:
                    if st.button('', icon=':material/folder:', key='view_collection_' + str(cid),
                                 help='View files in ' + collection_title(group),
                                 type='primary' if cid == selected else 'secondary'):
                        st.session_state['selected_collection'] = cid
                        st.rerun()
                with navigation:
                    with st.popover('', icon=':material/folder_open:',
                                    help='Browse original files in ' + collection_title(group),
                                    use_container_width=True):
                        st.markdown('**' + escape(collection_title(group)) + '**')
                        st.caption('Original files · Open a location in your file manager.')
                        if not items:
                            st.info('No files are available. Refresh collections to update this folder.')
                        if group['stale']:
                            st.caption('Files may have changed. Refresh collections to update this list.')
                        begin, finish = pager(len(items), 6, f'collection_quick_page_{cid}', 'files')
                        for item in items[begin:finish]:
                            location_button(item['path'], config,
                                            f'collection_quick_{cid}_{item["document_id"]}',
                                            label=Path(item['path']).name)
                st.markdown(f'<span class="duplicate-decision">{status}</span>'
                            f'<h3 class="collection-tile-title">{escape(collection_title(group))}</h3><div class="collection-tile-count">{len(items)} <span>files · {folders} {folder_noun}</span></div>'
                            '<div class="format-chips">' + ''.join(f'<span>{escape(kind)}</span>' for kind in formats) + '</div>', unsafe_allow_html=True)
    group = next(g for g in filtered if g['cluster_id'] == selected)
    items = members[selected]
    with st.container(border=True, key='collection_detail'):
        st.markdown(f'<div class="collection-detail-title"><span class="collection-large-icon">{icon("folder")}</span><div><div class="duplicate-eyebrow">COLLECTION CONTENTS</div><h2>{escape(collection_title(group))}</h2></div></div>', unsafe_allow_html=True)
        st.caption(f'{len(items)} files · Use the folder icon to reveal an original file in your file manager.')
        if group['stale']:
            st.warning('Files have changed since this collection was created. Refresh collections to update the grouping.')
        if not items:
            st.info('No present files remain in this collection. Refresh collections to update it.')
        first, last = pager(len(items), 6, f'collection_files_page_{selected}', 'files')
        for item in items[first:last]:
            kind = (item['magika_label'] or 'FILE').upper()
            date = datetime.fromtimestamp(item['mtime'] / 1e9).strftime('%d %b %Y') if item['mtime'] else 'Date unavailable'
            with st.container(key='collection_file_' + str(item['document_id'])):
                info, location, alike = st.columns([4, 1, 1], vertical_alignment='center')
                info.markdown(f'<div class="collection-file-heading"><span class="duplicate-doc">{escape(kind[:5])}</span><div><strong>{escape(Path(item["path"]).name)}</strong><p>{escape(kind)} · Modified {date}</p></div></div>', unsafe_allow_html=True)
                with location:
                    location_button(item['path'], config, 'collection_' + str(item['document_id']))
                with alike:
                    more_like_this_button(item['document_id'], 'collection_' + str(item['document_id']))
                st.markdown(f'<p class="collection-file-excerpt">{escape((item["excerpt"] or "No text preview available.")[:220])}</p>', unsafe_allow_html=True)
        with st.expander('Why these files are grouped', icon=':material/info:'):
            st.write('Topic keywords: ' + (group['keyword_label'] or 'No confident keywords'))
            st.write('Tags: ' + ', '.join(json.loads(group['llm_tags_json'] or '[]')))
            st.caption('Grouping uses content similarity. Topic labels are suggestions, not instructions to move files.')
            st.json(json.loads(group['evidence_json'] or '{}'))
