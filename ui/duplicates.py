"""Visual duplicate review, using the existing decisions and approval flow."""
from datetime import datetime
from html import escape
import json
from pathlib import Path

import streamlit as st
from app import actions
from app.store import now
from ui.locations import location_button
from ui.pager import pager


TIERS = {1: ('Exact copies', 'The file contents are byte-for-byte identical.', 'exact'),
         2: ('Same text', 'The extracted text matches after normalization.', 'text'),
         3: ('Edited versions', 'One document saved twice with changes, or near-identical meaning.', 'related'),
         4: ('Summaries & excerpts', 'A shorter file that restates or quotes a longer one.', 'summary')}
DECISIONS = {'unreviewed': 'Needs review', 'keep-both': 'Keep both', 'duplicate': 'Confirmed duplicate'}


def file_card(row, side, label=None):
    path = Path(row[f'{side}_path'])
    size = row[f'{side}_size']
    size_label = 'Size unavailable' if size is None else (f'{size / 1048576:.1f} MB' if size >= 1048576 else f'{size / 1024:.1f} KB')
    modified = row[f'{side}_mtime']
    date = datetime.fromtimestamp(modified / 1e9).strftime('%d %b %Y') if modified else 'Date unavailable'
    kind = (row[f'{side}_kind'] or 'FILE').upper()
    excerpt = row[f'{side}_excerpt'] or 'No text preview available. Review the original file.'
    label = label or ('File A' if side == 'left' else 'File B')
    return (f'<article class="duplicate-file"><div class="duplicate-file-top"><span class="duplicate-doc">{escape(kind[:5])}</span>'
            f'<div><span class="duplicate-eyebrow">{label}</span><h3>{escape(path.name)}</h3></div></div>'
            f'<div class="duplicate-meta">{escape(kind)} <span>·</span> {size_label} <span>·</span> {date}</div>'
            f'<p class="duplicate-excerpt">{escape(excerpt[:260])}{"…" if len(excerpt) > 260 else ""}</p></article>')


def render_file(row, side, config, key, label=None):
    with st.container(border=True, key='file_preview_' + key):
        st.markdown(file_card(row, side, label), unsafe_allow_html=True)
        location_button(row[f'{side}_path'], config, key)


def exact_groups(rows):
    """Join pairwise exact matches into one family per identical content set."""
    parents = {}
    def find(item):
        parents.setdefault(item, item)
        while item != parents[item]:
            parents[item] = parents[parents[item]]
            item = parents[item]
        return item
    exact = [r for r in rows if r['tier'] == 1]
    for row in exact:
        parents[find(row['right_id'])] = find(row['left_id'])
    groups = {}
    for row in exact:
        groups.setdefault(find(row['left_id']), []).append(row)
    return list(groups.values())


def relation_note(row):
    """Plain-language explanation of a version or summary match, with the words that changed."""
    evidence = json.loads(row['evidence_json'] or '{}')
    names = {'left': Path(row['left_path']).name, 'right': Path(row['right_path']).name}
    if row['tier'] == 4:
        shorter = evidence.get('shorter', 'right')
        longer = 'left' if shorter == 'right' else 'right'
        kind = 'an excerpt of' if evidence.get('relation') == 'excerpt' else 'a summary of'
        figures = ', '.join(evidence.get('shared_figures', [])[:5])
        detail = f'Shared figures: {escape(figures)}' if figures else f"{evidence.get('copied_wording', 0):.0%} of its wording is copied"
        return (f'<div class="duplicate-match-note"><strong>{escape(names[shorter])} looks like {kind} {escape(names[longer])}</strong>'
                f'<span>{detail}</span></div>')
    if 'shared_wording' in evidence and evidence.get('reason', '').startswith('Edited'):
        def edit(change):
            before, after = escape(change['before'][:160]), escape(change['after'][:160])
            if not before:
                return f'<li><span>Added</span><ins>{after}</ins></li>'
            if not after:
                return f'<li><span>Removed</span><del>{before}</del></li>'
            return f'<li><del>{before}</del><span aria-label="changed to">→</span><ins>{after}</ins></li>'
        edits = ''.join(edit(c) for c in evidence.get('changes', []))
        return (f'<div class="duplicate-match-note"><strong>{evidence["shared_wording"]:.0%} of the wording is shared</strong>'
                f'<span>File A → File B changes</span></div>' + (f'<ul class="duplicate-changes">{edits}</ul>' if edits else ''))
    return (f'<div class="duplicate-match-note"><strong>Cosine similarity · {row["score"]:.3f}</strong>'
            f'<span>{TIERS[row["tier"]][1]}</span></div>')


