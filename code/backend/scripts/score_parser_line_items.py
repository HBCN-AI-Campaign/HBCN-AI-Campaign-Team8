"""Score frozen garment invoice rows separately from scalar field coverage.

Candidate coverage is diagnostic only: it must never become usable output.
"""
import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


CELLS = ('quantity', 'unit_price', 'amount', 'unit', 'currency')


def style(row):
    tokens = set(re.findall(r'(?<![A-Z0-9-])[A-Z]-[A-Z]{2}-\d{2}(?![A-Z0-9-])',
                           str(row.get('style', '')) + ' ' + str(row.get('description', ''))))
    return next(iter(tokens)) if len(tokens) == 1 else None


def same_cell(actual, expected, key):
    if key in ('quantity', 'unit_price', 'amount'):
        if isinstance(actual, (bool, float)) or actual is None:
            return False
        try:
            a, b = Decimal(str(actual)), Decimal(str(expected))
            return a.is_finite() and b.is_finite() and a == b
        except InvalidOperation:
            return False
    return actual == expected


def located(row, expected, evidence):
    ids = row.get('block_ids')
    if not isinstance(ids, list) or not ids or not all(i in evidence for i in ids):
        return False
    sources = [evidence[i] for i in ids]
    for source in sources:
        box = source.get('bbox', [])
        if (len(box) != 4 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in box)
                or not 0 <= box[0] < box[2] <= 1 or not 0 <= box[1] < box[3] <= 1):
            return False
    return set(expected['pages']).issubset({s.get('page') for s in sources})


def rows_score(rows, expected_rows, evidence):
    expected_by_style = {r['style']: r for r in expected_rows}
    if len(expected_by_style) != len(expected_rows):
        raise ValueError('DUPLICATE_GOLD_STYLE')
    counts = Counter(expected_rows=len(expected_rows), expected_cells=len(expected_rows) * len(CELLS),
                     actual_rows=len(rows), correct_rows=0, correct_cells=0,
                     wrong_or_duplicate_rows=0, correct_rows_with_page_and_boxes=0)
    groups = {}
    for row in rows:
        groups.setdefault(style(row), []).append(row)
    details = []
    for identity, expected in expected_by_style.items():
        matches = groups.get(identity, [])
        unique = len(matches) == 1
        row = matches[0] if unique else {}
        cells = {k: unique and same_cell(row.get(k), expected[k], k) for k in CELLS}
        correct = all(cells.values())
        counts['correct_cells'] += sum(cells.values())
        counts['correct_rows'] += correct
        has_source = correct and located(row, expected, evidence)
        counts['correct_rows_with_page_and_boxes'] += has_source
        details.append(dict(style=identity, matches=len(matches), cells=cells, correct=correct,
                            valid_page_and_boxes=bool(has_source)))
    for row in rows:
        identity = style(row)
        expected = expected_by_style.get(identity)
        counts['wrong_or_duplicate_rows'] += (
            expected is None or len(groups[identity]) != 1
            or not all(same_cell(row.get(k), expected[k], k) for k in CELLS))
    counts['complete_correct_collection'] = int(
        len(rows) == len(expected_rows) and counts['correct_rows'] == len(expected_rows))
    return dict(counts), details


def score(gold, result):
    if result.get('source_sha256') != gold['sha256']:
        raise ValueError('RESULT_SOURCE_HASH_MISMATCH')
    if result.get('source_filename') != gold['filename'] or result.get('page_count') != gold['pages']:
        raise ValueError('RESULT_SOURCE_IDENTITY_MISMATCH')
    field = next((f for f in result.get('fields', []) if f.get('key') == 'line_items'), {})
    candidates = field.get('candidates', [])
    usable = (field.get('status') == 'accepted' and isinstance(field.get('value'), list)
              and not result.get('issues') and result.get('status') != 'failed')
    rows = field['value'] if usable else []
    # A final value may cite only its matching candidate, never evidence borrowed
    # from a different model response or conflicting row collection.
    evidence = {}
    for c in candidates:
        if not c.get('issues') and c.get('normalized_value') == rows:
            evidence.update({e['block_id']: e for e in c.get('evidence', [])})
    for r in field.get('row_results', []):
        if r.get('status') == 'accepted' and r.get('value') in rows:
            evidence.update({s['block_id']: s for c in r.get('cells', {}).values() for s in c.get('sources', [])})
    counts, details = rows_score(rows, gold['line_items'], evidence)
    counts['collection_accepted'] = int(usable)
    diagnostics = []
    for c in candidates:
        value = c.get('normalized_value')
        if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
            continue
        candidate_counts, _ = rows_score(value, gold['line_items'],
                                        {e['block_id']: e for e in c.get('evidence', [])})
        diagnostics.append(dict(method=c.get('method'), issues=c.get('issues'), counts=candidate_counts))
    validated=field.get('row_results', [])
    if validated:
        value=[r['value'] for r in validated if r.get('value')]
        row_evidence={s['block_id']: s for r in validated for c in r.get('cells', {}).values() for s in c.get('sources', [])}
        candidate_counts,_=rows_score(value, gold['line_items'], row_evidence)
        diagnostics.append(dict(method='vision_records',issues=field.get('issues'),counts=candidate_counts,
                                individually_validated_rows=sum(r.get('status')=='accepted' for r in validated)))
    return dict(counts=counts, details=details, candidate_diagnostics=diagnostics,
                printed_totals={k: gold[k] for k in ('printed_total_quantity', 'printed_total_amount')},
                row_sums={k: format(sum(Decimal(r[k]) for r in gold['line_items']), 'f')
                          for k in ('quantity', 'amount')},
                interpretation='只统计最终 accepted 集合；候选逐行覆盖单列，不能作为可用结果。位置检查页码和框合法性，不代表单元格 IoU。印刷合计与逐行和分别保留，不自行改值。')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--gold', default='tests/fixtures/parser_set6_invoice.json')
    p.add_argument('--results', required=True)
    p.add_argument('--source-root')
    args = p.parse_args()
    gold_bytes = Path(args.gold).read_bytes()
    gold = json.loads(gold_bytes)
    documents = [d for d in gold['documents'] if 'line_items' in d]
    if len(documents) != 1:
        raise ValueError('EXPECTED_ONE_GARMENT_INVOICE')
    doc = documents[0]
    if args.source_root and hashlib.sha256((Path(args.source_root) / doc['filename']).read_bytes()).hexdigest() != doc['sha256']:
        raise ValueError('SOURCE_HASH_MISMATCH')
    root = Path(args.results)
    result = json.loads((root / (Path(doc['filename']).stem + '.result.json')).read_text(encoding='utf-8'))
    report = score(doc, result)
    report.update(annotation_version=gold['annotation_version'], scope=gold['scope'],
                  gold_sha256=hashlib.sha256(gold_bytes).hexdigest())
    (root / 'line-items-score.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'details'}, ensure_ascii=False, indent=2))
