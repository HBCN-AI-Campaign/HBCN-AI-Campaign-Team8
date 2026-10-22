---
name: fx-review
description: 汇总授权任务的币种和金额，识别是否需要外部汇率依据以及材料中的换算差异。
license: Proprietary - HSBC internal
metadata:
  displayName: 汇率换算
  shortDescription: 检查币种、金额及换算依据
  version: 1.0.0
  owner: AI 助手团队
  permissions: read_authorized_evidence
---

# 汇率与币种核对

读取当前授权任务中的币种和金额字段，并与规则结果、合同、提款指示及付款材料对照。明确区分材料原值、可验证的规则依据和需要外部汇率服务确认的内容。

不得编造汇率、汇率日期或报价来源。当前上下文没有汇率证据时，直接标注“需人工确认汇率来源及适用日期”。不得把币种一致性检查表述成已完成真实汇率换算。
