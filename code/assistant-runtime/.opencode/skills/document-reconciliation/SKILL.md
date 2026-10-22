---
name: document-reconciliation
description: 比对授权任务多份交易单据中的主体、金额、币种、日期和货物字段并定位冲突。
license: Proprietary - HSBC internal
metadata:
  displayName: 单据比对
  shortDescription: 比对材料字段并列出不一致项
  version: 1.0.0
  owner: AI 助手团队
  permissions: read_authorized_evidence
---

# 单据字段比对

逐份读取当前授权任务中可用的结构化单据字段，按主体、金额、币种、日期、合同/发票/运输标识等维度对照。输出需包含每个值对应的单据来源，区分一致、冲突和材料缺失。

不要把 OCR 提取值当作原件已核实的事实。对字段缺失、定位不清、币种换算和名称差异标注“需人工确认”，不得替审核人员决定接受或拒绝材料。
