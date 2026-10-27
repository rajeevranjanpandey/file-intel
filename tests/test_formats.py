import io
import zipfile
from dataclasses import replace
import pytest
from app.extract import _bytes, ExtractionPool
from app.guard import enable_offline
from app.pipeline import index
from app import BASE


@pytest.mark.integration
def test_structured_formats_and_ocr(config, monkeypatch):
    enable_offline()
    monkeypatch.setenv('FILE_INTEL_DENY_ALL', '1')
    from eval.corpus import formats
    formats(config.roots[0])
    pool = ExtractionPool(config)
    expected = {'invoice.pdf':'pdf','wrong-extension.txt':'pdf','ledger.xlsx':'xlsx',
                'research.docx':'docx','search.pptx':'pptx','notes.html':'html','scanned-invoice.png':'png'}
    try:
        for name, label in expected.items():
            documents = pool.run({'path': str(config.roots[0] / name), 'magika_label': label})
            assert documents[0].extraction_status == 'ok', name
            assert documents[0].normalized_text.strip(), name
            assert documents[0].chunks, name
            if name == 'scanned-invoice.png':
                assert '0142' in documents[0].normalized_text
            if name == 'ledger.xlsx':
                assert documents[0].tables
    finally:
        pool.close()


@pytest.mark.integration
def test_containers_and_email(config):
    from eval.corpus import formats
    formats(config.roots[0])
    result = _bytes((config.roots[0] / 'notes.zip').read_bytes(), 'notes.zip', 'zip', config)
    assert result[0].extraction_status == 'partial'
    assert result[1].metadata['parent_path'] == 'notes.zip'
    assert len(result) == 2
    message = _bytes((config.roots[0] / 'message.eml').read_bytes(), 'message.eml', 'txt', config)[0]
    assert message.metadata['headers']['Subject'] == 'Offline invoice'
    assert 'From:' not in message.normalized_text
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as z:
        z.writestr('large.txt', 'hello ' * 1000)
    capped = replace(config, archive_total_mb=0)
    assert _bytes(payload.getvalue(), 'large.zip', 'zip', capped)[0].extraction_status == 'partial'


@pytest.mark.integration
def test_corrupt_quarantine_and_caps(config, store):
    (config.roots[0] / 'broken.pdf').write_bytes((BASE / 'demo/formats/invoice.pdf').read_bytes()[:100])
    (config.roots[0] / 'unknown.bin').write_bytes(b'\x00\x01\x02\xff' * 100)
    outcome = index(config, store)
    assert outcome['failed'] == 1
    failed = store.one("SELECT * FROM files WHERE path LIKE '%broken.pdf'")
    assert failed['status'] == 'quarantined' and failed['failures'] == 2
    assert index(config, store)['indexed'] == 0
    assert store.verify_audit()
