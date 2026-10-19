"""AI 助手底座：Agent SDK 适配、受控工具和 SSE 事件编排。

业务边界：助手可以读取授权任务证据、调用 RAG 查询适配器并生成审核辅助建议，
但不写入任务审核状态、不改写规则结果，也不替审核人员做贷款最终结论。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from typing import Any

from . import models
from .config import settings

ASSISTANT_INSTRUCTIONS = (
    "你是境外贷款单据审核辅助助手。只能解释证据、检索知识、整理风险和起草人工复核意见。"
    "不得直接批准、拒绝或改变贷款审核结论；结论必须交给有权限的审核人员。"
    "回答要引用任务材料或规则结果，证据不足时明确说需要人工确认。"
)


def sdk_configured() -> bool:
    return bool(settings.AI_BASE_URL and settings.AI_API_KEY and settings.AI_MODEL)


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
    except Exception:
        # 网关或 RAG 服务异常时保留本地证据，不阻断助手。
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


def fallback_answer(message: str, context: dict[str, Any]) -> str:
    task = context.get("task")
    if not task:
        return (
            "我可以协助检索业务规则、解释审核结果、整理单据证据和起草人工复核意见。"
            "请从业务页面带入任务上下文，或先告诉我需要查询的内容。"
            "当前助手只提供审核辅助，不会直接决定贷款审核结论。"
        )

    failures = [row for row in context.get("results", []) if row["status"] == "fail"]
    warnings = [row for row in context.get("results", []) if row["status"] == "warn"]
    lead = (
        f"我已读取任务 {task['task_code']} 的 "
        f"{len(context.get('documents', []))} 份材料和 "
        f"{len(context.get('results', []))} 条规则结果。"
    )
    if failures:
        detail = "；".join(f"{row['rule_id']} {row['rule_name']}" for row in failures[:3])
        return (
            f"{lead}\n\n当前发现 {len(failures)} 项不通过：{detail}。"
            "建议先打开对应规则的原文定位，核对差异后由审核人员决定是否退回补件或保留异常。"
        )
    if warnings:
        return (
            f"{lead}\n\n当前有 {len(warnings)} 项提示，需要结合材料和外部核验结果人工确认。"
            "助手可以继续整理证据，但不会自动把提示改成通过。"
        )
    return (
        f"{lead}\n\n针对“{message[:80]}”，目前没有发现已落库的不通过项。"
        "仍请审核人员结合原文、法规和外部核验完成最终确认。"
    )


def _strip_tool_echo(text: str) -> str:
    """去掉模型在真正调用工具前以纯文本形式回显的工具参数 JSON。

    部分网关模型（如经 CCSwitch 路由的 gpt-6.1-sol）会在调用 function tool
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


async def run_agent_events(
    message: str,
    context: dict[str, Any],
    instructions: str = ASSISTANT_INSTRUCTIONS,
) -> AsyncIterator[dict[str, Any]]:
    """可复用的 Agent SDK 调用入口，输出 delta、tool、warning 和最终结果事件。

    专项审核等后端 workflow 可以传入自己已鉴权、已筛选的只读上下文和任务指令。
    工具权限仍由本服务控制；该运行时没有贷款状态写入工具。
    """
    if not sdk_configured():
        yield {"event": "assistant_result", "answer": None, "citations": []}
        return
    chunks: list[str] = []
    retrieved: list[dict[str, Any]] = []
    retrieval_warnings: list[str] = []
    try:
        from agents import Agent, Runner, function_tool
        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
        from openai import AsyncOpenAI

        @function_tool
        def search_knowledge_base(query: str) -> str:
            """检索当前授权任务的材料和规则证据。"""
            retrieved.extend(_rag_search(context, query, retrieval_warnings))
            return json.dumps(retrieved, ensure_ascii=False)

        client = AsyncOpenAI(
            base_url=settings.AI_BASE_URL,
            api_key=settings.AI_API_KEY,
            timeout=settings.AI_REQUEST_TIMEOUT,
        )
        model = OpenAIChatCompletionsModel(
            model=settings.AI_MODEL,
            openai_client=client,
        )
        agent = Agent(
            name="汇丰审核助手",
            model=model,
            instructions=instructions,
            tools=[search_knowledge_base],
        )
        task = context.get("task") or {}
        previous_messages = context.get("conversation", [])
        prompt = json.dumps(
            {
                "question": message,
                "conversation": previous_messages[-12:],
                # 任务全文不随每次请求发送；按模型工具查询结果最小化提供证据。
                "task": {"task_code": task.get("task_code"), "status": task.get("status")},
            },
            ensure_ascii=False,
        )
        run = Runner.run_streamed(agent, prompt)
        async for event in run.stream_events():
            if event.type == "raw_response_event":
                delta = getattr(event.data, "delta", None)
                if isinstance(delta, str):
                    chunks.append(delta)
                    yield {"event": "delta", "delta": delta}
            elif event.type == "run_item_stream_event" and event.name == "tool_called":
                yield {"event": "tool", "tool": {"name": "search_knowledge_base", "status": "running"}}
            elif event.type == "run_item_stream_event" and event.name == "tool_output":
                yield {"event": "tool", "tool": {"name": "search_knowledge_base", "status": "completed", "result_count": len(retrieved)}}
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
        answer = _strip_tool_echo(
            "".join(chunks).strip() or str(run.final_output or "").strip()
        )
        yield {"event": "assistant_result", "answer": answer or None, "citations": retrieved}
    except Exception:
        # 网关、模型或 SDK 版本异常时，保留本地演示能力。
        yield {"event": "warning", "message": "模型网关暂不可用，正在使用本地演示回复"}
        yield {"event": "assistant_result", "answer": _strip_tool_echo("".join(chunks).strip()) or None, "citations": retrieved}


