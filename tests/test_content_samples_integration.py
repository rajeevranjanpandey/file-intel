"""Real parser/model verification using the sample Markdown, text, and PDF files."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from app import BASE, actions
from app.analyze import dedupe
from app.config import Config
from app.guard import enable_offline
from app.organize import plan
from app.pipeline import index
from app.search import search
from app.store import Store


@pytest.mark.integration
def test_real_cross_format_grouping_and_multi_folder_move(tmp_path, monkeypatch):
    monkeypatch.setenv('FILE_INTEL_DENY_ALL', '1')
    enable_offline()
    source = tmp_path / 'sample-folders'
    shutil.copytree(BASE / 'demo/content-check', source)
    config = Config(roots=[source / name for name in ('Markdown', 'PDF', 'Text')],
                    data=tmp_path / 'state', models=BASE / 'models', use_llm=False).validate()
    store = Store(config)
    report = {}
    try:
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        result = index(config, store)
        report['index'] = result
        assert result == {'changed': 6, 'indexed': 6, 'failed': 0}
        documents = store.rows('SELECT f.path,f.magika_label,d.text_sha256,d.extraction_status FROM documents d JOIN files f USING(file_id)')
        same = [d for d in documents if Path(d['path']).stem in ('orion-plan', 'orion-copy')]
        assert len(same) == 4
        assert {d['magika_label'] for d in same} == {'markdown', 'pdf', 'txt'}
        assert len({d['text_sha256'] for d in same}) == 1
        dedupe(store, config)
        pairs = store.rows('SELECT tier FROM duplicates')
        assert sum(d['tier'] in (1, 2) for d in pairs) == 6
        report['matching_files'] = [str(Path(d['path']).relative_to(source)) for d in same]
        report['exact_or_same_text_pairs'] = 6
        results = search(store, config, 'Orion garden project', mode='hybrid', limit=5)
        assert {d['path'] for d in same} <= {r['path'] for r in results}
        assert not any(Path(r['path']).name == 'pasta-recipe.txt' for r in results)
        report['search'] = 'All four matching files retrieved; unrelated recipe excluded from top five'
        preview = plan(store, config, config.roots[0], 'Grouped samples', layout='Same content',
                       selected_paths=list(before))
        assert {r['Source'] for r in preview} == {r['path'] for r in same}
        assert len({Path(r['Destination']).parent for r in preview}) == 1
        assert {Path(r['Source']).parent for r in preview} == set(config.roots)
        assert len({Path(r['Source']).suffix for r in preview}) == 3
        created = []
        try:
            for row in preview:
                aid = actions.propose(store, config, 'move', row['Source'], row['Destination'])
                actions.approve(store, aid, actor='sample-verification')
                actions.apply(store, config, aid)
                created.append(aid)
            assert all(Path(r['Destination']).exists() and not Path(r['Source']).exists() for r in preview)
            report['physical_grouping'] = '4 files moved from 3 folders into 1 folder'
        finally:
            for aid in reversed(created):
                actions.undo(store, config, aid)
        assert all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in before.items())
        assert store.verify_audit()
        report['undo'] = 'All six source files intact; hashes verified'
        report['audit'] = 'Verified'
        report['network'] = 'Application socket connections denied during the test; OS networking was not disabled'
        assert index(config, store)['indexed'] == 0
        report['incremental_scan'] = 'No unnecessary re-indexing after undo'
        # A transient failure can be retried without editing the user's file.
        store.db.execute("UPDATE files SET status='quarantined',failures=2 WHERE path=?", (same[0]['path'],))
        store.db.commit()
        retried = index(config, store, retry_failed=True)
        assert retried == {'changed': 0, 'indexed': 1, 'failed': 0}
        report['retry'] = 'One unreadable file recovered without changing its contents'
        assert store.verify_audit()
        output = BASE / 'output/content-check'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'verification.json').write_text(json.dumps(report, indent=2))
    finally:
        store.close()
