---
name: bill-of-lading-check
description: 对授权任务中的海运提单与合同、商业发票等单据进行字段交叉核对，整理疑点和人工核验点。
license: Proprietary - HSBC internal
metadata:
  displayName: 提单验真
  shortDescription: 核对提单与交易单据的一致性
  version: 1.0.0
  owner: AI 助手团队
  permissions: read_authorized_evidence
---

# 提单验真

仅使用当前会话已授权的任务材料和 `read_authorized_evidence` 返回的证据。对提单号、装运港、目的港、承运人、货物描述、日期与关联商业单据进行逐项对照。

输出字段、材料来源和差异。证据不存在或不能相互印证时写明“需人工确认”，不得推断外部承运人系统已核验。不得声称已查询未授权的船运、制裁或外部 API。不得作出贷款审批决定。
