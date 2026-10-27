import json
import numpy as np
from app.analyze import dedupe, relation

AUDIT = ('Annual financial audit 2026. The finance department reviewed all quarterly accounts. Total revenue reached '
         '1450000 AED against operational expenditures of 820000 AED. Bank statements and supplier ledgers were verified. '
         'Tax provisions and compliance obligations meet regulatory standards.')
REVISED = AUDIT.replace('against operational expenditures of 820000 AED', 'with a verified net operating margin')
SUMMARY = 'Executive summary 2026. Expenditures held at 820000 AED while revenue met target. Supplier ledgers reconciled.'
OTHER = ('Accounts payable procedure. Review each supplier invoice, validate the purchase order, confirm bank details '
         'and record payment in the financial ledger before the monthly close and the treasury report.')


def test_revision_reports_the_changed_words():
    tier, evidence = relation(AUDIT, REVISED, 0.95, 0.99)
    assert tier == 3 and evidence['relation'] == 'revision'
    assert evidence['changes'][0]['before'].startswith('against operational expenditures')
    assert evidence['shared_wording'] >= 0.5


def test_summary_needs_meaning_and_shared_figures():
    tier, evidence = relation(AUDIT, SUMMARY, 0.8, 0.93)
    assert tier == 4 and evidence['relation'] == 'summary' and evidence['shorter'] == 'right'
    assert '820000' in evidence['shared_figures']
    assert relation(AUDIT, SUMMARY.replace('820000', 'stable'), 0.8, 0.93) == (None, None)
    assert relation(AUDIT, SUMMARY, 0.6, 0.93) == (None, None)


def test_excerpt_and_unrelated_same_topic_document():
    excerpt = AUDIT[:AUDIT.index('Bank')]
    assert relation(excerpt, AUDIT, 0.72, 0.93)[1]['relation'] == 'excerpt'
    assert relation(AUDIT, OTHER, 0.72, 0.93) == (None, None)


def test_dedupe_keeps_reviews_and_adds_relation_tiers(store, config):
    vectors = {'a': [1, 0, 0], 'a-copy': [1, 0, 0], 'b': [0.97, 0.243, 0], 'c': [0.8, 0.6, 0], 'd': [0, 0, 1]}
    ids = {}
    for name, text in (('a', AUDIT), ('a-copy', AUDIT), ('b', REVISED), ('c', SUMMARY), ('d', OTHER)):
        fid = store.db.execute('INSERT INTO files(path,sha256) VALUES(?,?)', (str(config.roots[0] / name), name[0])).lastrowid
        did = store.db.execute("INSERT INTO documents(file_id,text,text_sha256,extraction_status) VALUES(?,?,?,'ok')",
                               (fid, text, 't' + name[0])).lastrowid
        vector = np.array(vectors[name], np.float32)
        store.db.execute('INSERT INTO embeddings VALUES(NULL,?,?,?,?)', (did, 'm', 3, (vector / np.linalg.norm(vector)).tobytes()))
        ids[name] = did
    store.db.commit()
    # The copy joins a's family, so it adds one exact pair and no extra version or summary pairs.
    assert dedupe(store, config) == 3
    pairs = {(r['left_id'], r['right_id']): r for r in store.rows('SELECT * FROM duplicates')}
    assert pairs[(ids['a'], ids['a-copy'])]['tier'] == 1
    assert pairs[(ids['a'], ids['b'])]['tier'] == 3
    assert pairs[(ids['a'], ids['c'])]['tier'] == 4
    assert json.loads(pairs[(ids['a'], ids['c'])]['evidence_json'])['shorter'] == 'right'
    store.db.execute("UPDATE duplicates SET decision='keep-both' WHERE tier=4")
    store.db.commit()
    dedupe(store, config)
    assert store.one('SELECT decision FROM duplicates WHERE tier=4')['decision'] == 'keep-both'
    assert store.verify_audit()
