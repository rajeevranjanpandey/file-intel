"""Pure interpretation boundary: no file operations, database or action imports."""
import json
import re

SCHEMA = {'type': 'object', 'properties': {
    'name': {'type': 'string'}, 'summary': {'type': 'string'},
    'tags': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 5}},
    'required': ['name', 'summary', 'tags'], 'additionalProperties': False}

def label(evidence, generate=None):
    fallback = {'name': ' '.join(evidence['keywords'][:3]) or 'Uncategorized',
                'summary': 'Documents grouped by shared content.', 'tags': evidence['keywords'][:5],
                'source': 'keyword', 'error': ''}
    if generate is None:
        return fallback
    try:
        output = generate(evidence, SCHEMA)
        value = json.loads(output)
        if set(value) != {'name', 'summary', 'tags'}:
            raise ValueError('Unexpected output fields')
        if not isinstance(value['name'], str) or not 1 <= len(value['name'].split()) <= 6:
            raise ValueError('Name must contain 1–6 words')
        if not isinstance(value['summary'], str) or not value['summary'].strip() or len(value['summary']) > 700 or len(re.findall(r'[.!?](?:\s|$)', value['summary'])) > 2:
            raise ValueError('Summary exceeds contract')
        if not isinstance(value['tags'], list) or len(value['tags']) > 5 or any(not isinstance(t, str) or not t.strip() or len(t) > 50 for t in value['tags']):
            raise ValueError('Invalid tags')
        return {**value, 'source': 'llm', 'error': ''}
    except Exception as exc:
        return {**fallback, 'error': str(exc)}
