"""规则核对服务客户端（对接对方同事的 rule_check API）。

职责：
  1. health()  —— 探测对方服务是否 ready（带短期缓存，避免每次核对都探）。
  2. check()   —— 把一个任务的单据字段提交给对方核对，返回 RuleResult 列表。
  3. to_payload() —— 把 ORM Document 列表转成对方 API 的请求体（与本地 rule_engine
                    的取数口径一致：type_code / fields / field_sources / pdf_file）。

约定的接口契约（对方 API 未最终确定前，先按合理约定实现；地址见 config）：

  GET  {RULE_CHECK_BASE_URL}{RULE_CHECK_HEALTH_PATH}
       → 200；body 可为空，或 {"status": "ok|ready|up|healthy"}。

  POST {RULE_CHECK_BASE_URL}{RULE_CHECK_PATH}
       请求 JSON:
         {
           "task_code": "2026-0001",
           "drawdown_currency": "USD",
           "drawdown_amount": 2000000.0,
           "documents": [
             {
               "doc_code": "D1",
               "type_code": "DRAWDOWN_INSTRUCTION",
               "pdf_file": "set_9/drawdown_instruction.pdf",
               "fields": {"currency": "USD", "amount": 2000000, ...},
               "field_sources": {"currency": {"page": 1, "bbox": [..]}, ...}
             }, ...
           ]
         }
       响应 JSON（任一形状都兼容）:
         {"results": [ {rule_id, rule_name, dimension, status, why, suggestion, detail}, ... ]}
         或直接是上述 results 列表。
       其中 status ∈ {pass, fail, warn, skip}；
       detail 为明细行列表，每行 [label, value, flag] 或 [label, value, flag, source]，
       source = {doc_code, type_code, pdf_file, page, bbox}（供前端「定位原文」）。

对方未就绪（未配置地址 / health 不通 / 调用异常）时，由 rule_orchestrator 回退到
本地内置 rule_engine，保证流程不阻断。
"""
from __future__ import annotations

import logging
import time

import httpx

from .config import settings
from .rule_engine.base import RuleResult, Status

log = logging.getLogger(__name__)

# ---- health 结果短期缓存（秒）：避免同一批核对里反复探测拖慢响应 ----
_HEALTH_TTL = 10.0
_health_cache: dict[str, float | bool] = {"ts": 0.0, "ok": False}


def configured() -> bool:
    """是否配置了对方服务地址。未配置 → 直接走本地 rule_engine。"""
    return bool(settings.RULE_CHECK_BASE_URL.strip())


def health(force: bool = False) -> bool:
    """探测对方 rule_check 服务是否 ready。

    - 未配置地址：返回 False（走本地）。
    - 10 秒内探测过：复用缓存结果（force=True 可强制刷新）。
    - 200 响应即视为 ready；若 body 含 status 字段，还要求值在 {ok,ready,up,healthy}。
    """
    if not configured():
        return False

    now = time.monotonic()
    if not force and (now - float(_health_cache["ts"])) < _HEALTH_TTL:
        return bool(_health_cache["ok"])

    url = settings.RULE_CHECK_BASE_URL.rstrip("/") + settings.RULE_CHECK_HEALTH_PATH
    ok = False
    try:
        resp = httpx.get(url, timeout=settings.RULE_CHECK_HEALTH_TIMEOUT)
        if resp.status_code == 200:
            ok = True
            # 若返回 JSON 且带 status，进一步校验语义
            try:
                data = resp.json()
                if isinstance(data, dict) and "status" in data:
                    ok = str(data["status"]).lower() in {"ok", "ready", "up", "healthy", "1", "true"}
            except Exception:
                pass  # 非 JSON body，200 即视为健康
        log.info("rule_check health url=%s status=%s → ready=%s", url, resp.status_code, ok)
    except Exception as exc:
        log.warning("rule_check health failed url=%s: %s", url, exc)
        ok = False

    _health_cache["ts"] = now
    _health_cache["ok"] = ok
    return ok


def to_payload(task, documents: list) -> dict:
    """把 ORM 任务 + 单据列表转成对方 API 请求体。

    取数口径与本地 rule_engine.runner.build_bundle 完全一致：
    type_code / fields(dict) / field_sources(dict) / doc_code / pdf_file。
    """
    docs_payload = []
    for d in documents:
        type_code = d.type_code.value if hasattr(d.type_code, "value") else str(d.type_code)
        docs_payload.append({
            "doc_code": getattr(d, "doc_code", None),
            "type_code": type_code,
            "pdf_file": getattr(d, "pdf_file", None),
            "fields": d.fields or {},
            "field_sources": getattr(d, "field_sources", None) or {},
        })
    return {
        "task_code": getattr(task, "task_code", None),
        "drawdown_currency": getattr(task, "drawdown_currency", None),
        "drawdown_amount": float(task.drawdown_amount) if getattr(task, "drawdown_amount", None) is not None else None,
        "documents": docs_payload,
    }


_STATUS_MAP = {
    "pass": Status.PASS, "fail": Status.FAIL,
    "warn": Status.WARN, "skip": Status.SKIP,
}


def _coerce_result(item: dict) -> RuleResult | None:
    """把对方返回的单条结果 dict 映射为内部 RuleResult。缺失字段给默认值。"""
    if not isinstance(item, dict):
        return None
    status = _STATUS_MAP.get(str(item.get("status", "")).lower())
    if status is None:
        log.warning("rule_check 返回未知 status=%r，按 skip 处理: %r", item.get("status"), item.get("rule_id"))
        status = Status.SKIP
    detail = item.get("detail") or []
    if not isinstance(detail, list):
        detail = []
    return RuleResult(
        rule_id=str(item.get("rule_id", "")),
        rule_name=str(item.get("rule_name", "")),
        dimension=str(item.get("dimension", "")),
        status=status,
        why=str(item.get("why", "") or ""),
        suggestion=str(item.get("suggestion", "") or ""),
        detail=detail,
    )


def check(task, documents: list) -> list[RuleResult]:
    """调用对方 rule_check API，返回 RuleResult 列表。

    失败（网络/非 200/解析异常）抛出 RuntimeError，由 orchestrator 捕获并回退本地引擎。
    """
    url = settings.RULE_CHECK_BASE_URL.rstrip("/") + settings.RULE_CHECK_PATH
    payload = to_payload(task, documents)
    log.info("rule_check POST %s  docs=%d", url, len(payload["documents"]))
    try:
        resp = httpx.post(url, json=payload, timeout=settings.RULE_CHECK_TIMEOUT)
    except Exception as exc:
        raise RuntimeError(f"rule_check 调用失败: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"rule_check 非 200: {resp.status_code} {resp.text[:200]}")

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"rule_check 响应非 JSON: {exc}") from exc

    # 兼容 {"results": [...]} 或直接 [...]
    raw = data.get("results") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise RuntimeError(f"rule_check 响应缺少 results 列表: {str(data)[:200]}")

    results = [r for r in (_coerce_result(x) for x in raw) if r is not None]
    log.info("rule_check 返回 %d 条结果", len(results))
    return results
