---
name: business-day-check
description: 从授权任务材料中定位提款和付款日期，并说明需要核验的司法辖区及工作日日历。
license: Proprietary - HSBC internal
metadata:
  displayName: 节假日核验
  shortDescription: 定位业务日期与工作日日历风险
  version: 1.0.0
  owner: AI 助手团队
  permissions: read_authorized_evidence
---

# 业务日与节假日核验

从当前授权任务的材料中提取提款日、付款日和适用地点，结合知识库规则列出需要核验的市场和日历依据。

知识库没有提供对应日期、司法辖区和日历来源时，不得声称已完成节假日查询，须标注“需人工确认”。不要推测节假日状态或改变业务到期日。
