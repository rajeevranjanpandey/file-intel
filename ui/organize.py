"""Select documents across folders and preview physical content groups."""
from pathlib import Path

import streamlit as st

from app import actions
from app.organize import DATE_FORMATS, LAYOUTS, plan
from app.sources import file_label
from ui.locations import location_button
from ui.sources import render_connections


def render(store, config):
    st.title('Bring matching files together')
    st.write('Choose files across your folders. Keep matching content in one place, with every format preserved.')
    with st.container(border=True):
        heading, connect = st.columns([3, 1])
        heading.subheader('1 · Choose your files')
        with connect:
            render_connections(config, 'organize_sources')
        indexed = store.rows('''SELECT f.path FROM files f JOIN documents d USING(file_id)
            WHERE f.status='present' AND f.parent_file_id IS NULL ORDER BY f.path''')
        all_paths = [r['path'] for r in indexed]
        scope = st.segmented_control('File selection', ['All indexed files', 'Choose files'],
                                     default='All indexed files', key='organize_scope')
        selected = None
        if scope == 'Choose files':
            folders = sorted({str(Path(p).parent) for p in all_paths})
            selected_folders = st.multiselect('Look in folders', folders,
                format_func=lambda p: file_label(str(Path(p) / 'Files'), config.roots).removeprefix('Files · '),
                placeholder='All connected folders', key='organize_folders')
            choices = [p for p in all_paths if not selected_folders or str(Path(p).parent) in selected_folders]
            prior = st.session_state.get('organize_files', [])
            if any(p not in choices for p in prior):
                st.session_state['organize_files'] = [p for p in prior if p in choices]
            a, b, _ = st.columns([1, 1, 3])
            if a.button('Select shown files', key='select_shown_files'):
                st.session_state['organize_files'] = choices
            if b.button('Clear selection', key='clear_selected_files'):
                st.session_state['organize_files'] = []
            selected = st.multiselect('Files to organize', choices, key='organize_files',
                format_func=lambda p: file_label(p, config.roots), placeholder='Search filenames and select from several folders')
        active = all_paths if selected is None else selected
        st.caption(f'{len(active)} files · {len({str(Path(p).parent) for p in active})} source folders')

    with st.container(border=True):
        st.subheader('2 · Set up the destination')
        left, right = st.columns(2)
        layout = left.selectbox('Group files by', LAYOUTS)
        name = right.text_input('New folder name', 'Organized files')
        root = left.selectbox('Create folder inside', [str(r) for r in config.roots],
                              format_func=lambda p: Path(p).name)
        date_format = right.selectbox('Date folder format', list(DATE_FORMATS), disabled='Date' not in layout)
        topical = 'Content topic' in layout
        include_unsorted = st.checkbox('Include files without a confident topic in Unsorted') if topical else False
        if layout == 'Same content':
            st.info('One folder per matching text group. For example, a Markdown file, a text file and a PDF can stay together. Revised or unrelated text stays separate.')
            st.caption('Matches use complete extracted text, ignoring whitespace and Unicode composition. Images, formatting and metadata may differ. Dates do not split a matching group.')
        elif topical:
            st.caption('Topic collections include related documents. Refresh Collections after adding or changing files.')
        if 'Date' in layout:
            st.caption('Dates use each file’s last modified date in local time.')
        settings = (root, name, layout, date_format, include_unsorted, None if selected is None else tuple(sorted(selected)))
        if st.button('Preview folder structure', icon=':material/account_tree:', type='primary', disabled=not active):
            st.session_state['folder_plan'] = plan(store, config, root, name, layout, date_format,
                                                   include_unsorted, selected)
            st.session_state['folder_settings'] = settings
    preview = st.session_state.get('folder_plan')
    if preview is None:
        return
    if st.session_state.get('folder_settings') != settings:
        st.info('Selection or settings changed. Preview again to update your plan.')
        return
    if not preview:
        if layout == 'Same content':
            st.info('No matching files are ready to move. Select at least two files with identical, completely extracted text. Scan changed files again, or try a different grouping option.')
        else:
            st.info('No selected files are ready to move. Files already in the destination or waiting in Activity are skipped. For topic layouts, refresh Collections or include Unsorted.')
        return
    st.subheader('3 · Review your folder plan')
    a, b, c = st.columns(3)
    a.metric('Files to organize', len(preview))
    b.metric('Destination folders', len({str(Path(r['Destination']).parent) for r in preview}))
    c.metric('Files staying in place', len(active) - len(preview))
    with st.expander('Folder structure', expanded=True, icon=':material/folder_copy:'):
        for destination in sorted({str(Path(r['Destination']).parent) for r in preview}):
            st.write('📁 ' + str(Path(destination).relative_to(root)))
            st.caption(' · '.join(Path(r['Destination']).name for r in preview
                                 if str(Path(r['Destination']).parent) == destination))
    st.dataframe([{'File': Path(r['Source']).name, 'From folder': file_label(r['Source'], config.roots).split(' · ', 1)[1],
                   'Destination': str(Path(r['Destination']).relative_to(root))} for r in preview],
                 hide_index=True, use_container_width=True)
    with st.expander('Source file locations', icon=':material/folder_open:'):
        source = st.selectbox('File', [r['Source'] for r in preview], format_func=lambda p: file_label(p, config.roots))
        location_button(source, config, 'organize_source')
    st.caption('Create proposals, then approve moves in Activity. Folders are created when moves run. Undo restores each file. Existing files are never overwritten; archives stay intact.')
    if st.button('Create move proposals', icon=':material/drive_file_move:', type='primary'):
        fresh = plan(store, config, root, name, layout, date_format, include_unsorted, selected)
        if fresh != preview:
            st.session_state['folder_plan'] = fresh
            st.warning('Files or destinations changed. Review the refreshed preview before creating proposals.')
        else:
            created = []
            try:
                for item in preview:
                    created.append(actions.propose(store, config, 'move', item['Source'], item['Destination']))
            finally:
                st.session_state.pop('folder_plan', None)
            st.success(f'{len(created)} move proposals created. Open Activity to apply them.')
