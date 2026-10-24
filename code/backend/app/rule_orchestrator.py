"""规则核对编排器。

统一入口 `run_rules(task, documents)`，决定由谁来做规则核对：

  1. 对方 rule_check 服务已配置且 /health ready → 调用对方 API，取回结果；
     调用过程若异常，自动回退本地引擎（不阻断流程）。
  2. 否则（未配置 / 不健康）→ 使用本地内置 rule_engine.run_all。

返回统一的 RuleResult 列表，上层（routers.tasks._run_and_persist）据此落 CheckResult 库，
无需关心结果来自哪一侧。
"""
from __future__ import annotations

import logging

from . import rule_check_client
from .rule_engine import run_all
from .rule_engine.base import RuleResult

log = logging.getLogger(__name__)


def run_rules(task, documents: list) -> tuple[list[RuleResult], str]:
    """执行规则核对。

    返回 (results, source)：
      - results：RuleResult 列表
      - source ：'remote'（对方服务）/ 'local'（本地引擎），便于日志与前端标注来源。
    """
    if rule_check_client.configured() and rule_check_client.health():
        try:
            results = rule_check_client.check(task, documents)
            log.info("规则核对：使用对方 rule_check 服务，返回 %d 条", len(results))
            return results, "remote"
        except Exception as exc:
            # 对方服务探测 ready 但调用失败 → 回退本地，保证流程不阻断
            log.warning("对方 rule_check 调用失败，回退本地引擎: %s", exc)

    results = run_all(documents)
    log.info("规则核对：使用本地 rule_engine，返回 %d 条", len(results))
    return results, "local"
