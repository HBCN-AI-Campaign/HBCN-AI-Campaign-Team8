"""AI 助手底座：Agent SDK 适配、受控工具和 SSE 事件编排。

业务边界：助手可以读取授权任务证据、调用 RAG 查询适配器并生成审核辅助建议，
但不写入任务审核状态、不改写规则结果，也不替审核人员做贷款最终结论。
"""
from __future__ import annotations

import asyncio
import httpx
import json
import logging
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from typing import Any

from . import models
from .assistant_skills import get_skill
from .config import settings

ASSISTANT_INSTRUCTIONS = (
    "你是境外贷款单据审核辅助助手。只能解释证据、检索知识、整理风险和起草人工复核意见。"
    "不得直接批准、拒绝或改变贷款审核结论；结论必须交给有权限的审核人员。"
    "回答要引用任务材料或规则结果，证据不足时明确说需要人工确认。"
    "不得输出内部思维链、草稿推理或工具参数，只给用户可见的结论、依据和简洁的执行摘要。"
)
logger = logging.getLogger(__name__)


def sdk_configured() -> bool:
    return bool(
        settings.ASSISTANT_RUNTIME_URL
        and settings.ASSISTANT_RUNTIME_TOKEN
    )


def task_for_user(db, user: models.User, task_code: str | None):
    """取任务并做最小数据级权限隔离。"""
    if not task_code:
        return None
    task = db.query(models.ReviewTask).filter_by(task_code=task_code).first()
    if not task:
        return None
    if user.role == models.Role.OPERATOR and task.submitted_by != user.id:
        return None
    return task


def task_context(task: models.ReviewTask | None) -> dict[str, Any]:
    if task is None:
        return {"task": None, "documents": [], "results": [], "citations": []}

    documents: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for doc in task.documents:
        type_code = getattr(doc.type_code, "value", doc.type_code)
        documents.append({
            "doc_code": doc.doc_code,
            "type_code": type_code,
            "fields": doc.fields or {},
        })
        citations.append({
            "id": f"document:{doc.id}",
            "label": f"{doc.doc_code} · {type_code}",
            "source": doc.pdf_file or doc.doc_code,
            "detail": "任务材料字段与原文定位",
        })

    results: list[dict[str, Any]] = []
    for row in task.results:
        status = getattr(row.status, "value", row.status)
        results.append({
            "rule_id": row.rule_id,
            "rule_name": row.rule_name,
            "status": status,
            "why": row.why,
            "suggestion": row.suggestion,
        })
        citations.append({
            "id": f"rule:{row.rule_id}",
            "label": row.rule_id,
            "source": "规则审核结果",
            "detail": row.rule_name,
            "status": status,
        })

    return {
        "task": {
            "task_code": task.task_code,
            "borrower": task.borrower,
            "currency": task.drawdown_currency,
            "amount": float(task.drawdown_amount),
            "status": getattr(task.status, "value", task.status),
        },
        "documents": documents,
        "results": results,
        "citations": citations,
    }


def search_evidence(context: dict[str, Any], query: str) -> list[dict[str, Any]]:
    """本地证据适配器，供无 RAG 配置时演示和 SDK tool 使用。

    配置 RAG 服务后，助手仍通过同一工具名调用；外部 RAG 的专用协议由
    `rag_service.RAGClient` 负责，避免把 RAGFlow 返回格式泄露给助手调用方。
    """
    terms = [term.lower() for term in query.split() if term.strip()]
    hits: list[dict[str, Any]] = []
    for item in context.get("results", []):
        haystack = json.dumps(item, ensure_ascii=False).lower()
        if not terms or any(term in haystack for term in terms):
            hits.append({
                "type": "rule",
                "id": item["rule_id"],
                "text": f'{item["rule_name"]}：{item["why"]}',
                "source": "规则审核结果",
            })
    for item in context.get("documents", []):
        haystack = json.dumps(item, ensure_ascii=False).lower()
        if not terms or any(term in haystack for term in terms):
            hits.append({
                "type": "document",
                "id": item["doc_code"],
                "text": json.dumps(item["fields"], ensure_ascii=False),
                "source": item["doc_code"],
            })
    return hits[:8]


