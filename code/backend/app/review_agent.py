"""专项审核 Agent（流程编排，对应时序图中的 ORC 流程编排(Agent)）。

职责边界（与 rule_engine 明确分工）：
  🧮 规则引擎（rule_engine）：能用已识别字段直接硬核对的，产出 pass/fail/warn，落库为 CheckResult。
  🤖 专项审核 Agent（本文件）：
     1) 驱动整体流程 —— 归集建树 → 逐条播放规则推理"思考流" → 命中不通过时挂起等待处置；
     2) 承接规则引擎移交的「[专项]」项 —— 这些是规则引擎做不到、需外部能力的检查
        （节假日判定、汇率折算、提单真伪验证、海关联网、制裁/反洗钱名单、法规检索、语义翻译研判），
        由本 Agent 以"专项审核步骤"继续处理，必要时产出需人工回复的待处置项。

真实环境下第 2 类会调用 LLM / 外部服务（时序图中的 EXT：法规/验真/名单）。当前为 mock：
  读取 rule_engine.run_all 产出的 Status.SKIP 且 why 以「[专项]」开头的结果，
  合成对应的专项审核思考流与待处置项。

状态不落库，纯内存会话；审核人通过 /ai/resolve 回复意见后流程继续。
"""
from __future__ import annotations

from typing import Any

from . import models
from .rule_engine import run_all
from .rule_engine.rules import HANDOFF

# 维度中文名（与前端 DIMENSION_NAME 对应）
DIMENSION_NAME = {
    "A": "授信层（提款↔FOL）",
    "B": "资金拆分（提款↔支付）",
    "C": "贸易背景（支付↔外部单据）",
    "D": "单据一致性",
    "E": "合规与制裁",
    "F": "形式与完整性",
}


def build_tree(task: "models.ReviewTask") -> list[dict[str, Any]]:
    """以单据构建关联归集树节点（层级用 level 表示）。"""
    nodes: list[dict[str, Any]] = []
    level_map = {
        "FACILITY_LETTER": 0,
        "DRAWDOWN_INSTRUCTION": 1,
        "PAYMENT_INSTRUCTION": 2,
    }
    for d in task.documents:
        tcode = d.type_code.value if hasattr(d.type_code, "value") else str(d.type_code)
        nodes.append(
            {
                "doc_code": d.doc_code,
                "type_code": tcode,
                "level": level_map.get(tcode, 3),
                "summary": _doc_summary(d),
            }
        )
    return nodes


def _doc_summary(d: "models.Document") -> str:
    f = d.fields or {}
    picks = []
    for k in ("amount", "currency", "payee", "borrower", "facility_amount", "drawdown_amount"):
        if k in f and f[k]:
            picks.append(f"{k}={f[k]}")
    return " · ".join(picks[:3]) if picks else "待解析"


def _check_rows(task: "models.ReviewTask") -> list[dict[str, Any]]:
    """已落库的规则引擎结果（pass/fail/warn）。"""
    rows = []
    for r in task.results:
        st = r.status.value if hasattr(r.status, "value") else str(r.status)
        rows.append(
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "dimension": r.dimension,
                "status": st,
                "why": r.why,
                "suggestion": r.suggestion or "",
            }
        )
    return rows


def _handoff_items(task: "models.ReviewTask") -> list[dict[str, Any]]:
    """规则引擎移交给专项审核的项：Status.SKIP 且 why 以 [专项] 开头。"""
    items = []
    for r in run_all(task.documents):
        if r.status.value == "skip" and (r.why or "").startswith(HANDOFF):
            items.append(
                {
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "dimension": r.dimension,
                    "why": (r.why or "").removeprefix(HANDOFF).strip(),
                    "suggestion": r.suggestion or "",
                }
            )
    return items


