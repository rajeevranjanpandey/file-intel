"""Answer a question from the indexed files, citing the passages used.

Retrieval reuses hybrid search. The local model may only rephrase what the passages say; when it
is unavailable, slow, or returns something outside the contract, an extractive answer is built
from the passage sentences closest in meaning to the question.
"""
import json
import re
import numpy as np
from app.search import search
from app.represent import Representer

SCHEMA = {'type': 'object', 'properties': {
    'answer': {'type': 'string'},
    'citations': {'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 5}},
    'required': ['answer', 'citations'], 'additionalProperties': False}


# A passage found only by meaning must be at least this close to the question. Unrelated text scores
# near zero with MiniLM; without a floor, semantic search would always return something to cite.
MIN_COSINE = 0.25


def passages_for(store, config, question, limit=5, representer=None):
    rows = search(store, config, question, limit=limit, mode='hybrid', representer=representer)
    # Word matches alone are weak for questions (they include words like "the"), except for identifiers.
    has_identifier = any(any(c.isdigit() for c in token) for token in question.split())
    rows = [r for r in rows if r.get('evidence') and r['evidence'] != 'Filename/path match'
            and ((r.get('cosine') or 0) >= MIN_COSINE or (has_identifier and r.get('keyword_rank')))]
    passages, seen = [], {}
    for r in rows:
        key = ' '.join(r['evidence'].casefold().split())
        if key in seen:  # identical copies add a file name, not another passage to read
            seen[key]['copies'].append(r['path'])
            continue
        seen[key] = {'n': len(passages) + 1, 'document_id': r['document_id'], 'path': r['path'], 'title': r['title'],
                     'page': r.get('page'), 'text': r['evidence'][:1200], 'copies': []}
        passages.append(seen[key])
    return passages


def _sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.split()) >= 4]


def extractive(question, passages, representer, keep=2):
    """The passage sentences closest in meaning to the question, each with its passage number."""
    candidates = list({s.casefold(): (p['n'], s) for p in reversed(passages) for s in _sentences(p['text'])}.values())
    candidates = sorted(candidates) or [(p['n'], p['text']) for p in passages]
    if not candidates:
        return '', []
    vectors = representer.encode([question] + [s for _, s in candidates])
    scores = vectors[1:] @ vectors[0]
    best = sorted(np.argsort(-scores)[:keep])  # keep reading order within the passages
    return ' '.join(f'{candidates[i][1]} [{candidates[i][0]}]' for i in best), sorted({candidates[i][0] for i in best})


def validate(output, count):
    value = json.loads(output)
    answer, cited = value.get('answer'), value.get('citations')
    if set(value) != {'answer', 'citations'} or not isinstance(answer, str) or not answer.strip() or len(answer) > 1200:
        raise ValueError('Answer outside contract')
    if not isinstance(cited, list) or not all(isinstance(c, int) and 1 <= c <= count for c in cited):
        raise ValueError('Citations must name the supplied passages')
    return answer.strip(), sorted(set(cited))


def ask(store, config, question, generate=None, representer=None, limit=5):
    question = ' '.join(question.split())
    if not question:
        return {'answer': '', 'passages': [], 'citations': [], 'source': 'none', 'error': 'Enter a question'}
    representer = representer or Representer(config)
    passages = passages_for(store, config, question, limit, representer)
    if not passages:
        return {'answer': 'No indexed passage matches this question.', 'passages': [], 'citations': [],
                'source': 'none', 'error': ''}
    error = ''
    if generate is not None:
        try:
            payload = {'question': question, 'passages': [{'n': p['n'], 'text': p['text']} for p in passages]}
            answer, cited = validate(generate(payload, SCHEMA), len(passages))
            if cited:
                return {'answer': answer, 'passages': passages, 'citations': cited, 'source': 'llm', 'error': ''}
            error = 'The local model cited no passage'
        except Exception as exc:
            error = str(exc)
    answer, cited = extractive(question, passages, representer)
    return {'answer': answer, 'passages': passages, 'citations': cited, 'source': 'extractive', 'error': error}
