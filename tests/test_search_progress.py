from app.search import search


def test_empty_scope_reports_honest_completion(store, config):
    events = []
    assert search(store, config, 'invoice', progress=lambda *event: events.append(event)) == []
    assert events[0][:2] == ('scope', 'running')
    assert events[-1][:2] == ('results', 'complete')
    assert {e[0] for e in events if e[1] == 'skipped'} == {'keyword', 'semantic', 'rank'}
    assert '0 results' in events[-1][2]