def build_session(task: "models.ReviewTask") -> dict[str, Any]:
    """生成一次完整的专项审核会话数据（供前端播放）。"""
    checks = _check_rows(task)
    handoffs = _handoff_items(task)
    tree = build_tree(task)
    n_doc = len(tree)

    thoughts: list[dict[str, Any]] = []
    pendings: list[dict[str, Any]] = []

    # 1) 前置：解析 / 归集
    thoughts.append({
        "kind": "phase", "tag": "启动",
        "text": f"开始专项审核：共归集 {n_doc} 份单据，构建以贷款合同为根的关联归集树。",
    })
    for i, node in enumerate(tree):
        thoughts.append({
            "kind": "parse", "tag": "解析",
            "text": f"解析单据 {node['doc_code']}（{node['type_code']}）… 提取关键字段完成。",
            "parse_index": i + 1, "parse_total": n_doc,
        })
    thoughts.append({
        "kind": "phase", "tag": "归集",
        "text": f"{n_doc} 份单据解析与归集完成。先执行规则引擎可确定性判定的项，再对需外部能力的项做专项审核。",
    })

    # 2) 规则引擎结果回放：pass 记录；warn 挂入需处理项不阻断；fail 挂起等待处置
    for c in checks:
        dim = c["dimension"]
        dim_name = DIMENSION_NAME.get(dim, dim)
        if c["status"] == "pass":
            thoughts.append({
                "kind": "pass", "tag": "通过",
                "text": f"[规则·{dim}·{dim_name}] {c['rule_name']}：{c['why']} 判定通过。",
            })
        elif c["status"] == "warn":
            pendings.append(_pending(c["rule_id"], c["rule_name"], c["dimension"], "warn", c["why"], c["suggestion"]))
            thoughts.append({
                "kind": "warn", "tag": "记录",
                "text": f"[规则·{dim}·{dim_name}] {c['rule_name']}：{c['why']} 已挂入「需处理项」，不阻断流程，由审核人知悉留痕。",
                "pending_id": c["rule_id"],
            })
        elif c["status"] == "fail":
            pendings.append(_pending(c["rule_id"], c["rule_name"], c["dimension"], "fail", c["why"], c["suggestion"]))
            thoughts.append({
                "kind": "fail", "tag": "挂起",
                "text": f"[规则·{dim}·{dim_name}] {c['rule_name']}：{c['why']} 命中「不通过」，任务暂停，等待审核人处置后继续。",
                "pending_id": c["rule_id"],
                "pause": True,
            })

    # 3) 专项审核：规则引擎做不到、需外部能力的项，由 Agent 逐条研判
    if handoffs:
        thoughts.append({
            "kind": "phase", "tag": "专项",
            "text": f"规则引擎已完成可确定性判定，移交 {len(handoffs)} 个专项审核点（需节假日/汇率/验真/名单/法规/翻译等外部能力）。",
        })
    for h in handoffs:
        dim = h["dimension"]
        dim_name = DIMENSION_NAME.get(dim, dim)
        pendings.append(_pending(h["rule_id"], h["rule_name"], h["dimension"], "special", h["why"], h["suggestion"]))
        thoughts.append({
            "kind": "special", "tag": "专项",
            "text": f"[专项·{dim}·{dim_name}] {h['rule_name']}：{h['why']} "
                    f"该项规则引擎无法下定论，已调用专项能力并提请审核人结合外部核验结果确认。",
            "pending_id": h["rule_id"],
            "pause": True,
        })

    # 4) 结论
    thoughts.append({
        "kind": "phase", "tag": "结论",
        "text": "规则判定与专项审核已全部产出，可在「规则审核结果」查看明细，并在「最终结果」做出审核决定。",
    })

    return {
        "tree": tree,
        "thoughts": thoughts,
        "pendings": pendings,
        "counts": _counts(checks),
    }


def _pending(rid: str, name: str, dim: str, status: str, why: str, suggestion: str) -> dict[str, Any]:
    return {
        "id": rid,
        "rule_name": name,
        "dimension": dim,
        "status": status,  # fail / warn / special
        "why": why,
        "suggestion": suggestion,
    }


def _counts(checks: list[dict[str, Any]]) -> dict[str, int]:
    c = {"pass": 0, "fail": 0, "warn": 0}
    for x in checks:
        if x["status"] in c:
            c[x["status"]] += 1
    return c