async def stream_assistant(
    db,
    user: models.User,
    session: models.AssistantSession,
    message: str,
    task_code: str | None,
) -> AsyncIterator[dict[str, Any]]:
    task = task_for_user(db, user, task_code or session.task_code)
    context = task_context(task)
    citations = context.get("citations", [])[:8]
    conversation = [
        {"role": item.role, "content": item.content}
        for item in session.messages[-12:]
    ]
    context["conversation"] = conversation

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
    steps = [
        ("understand", "理解请求", "拆解问题并确认助手权限边界"),
        ("context", "加载业务上下文", "读取当前会话与任务材料" if task else "等待任务上下文"),
        ("retrieve", "检索证据", "查询规则结果、单据字段和知识库适配层"),
        ("compose", "组织建议", "生成带引用的审核辅助回复"),
    ]
    for key, label, detail in steps[:2]:
        yield {"event": "step", "step": {"key": key, "label": label, "detail": detail, "status": "running"}}
        yield {"event": "step", "step": {"key": key, "label": label, "detail": detail, "status": "completed"}}
    key, label, detail = steps[2]
    yield {"event": "step", "step": {"key": key, "label": label, "detail": detail, "status": "running"}}

    answer: str | None = None
    rag_citations: list[dict[str, Any]] = []
    runtime_steps: list[dict[str, Any]] = []
    tool_steps: dict[str, dict[str, Any]] = {}
    async for event in run_agent_events(message, context):
        if event.get("event") == "assistant_result":
            answer = event.get("answer")
            rag_citations = event.get("citations", [])
        elif event.get("event") == "step" and event.get("step"):
            runtime_steps.append(event["step"])
            yield event
        elif event.get("event") == "tool" and event.get("tool"):
            tool = event["tool"]
            tool_steps[tool["name"]] = {
                "key": f"tool:{tool['name']}",
                "label": "检索知识库",
                "detail": (
                    f"已检索 {tool.get('result_count', 0)} 条证据"
                    if tool.get("status") == "completed"
                    else "检索任务相关材料与业务知识"
                ),
                "status": "completed" if tool.get("status") == "completed" else "running",
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
    key, label, detail = steps[2]
    yield {"event": "step", "step": {"key": key, "label": label, "detail": detail, "status": "completed"}}
    key, label, detail = steps[3]
    yield {"event": "step", "step": {"key": key, "label": label, "detail": detail, "status": "running"}}
    if not answer:
        answer = fallback_answer(message, context)
        for chunk in (answer[index:index + 80] for index in range(0, len(answer), 80)):
            yield {"event": "delta", "delta": chunk}
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
    yield {"event": "step", "step": {"key": key, "label": label, "detail": detail, "status": "completed"}}

    persisted = models.AssistantMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        status="completed",
        steps=[
            *[{"key": key, "label": label, "status": "completed"} for key, label, _ in steps],
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
