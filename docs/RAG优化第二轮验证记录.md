# RAG 优化第二轮：中文词法与向量混合检索

> 对应 R03/R04/R12 的部分实现。源码已验证；未切换现有共享服务配置、未回填正式语料，不代表全部检索质量验收完成。

## 实现与选型

新增固定版本 `jieba==0.42.1` 搜索模式分词（MIT），关闭 HMM，以 NFKC/casefold 规范化中文与拉丁词。PostgreSQL `simple` 全文检索保存词位，GIN 加速候选检索，`ts_rank_cd` 做词法排序；与已有向量结果通过上游 LangChain PostgreSQL RRF 合并，随后参与查询族归一化归并。词法原始分、向量余弦分、通道 RRF 与查询族 RRF 分开记录，不当作审批概率。

这是可测的质量基线，不是搜索方案最终胜出的证明。比较：当前 PostgreSQL 路径复用事务、范围过滤与删除语义；Elasticsearch/OpenSearch 的语言分析与 BM25 值得作为后续候选，但增加独立索引同步与运维、权限删除一致性工作。不能以当前资源为上限排除后者；在独立题集上比较召回/排序、时延、资源与维护成本后决定，尚无证据声称本方案最优。

词法查询采用分词后的 OR 召回，避免自然问句所有词必须同时出现；精度由后续融合、重排、覆盖判断约束。单次词法查询最多 256 个不同词，超过时显式报错。英文目前无词干还原，中英文跨语言能力仍依赖翻译规划与向量，其他语言的质量须实测。

## 索引与权限边界

新增 `<向量表>_lexical` 派生表，包含片段 UUID 外键、tsvector 和分词器版本；不复制业务原文。外键 `ON DELETE CASCADE` 确保片段删除同步传播。词法检索关联原向量片段，按相同 scope、embedding_model、searchable 条件过滤，不依赖独立缓存的权限副本。本轮仍不开放任务资料或代替主站任务 ACL。

已有部署保持显式 `RAG_SEARCH_MODE=vector`。运行 `python -m app.lexical_index --apply` 创建/回填派生索引，校验后设置 `RAG_SEARCH_MODE=hybrid` 并重启对应服务；回填支持按批提交、重跑和分词器版本修复，不重新调用 Embedding。混合模式索引不存在、GIN 缺失、可检索片段未回填或分词器不一致时拒绝就绪/检索，不静默降级。混合模式新文档在开放 searchable 的事务内写入词法索引，失败不开放片段。

回滚设回 vector 并重启对应服务，不删除唯一向量数据或原件。若 vector 模式期间新增资料，重新启用 hybrid 前必须再回填。正式迁移前需备份、测量锁等待与回填时长；当前回填按批获取源行锁，未证明适合任意规模的在线迁移。

## 实际验证

| 验证 | 结果 | 证明范围 |
| --- | --- | --- |
| `python -m unittest discover -s tests -q`（RAG 虚拟环境） | 68 项，66 通过、2 跳过 | 外部语料路径未设置；真实 PostgreSQL 测试默认要求显式启用 |
| `HBCN_TEST_POSTGRES=1` 后 `python -m unittest tests.test_hybrid_retrieval -v` | 3 项全部通过 | 实际数据库中随机隔离 schema、合成资料；结束清理该 schema |
| 实际 PostgreSQL 检索 | 中文金额问题、英文 amount/correction 召回正确合成片段 | 不是正式语料 Recall 或 nDCG 评测 |
| 隔离服务启动 | uvicorn 启动、health/docs/OpenAPI 与未鉴权 401 通过 | 未启动共享 PostgreSQL 服务实例，不等于真实 UI 联调 |
| 实际过滤与生命周期 | scope、searchable、模型版本过滤；跨 scope 查询；版本过期拒绝；GIN 缺失拒绝并修复；回填 5→0→1；删除级联通过 | 未测试业务用户/任务 ACL、并发性能或权限撤销缓存 |
| 融合机制回归 | 两通道贡献、保留原始分类型、不混用余弦阈值、词法排序方向通过 | 向量候选在该集成测试中为受控空结果，不冒充真实 Embedding 端到端 |

## 复审修复及剩余事项

发现上游 RRF 对主通道按距离升序、次通道按关键词分降序，直接传相同递增名次会倒置词法排序；已按通道编码名次并增加独立词法顺序断言。词法低分不受向量余弦阈值误过滤。回填命令可修复缺失的 GIN 索引。

仍需独立 reranker、多源/MCP 适配与归并、法规适用性、来源级证据覆盖、真实 UI、独立题集与部署验收。配置默认值保留旧路径用于受控迁移，不能据此说正式实例已经启用混合检索。该轮没有产生模型/Embedding 调用费用。

技术依据：[PostgreSQL 全文检索](https://www.postgresql.org/docs/current/textsearch-controls.html)、[jieba 官方说明](https://github.com/fxsjy/jieba)、仓库锁定的 `langchain-postgres==0.0.19` 源码。采用成熟上游能力，业务代码只负责分词、索引生命周期、权限过滤与分数追踪适配。
