---
name: sanctions-screening-review
description: 整理授权任务材料中的相关主体信息，并列出制裁名单筛查所需的人工核验项。
license: Proprietary - HSBC internal
metadata:
  displayName: 制裁名单筛查
  shortDescription: 整理主体信息与筛查待核验项
  version: 1.0.0
  owner: AI 助手团队
  permissions: read_authorized_evidence
---

# 制裁名单筛查辅助

仅提取当前授权任务材料中出现的借款人、付款人、收款人等主体名称及其来源。整理需要具备的别名、注册地和身份标识，供有权限人员通过获批的筛查系统核验。

没有可信的名单查询工具和来源证据时，绝不能输出“未命中”“已通过”或“已完成筛查”。名称相似只能作为待核查提示，必须由有权限人员在获批系统确认。
