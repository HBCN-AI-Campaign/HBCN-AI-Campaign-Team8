"""Adapt the pinned langchain-postgres RRF to business query families.

RRF is delegated to the existing upstream library. Per-family averaging keeps
several near-synonym rewrites from manufacturing additional independent votes.
This combines candidates, not legal authority or an approval probability.
"""
from __future__ import annotations

import hashlib
from collections import Counter

from langchain_postgres.v2.hybrid_search_config import reciprocal_rank_fusion


def evidence_key(item):
    metadata = item.get("metadata") or {}
    source = metadata.get("source_type", "knowledge_base")
    version = str(metadata.get("version") or "")
    document = str(item.get("document_id") or item.get("source_url") or "")
    chunk = str(item.get("chunk_id") or "")
    # Content hash also separates changed text under a reused external ID.
    digest = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
    return "|".join([source, document, version, chunk, digest])


def fuse_channels(vector_items, lexical_items, *, top_k):
    """Equal-weight rank fusion; keep original, incomparable channel scores."""
    candidates, traces, rows = {}, {}, []
    for channel, items in (("vector", vector_items), ("lexical", lexical_items)):
        channel_rows, seen = [], set()
        for item in items:
            key = evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            candidates.setdefault(key, item)
            # Upstream sorts primary distances ascending, secondary keyword
            # relevance descending. Encode the already-ranked lexical order.
            channel_rows.append({"id": key, "distance": len(channel_rows) if channel == "vector" else -len(channel_rows)})
            traces.setdefault(key, []).append({"channel": channel, "rank": len(channel_rows),
                                               "score": item.get("similarity"),
                                               "score_type": "cosine_similarity" if channel == "vector" else "ts_rank_cd"})
        rows.append(channel_rows)
    ranked = reciprocal_rank_fusion(*rows, rrf_k=61, fetch_top_k=len(candidates))
    scores = {row["id"]: row["distance"] for row in ranked}
    result = []
    for key in sorted(scores, key=lambda value: (-scores[value], value))[:top_k]:
        item = dict(candidates[key])
        metadata = dict(item.get("metadata") or {})
        metadata["channel_fusion"] = {"score_type": "rrf", "score": scores[key], "hits": traces[key]}
        item.update(metadata=metadata, similarity=None)
        result.append(item)
    return result


def fuse_sources(source_pools, *, top_k):
    """Fuse already-ranked source pools; source scores never share a scale."""
    scores, candidates, traces = {}, {}, {}
    for source, items in source_pools.items():
        rows, seen = [], set()
        for item in items:
            key = evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            candidates.setdefault(key, item)
            rows.append({"id": key, "distance": len(rows)})
            traces.setdefault(key, []).append({"source": source, "rank": len(rows)})
        for row in reciprocal_rank_fusion(rows, [], rrf_k=61, fetch_top_k=len(rows)):
            scores[row["id"]] = scores.get(row["id"], 0.0) + row["distance"]
    result = []
    for key in sorted(scores, key=lambda value: (-scores[value], value))[:top_k]:
        item = dict(candidates[key])
        metadata = dict(item.get("metadata") or {})
        metadata["source_fusion"] = {"score_type": "rrf", "score": scores[key], "hits": traces[key]}
        item.update(metadata=metadata, similarity=None)
        result.append(item)
    return result


def fuse_query_results(batches, *, top_k):
    """batches: [(SearchQuery, list[evidence])]; each list is already ranked."""
    counts = Counter(query.family for query, _ in batches)
    scores, candidates, traces = {}, {}, {}
    for query, items in batches:
        rows, seen = [], set()
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("content"), str) or not item["content"].strip():
                continue
            key = evidence_key(item)
            if key in seen:
                continue
            seen.add(key)
            # Upstream expects the identifier as first column, then distance.
            rows.append({"id": key, "distance": len(rows)})
            candidates.setdefault(key, item)
            traces.setdefault(key, []).append({"family": query.family, "rank": len(rows), "score": item.get("similarity")})
        ranked = reciprocal_rank_fusion(rows, [], rrf_k=61, fetch_top_k=len(rows))
        for row in ranked:
            key = row["id"]
            scores[key] = scores.get(key, 0.0) + row["distance"] / counts[query.family]
    result = []
    for key in sorted(scores, key=lambda value: (-scores[value], value))[:top_k]:
        item = dict(candidates[key])
        metadata = dict(item.get("metadata") or {})
        metadata["retrieval"] = {"score_type": "family_normalized_rrf", "fusion_score": scores[key], "hits": traces[key]}
        # Fused rankings are not cosine similarities or confidence probabilities.
        item.update(metadata=metadata, similarity=None)
        result.append(item)
    return result