def _rag_search(
    context: dict[str, Any],
    query: str,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """组合任务本地证据与外部 RAG 知识库证据。

    本地证据（规则结果 + 单据字段）始终返回，保证任务上下文不因 RAG 未配置、
    未开放范围或服务异常而丢失；RAG 配置后追加 business_rules / project_design
    的检索片段，作为 ``type="knowledge"`` 引用返回给助手与前端溯源。
    """
    hits: list[dict[str, Any]] = list(search_evidence(context, query))
    if not getattr(settings, "RAG_BASE_URL", ""):
        return hits

    try:
        from .rag_service import RAGClient

        # The current RAG service indexes shared business/project knowledge only.
        # Task documents are already permission-filtered and supplied as local evidence.
        result = RAGClient().query(
            query=query,
            scope="knowledge_base",
            task_code=(context.get("task") or {}).get("task_code"),
            top_k=6,
            agentic=True,
            include_external_law=False,
        )
    except Exception as exc:
        # 网关或 RAG 服务异常时保留本地证据，不阻断助手。
        logger.warning("Assistant RAG query failed (%s)", type(exc).__name__)
        warning = "知识库暂不可用；本次回复仅基于当前任务已加载的本地证据。"
        if warnings is not None and warning not in warnings:
            warnings.append(warning)
        return hits

    if result.get("warnings") and warnings is not None:
        warning = "知识库未能提供完整匹配证据；请结合当前任务材料人工核实。"
        if warning not in warnings:
            warnings.append(warning)

    for index, item in enumerate(result.get("evidence", []), start=1):
        hits.append({
            "type": "knowledge",
            "id": str(item.get("document_id") or item.get("id") or item.get("chunk_id") or f"kb-{index}"),
            "text": str(item.get("content") or item.get("text") or item.get("chunk") or ""),
            "source": str(item.get("document_name") or item.get("source_name") or item.get("title") or "知识库"),
            "page": item.get("page"),
        })
    return hits


def _strip_tool_echo(text: str) -> str:
    """去掉模型在真正调用工具前以纯文本形式回显的工具参数 JSON。

    部分 OpenAI-compatible 模型会在调用 function tool
    之前，把工具调用参数当作普通文本 delta 输出，例如
    ``{"query":"..."}``。这些字符不是给用户的答案，若直接拼进正文会在
    回复开头显示一串原始 JSON。
    """
    if not text:
        return text
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return text
    try:
        value, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return text
    if not isinstance(value, (dict, list)):
        return text
    remainder = stripped[end:].strip()
    # 只有去除后仍有实质内容才丢弃；避免把整段纯 JSON 回答删掉。
    if not remainder or remainder.startswith(("{", "[")):
        return text
    # 仅当像工具参数回显（含 query / question / input 等键）时剔除，
    # 降低误删以 JSON 开头的正常回答的风险。
    if isinstance(value, dict) and not any(
        key in value for key in ("query", "question", "input", "parameters")
    ):
        return text
    return remainder


def _safe_final_answer(text: str) -> str | None:
    """Reject obvious analysis/tool-planning text before it reaches users or storage."""
    answer = _strip_tool_echo(text).strip()
    internal_markers = (
        "我们需要回答用户",
        "用户要求两句话",
        "用户只是问",
        "没有具体单据审核证据",
        "证据不足时明确说",
        "最终只输出",
        "最终应该是",
        "需要用中文",
        "需要引用任务材料或规则结果",
        "先调用 search_knowledge_base",
        "应调用 search_knowledge_base",
        "当前工具可用",
        "我们可以基于知识库",
        "先调用",
        "最终答案是",
        "最终只输出两句话",
        "let me think",
        "we need to answer the user",
        "analysis:",
        "reasoning:",
        "chain of thought",
    )
    if not answer or any(marker in answer.casefold() for marker in internal_markers):
        return None
    return answer


async def run_agent_events(
    message: str,
    context: dict[str, Any],
    instructions: str = ASSISTANT_INSTRUCTIONS,
) -> AsyncIterator[dict[str, Any]]:
    """Invoke the internal OpenCode SDK runtime behind the stable SSE contract."""
    if not sdk_configured():
        yield {"event": "warning", "message": "OpenCode runtime 或汇丰模型 API 配置未完成"}
        yield {"event": "assistant_result", "answer": None, "citations": []}
        return
    retrieval_warnings: list[str] = []
    retrieved = await asyncio.to_thread(_rag_search, context, message, retrieval_warnings)
    yield {
        "event": "step",
        "step": {
            "key": "retrieve",
            "label": "检索证据",
            "detail": f"已整理 {len(retrieved)} 条授权材料、规则和知识库证据",
            "status": "completed",
        },
    }
    for index, warning in enumerate(retrieval_warnings):
        yield {
            "event": "step",
            "step": {
                "key": f"retrieval-warning-{index}",
                "label": "知识库检索提示",
                "detail": warning,
                "status": "error",
            },
        }
    try:
        timeout = httpx.Timeout(settings.AI_REQUEST_TIMEOUT, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{settings.ASSISTANT_RUNTIME_URL.rstrip('/')}/runs",
                headers={"Authorization": f"Bearer {settings.ASSISTANT_RUNTIME_TOKEN}"},
                json={
                    "message": message,
                    "instructions": instructions,
                    "conversation": [
                        {"role": item["role"], "content": item["content"][:4_000]}
                        for item in context.get("conversation", [])[-12:]
                    ],
                    "evidence": [
                        {
                            "type": str(item.get("type") or "evidence")[:40],
                            "id": str(item.get("id") or "")[:160],
                            "text": str(item.get("text") or "")[:4_000],
                            "source": str(item.get("source") or "")[:500],
                            "page": item.get("page"),
                        }
                        for item in retrieved[:20]
                    ],
                },
            ) as response:
                response.raise_for_status()
                answer: str | None = None
                result_seen = False
                citations: list[dict[str, Any]] = retrieved
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("event") == "assistant_result":
                        result_seen = True
                        answer = _safe_final_answer(str(event.get("answer") or ""))
                        citations = retrieved
                        if answer:
                            for index in range(0, len(answer), 80):
                                yield {"event": "delta", "delta": answer[index:index + 80]}
                        yield {"event": "assistant_result", "answer": answer, "citations": citations}
                    elif event.get("event") == "tool":
                        status = event.get("tool", {}).get("status")
                        yield {
                            "event": "tool",
                            "tool": {
                                "name": "read_authorized_evidence",
                                "status": status if status in {"running", "completed", "error"} else "error",
                                "result_count": len(retrieved),
                            },
                        }
                    elif event.get("event") == "step" and isinstance(event.get("step"), dict):
                        yield {"event": "step", "step": event["step"]}
                    elif event.get("event") == "warning":
                        yield {"event": "warning", "message": "OpenCode 助手运行未完成，请稍后重试。"}
                if not result_seen:
                    yield {"event": "assistant_result", "answer": None, "citations": citations}
    except Exception:
        logger.exception("OpenCode assistant runtime request failed")
        yield {"event": "warning", "message": "OpenCode 助手运行未完成，请稍后重试。"}
        yield {"event": "assistant_result", "answer": None, "citations": retrieved}


async def stream_assistant(
    db,
    user: models.User,
    session: models.AssistantSession,
    message: str,
    task_code: str | None,
    skill_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    task = task_for_user(db, user, task_code or session.task_code)
    context = task_context(task)
    citations = context.get("citations", [])[:8]
    conversation = [
        {"role": item.role, "content": item.content}
        for item in session.messages[-12:]
    ]
    context["conversation"] = conversation
    skill = get_skill(skill_id)
    instructions = ASSISTANT_INSTRUCTIONS
    if skill:
        instructions += (
            f"\n\n用户选择了项目内置业务技能“{skill['name']}”。"
            "严格遵守其范围，不得扩大工具权限或数据访问范围。\n"
            f"<project_skill_instructions>\n{skill['instructions']}\n</project_skill_instructions>"
        )

    db.add(models.AssistantMessage(session_id=session.id, role="user", content=message))
    if task_code:
        session.task_code = task_code
    if session.title == "新会话":
        session.title = message[:32]
    session.updated_at = datetime.now(timezone.utc)
    db.commit()

    yield {
        "event": "message_start",
        "message_id": f"assistant:{session.id}",
        "task_code": task.task_code if task else None,
    }
    answer: str | None = None
    rag_citations: list[dict[str, Any]] = []
    runtime_steps: list[dict[str, Any]] = []
    tool_steps: dict[str, dict[str, Any]] = {}
    if skill:
        skill_step = {
            "key": f"skill:{skill['id']}",
            "label": f"应用技能：{skill['name']}",
            "detail": "载入已审核的业务指引",
            "status": "completed",
        }
        runtime_steps.append(skill_step)
        yield {"event": "step", "step": skill_step}
    yield {
        "event": "step",
        "step": {"key": "retrieve", "label": "检索证据", "detail": "查询任务材料、规则结果和知识库", "status": "running"},
    }

    async for event in run_agent_events(message, context, instructions):
        if event.get("event") == "assistant_result":
            answer = event.get("answer")
            rag_citations = event.get("citations", [])
        elif event.get("event") == "step" and event.get("step"):
            runtime_steps.append(event["step"])
            yield event
        elif event.get("event") == "tool" and event.get("tool"):
            tool = event["tool"]
            tool_status = tool.get("status")
            tool_steps[tool["name"]] = {
                "key": f"tool:{tool['name']}",
                "label": "读取授权证据",
                "detail": (
                    f"已检索 {tool.get('result_count', 0)} 条证据"
                    if tool_status == "completed"
                    else "正在向模型提供本轮已授权证据" if tool_status == "running"
                    else "OpenCode 未能读取本轮授权证据"
                ),
                "status": tool_status if tool_status in {"running", "completed", "error"} else "error",
            }
            yield event
        elif event.get("event") == "warning":
            warning_step = {
                "key": "model-warning",
                "label": "模型服务提示",
                "detail": event.get("message", "模型服务暂不可用"),
                "status": "error",
            }
            runtime_steps.append(warning_step)
            yield {"event": "step", "step": warning_step}
        else:
            yield event
    if not answer:
        yield {
            "event": "error",
            "message": "助手未能生成答复。请确认 OpenCode runtime 和汇丰模型 API 可用后重试。",
        }
        return
    disclaimer = "\n\n以上为审核辅助意见，不是贷款最终审批决定，请由有权限的审核人员复核。"
    if disclaimer not in answer:
        answer += disclaimer
        yield {"event": "delta", "delta": disclaimer}
    if rag_citations:
        citations.extend({
            "id": item["id"],
            "label": item["source"],
            "source": item["source"],
            "detail": item["text"][:180],
            "page": item.get("page"),
        } for item in rag_citations)
    if citations:
        yield {"event": "citations", "citations": citations}
    persisted = models.AssistantMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        status="completed",
        steps=[
            *runtime_steps,
            *tool_steps.values(),
        ],
        citations=citations,
    )
    db.add(persisted)
    db.commit()
    yield {
        "event": "message_end",
        "message": {
            "id": persisted.id,
            "role": persisted.role,
            "content": persisted.content,
            "status": persisted.status,
            "steps": persisted.steps,
            "citations": persisted.citations,
        },
    }
