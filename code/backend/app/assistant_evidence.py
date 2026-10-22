"""Assistant-only source attribution, independent of RAG retrieval internals.

References prove membership in this run's tool payload, not semantic correctness.
IDs are assigned by the server, never inferred from model-written URLs/titles.
"""
from __future__ import annotations

import re

REFERENCE = re.compile(r'\[E([0-9]+)\]')


def prepare_evidence(retrieved: list[dict], experts: list[dict]) -> list[dict]:
    experts = experts[:3]
    candidates = retrieved[:20 - len(experts)] + experts
    prepared = []
    reference = 0
    for item in candidates:
        if item.get('type') != 'expert':
            reference += 1
        prepared.append({
            'type': str(item.get('type') or 'evidence')[:40],
            'id': str(item.get('id') or '')[:160],
            'reference_id': f'E{reference}' if item.get('type') != 'expert' else None,
            'text': str(item.get('text') or '')[:4000],
            'source': str(item.get('source') or '')[:500],
            'page': item.get('page'),
        })
    return prepared


def cited_sources(answer: str, evidence: list[dict], *, tool_used: bool) -> tuple[list[dict], bool]:
    """Return cited sources in first appearance order, and whether all IDs resolve."""
    refs = list(dict.fromkeys(f'E{match.group(1)}' for match in REFERENCE.finditer(answer)))
    available = {item['reference_id']: item for item in evidence
                 if item.get('reference_id') and item.get('type') != 'expert'} if tool_used else {}
    if any(ref not in available for ref in refs):
        return [], False
    return [{
        'id': ref, 'reference_id': ref, 'source_id': available[ref]['id'],
        'label': available[ref]['source'], 'source': available[ref]['source'],
        'detail': available[ref]['text'][:180], 'page': available[ref].get('page'),
    } for ref in refs], True