def decide_all(store, pairs, decision):
    """Save one review decision for many pairs in a single audited transaction."""
    keys = sorted({(r['left_id'], r['right_id']) for r in pairs})
    stamp = now()
    store.db.executemany('UPDATE duplicates SET decision=?,reviewed_at=? WHERE left_id=? AND right_id=?',
                         [(decision, stamp, a, b) for a, b in keys])
    store.audit('interact', 'duplicate_review_batch', {'pairs': len(keys), 'decision': decision}, 'user')
    store.db.commit()
    return len(keys)


def propose_removals(store, config, paths):
    """Propose a soft-delete for each path that is a real file without a pending action. Nothing moves yet."""
    proposed, skipped = [], 0
    for path in dict.fromkeys(paths):
        pending = store.one("SELECT 1 FROM actions WHERE src=? AND status IN ('proposed','approved')", (path,))
        if '::' in path or pending:
            skipped += 1
            continue
        try:
            proposed.append(actions.propose(store, config, 'delete', path))
        except (ValueError, OSError):
            skipped += 1
    return proposed, skipped


def extra_copies(families):
    """In each exact-copy family keep the first file (lowest id) and list the others."""
    extras = []
    for family in families:
        ids = {}
        for pair in family:
            ids[pair['left_id']], ids[pair['right_id']] = pair['left_path'], pair['right_path']
        keep = min(ids)
        extras += [path for did, path in sorted(ids.items()) if did != keep]
    return extras


def render_timelines(store, config):
    from app.analyze import version_chains
    chains = version_chains(store)
    if not chains:
        return
    with st.expander(f'Version timelines · {len(chains)}', icon=':material/timeline:'):
        st.caption('Files linked as edited versions, oldest to newest by last-modified date. Keeping the latest moves the '
                   'older versions to recovery storage after you approve them in Activity. Undo restores them.')
        start, end = pager(len(chains), 3, 'timeline_page', 'timelines')
        for i, chain in enumerate(chains[start:end], start):
            steps = ''.join(
                f'<li class="{"latest" if n == len(chain) - 1 else ""}"><strong>{escape(Path(d["path"]).name)}</strong>'
                f'<span>{datetime.fromtimestamp(d["mtime"] / 1e9).strftime("%d %b %Y %H:%M") if d["mtime"] else "Date unavailable"}'
                f'{" · Latest" if n == len(chain) - 1 else ""}</span></li>' for n, d in enumerate(chain))
            with st.container(border=True, key=f'timeline_{i}'):
                st.markdown(f'<ol class="version-chain">{steps}</ol>', unsafe_allow_html=True)
                if len({Path(d['path']).suffix.lower() for d in chain}) > 1:
                    # Different formats are often deliberate exports (a .docx and its .pdf); never offer to remove them in bulk.
                    st.caption('These versions are different file types, so Keep latest is not offered. Review them in Compare & review.')
                elif st.button(f'Keep latest · move {len(chain) - 1} older to recovery', icon=':material/inventory_2:', key=f'keep_latest_{i}'):
                    proposed, skipped = propose_removals(store, config, [d['path'] for d in chain[:-1]])
                    st.success(f'{len(proposed)} move(s) proposed. Approve them in Activity; no file has moved yet.'
                               + (f' {skipped} skipped (already pending or inside an archive).' if skipped else ''))


