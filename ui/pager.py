"""Previous / next page navigator shared by the paged lists."""
import streamlit as st


def pager(total, per_page, key, noun='items'):
    """Render ‹ Previous · Page x of y · Next › and return (start, end) slice bounds for the current page."""
    pages = max(1, -(-total // per_page))
    page = min(max(st.session_state.get(key, 1), 1), pages)
    st.session_state[key] = page
    if pages > 1:
        with st.container(key='pager_' + key):
            back, label, forward = st.columns([1, 2, 1], vertical_alignment='center')
            if back.button('‹  Previous', key=key + '_prev', disabled=page == 1, use_container_width=True):
                st.session_state[key] = page - 1
                st.rerun()
            first, last = (page - 1) * per_page + 1, min(page * per_page, total)
            label.markdown(f'<div class="pager-label"><strong>Page {page} of {pages}</strong><span>{first}–{last} of {total} {noun}</span></div>',
                           unsafe_allow_html=True)
            if forward.button('Next  ›', key=key + '_next', disabled=page == pages, use_container_width=True):
                st.session_state[key] = page + 1
                st.rerun()
    return (page - 1) * per_page, page * per_page
