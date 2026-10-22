"""Loss-visible original-text windows for the existing SDK wire contract."""
from __future__ import annotations

import hashlib
import json

from langchain_text_splitters import RecursiveCharacterTextSplitter


MAX_RUNTIME_ITEMS = 20
MAX_RUNTIME_TEXT_UNITS = 4000
MAX_RUNTIME_BODY_BYTES = 250_000  # below the runtime's 256000-byte hard limit
CONTEXT_BATCH_BYTES = 220_000


class ContextBudgetError(ValueError):
    pass


def utf16_units(text):
    return len(text.encode("utf-16-le")) // 2


def evidence_source(item):
    metadata = item.get("metadata") or {}
    parts = [item["document_keyword"][:120]]
    excerpt = metadata.get("excerpt")
    if excerpt:
        parts.append(f"原片段字符[{excerpt['start_char']},{excerpt['end_char']})/{excerpt['parent_chars']}")
    for key in ("source_type", "scope", "jurisdiction", "doc_no", "timeliness", "implementation_date", "applicability"):
        if metadata.get(key):
            parts.append(f"{key}={str(metadata[key])[:50]}")
    if metadata.get("scope") == "law":
        parts.append("法规效力、适用性及附件仍须复核")
    # Runtime uses JS .slice(0,500); do not cut a supplementary character there.
    text = " | ".join(parts)
    while utf16_units(text) > 500:
        text = text[:-1]
    return text


def runtime_payload(*, message, instructions, evidence, conversation=None):
    conversation = conversation or []
    if len(evidence) > MAX_RUNTIME_ITEMS or any(utf16_units(item["content"]) > MAX_RUNTIME_TEXT_UNITS for item in evidence):
        raise ContextBudgetError("原文超过 SDK 单批限制，必须先分窗分批，不能静默截断")
    if len(conversation) > 12 or any(utf16_units(item["content"]) > 4000 for item in conversation):
        raise ContextBudgetError("会话超过 SDK 限制，不能静默丢弃历史")
    if utf16_units(message) > 8000 or utf16_units(instructions) > 24000:
        raise ContextBudgetError("问题或指令超过 SDK 限制")
    return {"message": message, "instructions": instructions, "conversation": conversation,
            "evidence": [{"type": "rag", "id": str(index + 1), "text": item["content"],
                          "source": evidence_source(item), "page": item.get("page_num")}
                         for index, item in enumerate(evidence)]}


def payload_bytes(payload):
    # Matches httpx's UTF-8 JSON encoding rather than Python character counts.
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _splitter(size, overlap):
    return RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap, add_start_index=True,
                                         strip_whitespace=False, separators=["\n\n", "\n", "。", "；", " ", ""])


def _spans(text):
    spans = []
    for document in _splitter(3500, 120).create_documents([text]):
        start = document.metadata["start_index"]
        if utf16_units(document.page_content) <= MAX_RUNTIME_TEXT_UNITS:
            spans.append((start, start + len(document.page_content)))
        else:
            # Only supplementary-heavy chunks need smaller Python-char windows.
            for child in _splitter(2000, 80).create_documents([document.page_content]):
                child_start = start + child.metadata["start_index"]
                spans.append((child_start, child_start + len(child.page_content)))
    end = 0
    for start, stop in spans:
        if start < 0 or start > end or stop > len(text) or stop <= start:
            break
        end = max(end, stop)
    else:
        if end == len(text):
            return spans, "recursive_character"
    # Repeated identical paragraphs can make upstream start_index ambiguous.
    # Fall back to deterministic exact spans; never invent a location or skip text.
    spans, start = [], 0
    while start < len(text):
        stop = min(len(text), start + 3500)
        if utf16_units(text[start:stop]) > MAX_RUNTIME_TEXT_UNITS:
            stop = min(len(text), start + 2000)
        spans.append((start, stop))
        if stop == len(text):
            break
        start = stop - 120
    return spans, "fixed_character_fallback"


def prepare_windows(items, *, max_windows):
    parents = []
    for item in items:
        text = item["content"]
        if utf16_units(text) <= MAX_RUNTIME_TEXT_UNITS:
            parents.append([item])
            continue
        spans, splitter = _spans(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        windows = []
        for index, (start, stop) in enumerate(spans):
            window = dict(item)
            metadata = dict(item.get("metadata") or {})
            metadata["excerpt"] = {"parent_chunk_id": item.get("chunk_id"), "parent_content_sha256": digest,
                                   "start_char": start, "end_char": stop, "parent_chars": len(text),
                                   "offset_unit": "unicode_codepoint", "window_index": index,
                                   "window_count": len(spans), "splitter": splitter}
            metadata["content_sha256"] = hashlib.sha256(text[start:stop].encode()).hexdigest()
            if metadata.get("rerank"):
                metadata["rerank"] = {**metadata["rerank"], "applies_to": "parent_excerpt"}
            window.update(content=text[start:stop], metadata=metadata)
            windows.append(window)
        parents.append(windows)
    # Round-robin preserves different sources/parents when the budget is tight.
    ordered = [parent[index] for index in range(max((len(parent) for parent in parents), default=0))
               for parent in parents if index < len(parent)]
    return ordered[:max_windows], len(ordered)


def pack_batches(items, *, message, instructions, conversation=None):
    base = runtime_payload(message=message, instructions=instructions, evidence=[], conversation=conversation)
    if payload_bytes(base) > CONTEXT_BATCH_BYTES:
        raise ContextBudgetError("问题、指令和会话已超过上下文批次预算")
    batches, current = [], []
    for item in items:
        trial = [*current, item]
        fits = len(trial) <= MAX_RUNTIME_ITEMS and payload_bytes(runtime_payload(
            message=message, instructions=instructions, evidence=trial, conversation=conversation,
        )) <= CONTEXT_BATCH_BYTES
        if not fits:
            if not current:
                raise ContextBudgetError("单个证据窗口超过批次字节预算")
            batches.append(current)
            current = [item]
            if payload_bytes(runtime_payload(message=message, instructions=instructions, evidence=current, conversation=conversation)) > CONTEXT_BATCH_BYTES:
                raise ContextBudgetError("单个证据窗口超过批次字节预算")
        else:
            current = trial
    return [*batches, current] if current or not batches else batches