def review_controls(row, store, config):
    key = f"{row['left_id']}-{row['right_id']}"
    decision = row['decision'] or 'unreviewed'
    selection, save = st.columns([3, 1], vertical_alignment='bottom')
    choice = selection.selectbox('Your decision', list(DECISIONS), index=list(DECISIONS).index(decision), format_func=DECISIONS.get, key='decision' + key, label_visibility='collapsed')
    if save.button('Save review', icon=':material/check:', key='save' + key, use_container_width=True):
        store.db.execute('UPDATE duplicates SET decision=?,reviewed_at=? WHERE left_id=? AND right_id=?', (choice, now(), row['left_id'], row['right_id']))
        store.audit('interact', 'duplicate_review', {'pair': key, 'decision': choice}, 'user')
        store.db.commit()
        st.rerun()
    with st.expander('Evidence & file actions', icon=':material/info:'):
        st.json(json.loads(row['evidence_json']))
        if row['tier'] < 4 and '::' not in row['right_path'] and st.button('Propose removing File B', icon=':material/delete_outline:', key='delete' + key):
            aid = actions.propose(store, config, 'delete', row['right_path'])
            st.success(f'Action {aid} proposed. Review and approve it in Activity. No file has been moved.')


def render(store, config, icon):
    rows = store.rows('''SELECT x.*,a.path left_path,b.path right_path,
        a.size left_size,b.size right_size,a.mtime left_mtime,b.mtime right_mtime,
        a.magika_label left_kind,b.magika_label right_kind,
        substr(da.text,1,600) left_excerpt,substr(db.text,1,600) right_excerpt
        FROM duplicates x JOIN documents da ON da.document_id=x.left_id JOIN files a ON a.file_id=da.file_id
        JOIN documents db ON db.document_id=x.right_id JOIN files b ON b.file_id=db.file_id
        WHERE a.status='present' AND b.status='present' ORDER BY x.tier,x.left_id,x.right_id''')
    reviewed = sum(r['decision'] in ('keep-both', 'duplicate') for r in rows)
    pending = len(rows) - reviewed
    unique = len({r[s] for r in rows for s in ('left_id', 'right_id')})
    st.markdown(f'<div class="duplicate-hero"><div><div class="duplicate-eyebrow">LIBRARY HEALTH</div>'
                f'<h1>Duplicates, in perspective.</h1><p>See what matches. Keep what matters.</p>'
                f'<div class="duplicate-hero-meta"><span>{unique} files involved</span><span>{pending} pairs to review</span><span>Processed on this device</span></div></div>'
                f'<div class="duplicate-art" aria-hidden="true"><div class="duplicate-sheet back">{icon("files")}</div>'
                f'<div class="duplicate-sheet front">{icon("copy")}</div><span class="duplicate-art-check">✓</span></div></div>', unsafe_allow_html=True)
    cards = []
    for tier, (title, detail, tone) in TIERS.items():
        count = sum(r['tier'] == tier for r in rows)
        share = count / max(len(rows), 1) * 100
        cards.append(f'<div class="duplicate-summary {tone}"><div class="duplicate-summary-heading"><span class="duplicate-summary-icon">{icon("copy" if tier < 3 else "spark")}</span><span>{title}</span></div>'
                     f'<div class="duplicate-total">{count}<span>pairs</span></div><p>{detail}</p>'
                     f'<div class="duplicate-meter" aria-hidden="true"><span style="width:{share:.2f}%"></span></div></div>')
    st.markdown('<div class="duplicate-summary-grid">' + ''.join(cards) + '</div>', unsafe_allow_html=True)
    percent = reviewed / max(len(rows), 1) * 100
    st.markdown(f'<div class="duplicate-review-status"><span class="duplicate-review-icon">{icon("check")}</span><div><strong>{reviewed} of {len(rows)} pairs reviewed</strong><p>Review decisions are saved. Files stay in place until an approved action runs.</p></div><div class="duplicate-meter" role="progressbar" aria-label="Pairs reviewed" aria-valuenow="{reviewed}" aria-valuemin="0" aria-valuemax="{max(len(rows), 1)}"><span style="width:{percent:.2f}%"></span></div></div>', unsafe_allow_html=True)
    render_timelines(store, config)
    with st.container(key='duplicate_filters'):
        st.markdown('<div class="section-title">Compare & review</div>', unsafe_allow_html=True)
        tier_filter = st.pills('Match type', ['All matches'] + [v[0] for v in TIERS.values()], default='All matches', key='duplicate_tier') or 'All matches'
        status_column, summary_column = st.columns(2, vertical_alignment='bottom')
        status_filter = status_column.selectbox('Review status', ['All pairs', 'Needs review', 'Reviewed'], key='duplicate_status')
    filtered = [r for r in rows if (tier_filter == 'All matches' or TIERS[r['tier']][0] == tier_filter)
                and (status_filter == 'All pairs' or (r['decision'] in ('keep-both', 'duplicate')) == (status_filter == 'Reviewed'))]
    if not rows:
        st.info('No duplicate pairs to display. Use Find duplicates in Library to compare the indexed files.')
        return
    if not filtered:
        st.info('No pairs match these filters. Choose All matches and All pairs to see the full review queue.')
        return
    families = exact_groups(filtered)
    entries = families + [[r] for r in filtered if r['tier'] != 1]
    summary_column.caption(f'{len(filtered)} matching pairs · {len(families)} exact-copy groups. Each file appears once within its group.')
    start, end = pager(len(entries), 4, 'duplicate_page', 'review items')
    visible = [pair for entry in entries[start:end] for pair in entry]
    with st.container(key='duplicate_batch'):
        keep, confirm, clean = st.columns(3)
        if keep.button('Keep both · this page', icon=':material/done_all:', use_container_width=True):
            st.toast(f'{decide_all(store, visible, "keep-both")} pairs marked Keep both')
            st.rerun()
        if confirm.button('Confirm duplicates · this page', icon=':material/rule:', use_container_width=True):
            st.toast(f'{decide_all(store, visible, "duplicate")} pairs marked Confirmed duplicate')
            st.rerun()
        extras = extra_copies(families)
        if clean.button(f'Remove {len(extras)} extra exact copies', icon=':material/delete_sweep:', use_container_width=True,
                        disabled=not extras, help='Keeps one file from each identical group and proposes moving the others to recovery storage.'):
            proposed, skipped = propose_removals(store, config, extras)
            st.success(f'{len(proposed)} removal(s) proposed. Approve them in Activity; no file has moved yet.'
                       + (f' {skipped} skipped (already pending or inside an archive).' if skipped else ''))
    for entry in entries[start:end]:
        row = entry[0]
        key = f"{row['left_id']}-{row['right_id']}"
        title, detail, tone = TIERS[row['tier']]
        decision = row['decision'] or 'unreviewed'
        with st.container(border=True, key='duplicate_pair_' + key):
            if row['tier'] == 1:
                files = {}
                for pair in entry:
                    for side in ('left', 'right'):
                        files.setdefault(pair[f'{side}_id'], (pair, side))
                pair_noun = 'review pair' if len(entry) == 1 else 'review pairs'
                st.markdown(f'<div class="duplicate-pair-heading"><span class="duplicate-badge exact">{icon("folder")} Identical file group</span><span class="duplicate-decision">{len(files)} files · {len(entry)} {pair_noun}</span></div>'
                            f'<h3 class="exact-group-title">{escape(Path(row["left_path"]).name)}</h3>', unsafe_allow_html=True)
                copies = list(files.items())
                for start in range(0, len(copies), 2):
                    columns = st.columns(2)
                    for i, (column, (did, (pair, side))) in enumerate(zip(columns, copies[start:start + 2]), start + 1):
                        with column:
                            render_file(pair, side, config, key + '_' + str(did), f'Copy {i}')
                if len(entry) > 1:
                    selected_pair = st.selectbox('Pair to review', range(len(entry)), format_func=lambda i: f'A: {Path(entry[i]["left_path"]).name} ↔ B: {Path(entry[i]["right_path"]).name}', key='exact_review_' + key)
                    row = entry[selected_pair]
                st.caption(f'Reviewing File A: {Path(row["left_path"]).name} ↔ File B: {Path(row["right_path"]).name}')
                review_controls(row, store, config)
                continue
            st.markdown(f'<div class="duplicate-pair-heading"><span class="duplicate-badge {tone}">{icon("copy" if row["tier"] < 3 else "spark")} {title}</span><span class="duplicate-decision">{DECISIONS[decision]}</span></div>', unsafe_allow_html=True)
            for column, side in zip(st.columns(2), ('left', 'right')):
                with column:
                    render_file(row, side, config, key + '_' + side)
            note = relation_note(row) if row['tier'] >= 3 else f'<div class="duplicate-match-note"><strong>Verified content match</strong><span>{detail}</span></div>'
            st.markdown(note, unsafe_allow_html=True)
            review_controls(row, store, config)
