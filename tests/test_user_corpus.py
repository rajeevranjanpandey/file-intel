"""Regression for the user's September 30 corpus and its PDF generators."""
import importlib.util
import json
from pathlib import Path
import shutil

import pypdfium2 as pdfium
import pytest

from app import BASE
from app.analyze import cluster, dedupe
from app.config import Config
from app.guard import enable_offline
from app.organize import plan
from app.pipeline import index
from app.store import Store


@pytest.mark.parametrize('script', ['create_dummy_test_corpus', 'generate_test_corpus'])
def test_generated_pdf_text_stays_on_page(tmp_path, script):
    spec = importlib.util.spec_from_file_location(script, BASE / 'scripts' / f'{script}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = tmp_path / 'layout.pdf'
    lines = ['Audit (2026) \\ Review', 'Revenue reached 1450000 AED against operational costs of 820000 AED.'] * 3
    module.make_pdf(lines, output)
    with pdfium.PdfDocument(output) as pdf:
        page = pdf[0]
        text = page.get_textpage()
        assert ' '.join(text.get_text_range().split()) == ' '.join(lines)
        for i in range(text.count_chars()):
            left, bottom, right, top = text.get_charbox(i)
            assert 0 <= left <= right <= page.get_width()
            assert 0 <= bottom <= top <= page.get_height()


@pytest.mark.integration
def test_user_corpus_real_index_and_grouping(tmp_path, monkeypatch):
    monkeypatch.setenv('FILE_INTEL_DENY_ALL', '1')
    enable_offline()
    source = tmp_path / 'corpus'
    shutil.copytree(BASE / 'dummy_test_corpus', source)
    config = Config(roots=[source], data=tmp_path / 'state', use_llm=False).validate()
    store = Store(config)
    try:
        result = index(config, store)
        assert result['failed'] == 0
        docs = store.rows('SELECT d.*,f.path FROM documents d JOIN files f USING(file_id)')
        by_name = {Path(r['path']).name: r for r in docs}
        pdf_names = ['audit_report_v1.pdf', 'audit_report_v2_exact_copy.pdf',
                     'audit_report_v3_revised.pdf', 'audit_report_v4_executive_summary.pdf']
        original, copy, revised, summary = [by_name[n] for n in pdf_names]
        assert '1450000' in original['text'] and 'regulatory standards' in original['text']
        assert original['text_sha256'] == copy['text_sha256']
        assert len({original['text_sha256'], revised['text_sha256'], summary['text_sha256']}) == 3
        dedupe(store, config)
        preview = plan(store, config, source, 'Reviewed groups', layout='Same content',
                       selected_paths=[source / n for n in pdf_names])
        assert {Path(r['Source']).name for r in preview} == set(pdf_names[:2])
        assert len({Path(r['Destination']).parent for r in preview}) == 1
        groups = cluster(store, config)
        assert any(g['label'] >= 0 for g in groups)
        for group in groups:
            members = store.rows('SELECT f.path FROM cluster_members cm JOIN documents d USING(document_id) JOIN files f USING(file_id) WHERE cm.cluster_id=?', (group['cluster_id'],))
            group['files'] = [Path(row['path']).name for row in members]
        assert store.verify_audit()
        report = {'index': result, 'documents': len(docs),
                  'same_content': [Path(r['Source']).name for r in preview],
                  'revision_and_summary_excluded_from_exact_group': True,
                  'topic_groups': groups, 'network': 'Python sockets denied',
                  'original_files': 'Unchanged; tested temporary copies'}
        output = BASE / 'output/release-review'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'user-corpus.json').write_text(json.dumps(report, indent=2))
    finally:
        store.close()
