"""Ask your library and More like this, shown as modes of the Search page."""
from html import escape
from pathlib import Path

import streamlit as st
from app.sources import file_label
from ui.locations import location_button

TOOLS = ['Search', 'Ask your library', 'More like this']


def more_like_this_button(document_id, key):
    """Open More like this for one document from anywhere in the app."""
    if st.button('More like this', icon=':material/travel_explore:', key='similar_' + key):
        # The Search page applies goto_tool before drawing its mode switch (a drawn widget's state is read-only).
        st.session_state.update(similar_to=document_id, goto_tool='More like this', current_page='Search')
        st.rerun()


def render_ask(store, config):
    st.caption('Ask a question in your own words. The answer is built only from your indexed files, and every '
               'sentence points to the passage it came from.')
    with st.form('ask_form', border=False):
        question = st.text_input('Your question', placeholder='e.g. How much was paid to the supplier twice?', key='ask_question')
        use_llm = st.toggle('Write the answer with the local model', value=config.use_llm, key='ask_llm',
                            help='When off, or when the model is unavailable, the closest sentences are quoted instead.')
        submitted = st.form_submit_button('Ask', icon=':material/question_answer:', type='primary')
    if submitted and question.strip():
        from app.ask import ask
        generator = None
        if use_llm:
            try:
                from app.local_model import LocalAnswerer
                generator = LocalAnswerer(config)
            except Exception as exc:
                st.info(f'The local model is not available ({exc}). Quoting the closest sentences instead.')
        with st.spinner('Finding passages and writing the answer on this device…'):
            st.session_state['ask_result'] = ask(store, config, question, generate=generator)
        store.audit('interact', 'ask', {'source': st.session_state['ask_result']['source'],
                                        'passages': len(st.session_state['ask_result']['passages'])}, 'user')
        store.db.commit()
    result = st.session_state.get('ask_result')
    if not result:
        return
    label = {'llm': 'Written by the local model from the cited passages',
             'extractive': 'Closest sentences quoted from your files', 'none': 'No answer'}[result['source']]
    with st.container(border=True, key='ask_answer'):
        st.markdown(f'<div class="ask-label">{escape(label)}</div><p class="ask-answer">{escape(result["answer"])}</p>',
                    unsafe_allow_html=True)
        if result['error'] and result['source'] == 'extractive':
            st.caption('The model answer was not used: ' + result['error'])
    cited = set(result['citations'])
    for p in result['passages']:
        with st.container(border=True, key=f"ask_passage_{p['n']}"):
            badge = 'Cited' if p['n'] in cited else 'Also retrieved'
            page = f" · page {p['page']}" if p.get('page') else ''
            st.markdown(f'<div class="ask-passage-head"><span class="ask-num">[{p["n"]}]</span>'
                        f'<strong>{escape(file_label(p["path"], config.roots))}</strong>'
                        f'<span class="duplicate-decision">{badge}{page}</span></div>'
                        f'<p class="collection-file-excerpt">{escape(p["text"][:500])}</p>'
                        + (f'<p class="file-sub">Same text also in {len(p["copies"])} other file(s): '
                           + escape(', '.join(Path(c).name for c in p['copies'][:4])) + '</p>' if p.get('copies') else ''),
                        unsafe_allow_html=True)
            left, right = st.columns(2)
            with left:
                location_button(p['path'], config, f"ask_{p['n']}")
            with right:
                more_like_this_button(p['document_id'], f"ask_{p['n']}")


def render_similar(store, config):
    from app.search import similar
    docs = store.rows('''SELECT d.document_id,f.path FROM documents d JOIN files f USING(file_id)
        WHERE f.status='present' ORDER BY f.path''')
    if not docs:
        st.info('Index your files first. More like this compares files that have been read.')
        return
    ids = [d['document_id'] for d in docs]
    labels = {d['document_id']: file_label(d['path'], config.roots) for d in docs}
    current = st.session_state.get('similar_to')
    # No widget key: the index follows similar_to, so a More like this click elsewhere selects that file.
    choice = st.selectbox('Find files like', ids, index=ids.index(current) if current in ids else 0, format_func=labels.get)
    st.session_state['similar_to'] = choice
    matches = similar(store, choice)
    if not matches:
        st.info('This file has no stored meaning vector yet, for example because its text could not be read.')
        return
    st.caption('Closest files by meaning, compared on this device. 1.00 means the same meaning.')
    for m in matches:
        with st.container(border=True, key=f"similar_card_{m['document_id']}"):
            info, score, where, again = st.columns([5, 1, 2, 2], vertical_alignment='center')
            info.markdown(f'<strong>{escape(Path(m["path"]).name)}</strong><br>'
                          f'<span class="file-sub">{escape(file_label(m["path"], config.roots))}</span>', unsafe_allow_html=True)
            score.markdown(f'<span class="duplicate-decision">{m["score"]:.2f}</span>', unsafe_allow_html=True)
            with where:
                location_button(m['path'], config, f"similar_loc_{m['document_id']}")
            with again:
                more_like_this_button(m['document_id'], f"row_{m['document_id']}")


def render_fact_matches(store, config, fact):
    """Every present file that mentions one key fact, without needing a search query."""
    rows = store.rows('''SELECT d.document_id,f.path,d.text FROM tags t JOIN documents d USING(document_id) JOIN files f USING(file_id)
        WHERE t.source='fact' AND t.tag=? AND f.status='present' ORDER BY f.path''', (fact,))
    st.caption(f'{len(rows)} file' + ('s' if len(rows) != 1 else '') + ' mention ' + fact.split(': ', 1)[-1])
    value = fact.split(': ', 1)[-1].split(' ')[0]
    for r in rows:
        text = ' '.join((r['text'] or '').split())
        at = text.find(value)
        snippet = text[max(0, at - 120):at + 180] if at >= 0 else text[:300]
        with st.container(border=True, key=f"fact_row_{r['document_id']}"):
            st.markdown(f'<strong>{escape(file_label(r["path"], config.roots))}</strong>'
                        f'<p class="collection-file-excerpt">{escape(snippet)}</p>', unsafe_allow_html=True)
            left, right = st.columns(2)
            with left:
                location_button(r['path'], config, f"fact_{r['document_id']}")
            with right:
                more_like_this_button(r['document_id'], f"fact_{r['document_id']}")
