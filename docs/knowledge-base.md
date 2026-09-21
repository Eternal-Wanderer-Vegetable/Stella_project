# 独立知识库（Knowledge Base）

> 状态：v1（2026-09-21 落地，对应 `docs/plans/2026-09-21-gitnexus-plan-independent-knowledge-base.md`）。
> WebUI/ChatUI 管理面、递归爬取、OCR、外部向量库、自动记忆晋升、MCP knowledge provider 为明确的 deferred 项。

## 1. 这是什么

与个人记忆（`memory/`）**平行**的资料库子系统：管理员统一维护的资料库（managed）与成员共建的共享资料库（shared）。支持 Markdown / TXT / 文本型 PDF / DOCX / 显式选择的 URL 导入，ACL 隔离、草稿/审核/发布生命周期、版本化索引、混合检索（BM25 + 语义）与有边界的引用式证据注入。

一句话定位：**记忆是「对人、对群长期相处的认知」，知识库是「沉淀下来的正式资料」**。两者绝不通婚。

## 2. 三条红线（设计约束）

1. **存储隔离**：知识库使用独立的 `KNOWLEDGE_DB_PATH`（默认 `<STELLA_HOME>/knowledge/knowledge.db`），与 `agent_memory.db` 没有任何表、索引或迁移历史上的交集。记忆的清理、候选晋升、空间合并、保留策略物理上碰不到外部文档，反之知识库重建/归档也不影响记忆。
2. **上下文三轨分离**：`tool_summaries`（工具摘要）、`knowledge_evidence`（知识证据）、`memories_for_prompt`（记忆）各自独立渲染、独立预算。证据带编号引用，证据预算是 `KNOWLEDGE_EVIDENCE_MAX_ITEMS` / `KNOWLEDGE_EVIDENCE_MAX_TOKENS`（渲染前硬边界；`fit_prompt_to_window` 只是超窗兜底）。
3. **晋升隔离**：整合器（consolidator）的输入只有 `group_messages` 原始聊天记录，证据从未被写入该表；`knowledge/isolation.py` 在每轮注入后运行运行时护栏，一旦发现证据文本出现在任何记忆字段里，立刻 error 告警并就地清除证据副本——宁可丢证据，不污染记忆。

## 3. 领域模型

```
KnowledgeBase (mode: managed|shared, owner, direct_publish, embedding 指纹)
  ├── KBGrant        主体(kind: user|group|space × id) → 角色(viewer|contributor|maintainer)
  └── KBDocument     文档身份（title / source / content_hash / 生命周期状态 / active_version 指针）
        └── KBDocumentVersion  不可变版本（索引状态机 pending→ready→active→superseded|failed）
              └── kb_chunk   块（定位符 + 向量 BLOB） + kb_chunk_fts（FTS5 行）
```

- **生命周期**（`knowledge/lifecycle.py`）：`draft → in_review → published → archived`；`publish` 必须携带一个 `index_complete` 的版本；`published → published` 是替换发布的幂等边。
- **原子激活**（`knowledge/store.activate_version`）：单事务完成「旧 active→superseded、ready→active、doc 指针前移、doc 状态→published」。半套索引不可能对外可见。
- **embedding 指纹**：库在首次收到向量时锁定 `model / dim / encoder / index_version` 四元组。配置变化后该库 dense 通道停用并标 `needs_rebuild`（BM25 照常可用），索引重建前不会在半新半旧的向量空间里排序。

## 4. 权限模型

角色三档 + 库主（owner 不进授权表，它就是 `kb.owner_user_id`）。主体三态并存且取最大命中：`user:<QQ号>`、`group:<QQ群号>`、`space:<群组共享空间>`——「授权给某个群」与「授权给整个空间」是两个不同的决定。

| 操作 | managed | shared |
|---|---|---|
| 检索（published） | viewer 以上 | viewer 以上 |
| 投稿 | maintainer 以上 | contributor 以上 |
| 审核 / 发布 | maintainer 以上 | maintainer 以上 |
| 管理 ACL | maintainer 以上 | maintainer 以上 |
| 归档库 / 开关直发 | 仅库主 | 仅库主 |

- 上传与发布是**两个**权限：shared 库的贡献者能投稿不等于能发布。
- 发布流程：managed 维护者上传即发布；shared 默认「投稿进 in_review，维护者发布」；库主可开 `direct_publish` 让投稿免审（策略行为，不走投稿人的发布权限）。
- **私库在群聊不可见**：群聊场景（`in_group=True`）下，没有任何 group/space 授权的库不进候选——群聊回复对全员可见，等于把私库内容公开广播。
- 检索过滤跑两遍（plan §9 第一风险）：service 层先按 ACL 圈定授权库集合（空集合直接短路，不碰任何数据），retrieval 层的 SQL 再按 `published + active_version` 过滤一遍；显式指定了无权限的库记入 `denied_kb_ids`，不报错也不返回任何元数据。

## 5. 导入

`knowledge/service.submit()` → worker 线程跑 `knowledge/ingest.py`（**绝不在回复路径上同步执行**）：

1. 解析（`parsers.py`）：Markdown 按 ATX 标题建节路径；TXT 按段；文本型 PDF 按页（扫描版是明确失败——OCR deferred）；DOCX 按 heading 分节、表格摊平（依赖可选的 `pypdf` / `python-docx`，缺失时给出安装提示的失败态）；URL 单页抓取（超时 + 字节上限 + Content-Type 白名单，不递归）。所有失败抛 `ParseError`，错误信息面向操作者并落库。
2. 切块（`chunking.py`）：段落原子、贪心装箱到 ~500 字符目标（硬上限 900）；定位符继承自所在节。
3. 幂等与版本：内容哈希（SHA-256，行尾规范化）同库唯一 → 重复导入忽略；同标题再导入 → 新版本（替换）。
4. 索引：chunk 行 + FTS 行（分词词串，`knowledge/fts.py` 两侧共用同一套切法）+ 向量 BLOB（可选 embedding）。全部写完且计数一致才置 `ready`。
5. 发布：免审投稿自动走原子激活；需审投稿停在 `in_review` 等维护者。
6. 每次导入记 `kb_import_job`（状态/失败原因），供状态面观测。

## 6. 检索与证据注入

- 双通道：BM25（FTS5 `bm25()`，中文 2/3 字滑窗分词）+ 语义（余弦，授权库 active 向量载入）；RRF 融合（`KNOWLEDGE_RRF_K`）；近重复折叠；可选注入式 rerank（`KNOWLEDGE_RERANK_ENABLED`，默认关）。
- 降级链：FTS5 不可用/无命中 → 纯 dense；embedding 不可用/指纹不匹配 → 纯 BM25 + `needs_rebuild` 标记；检索永不抛异常。
- 注入（`core/pipeline._knowledge_evidence_section`）：证据先过 `fit_evidence_to_budget`（条数 + token），渲染成带编号引用的段落（`[1]《标题》 节路径 > ¶段（资料库:名）`），放在工具摘要之后、当前输入之前——证据是本轮最权威的素材，离输入最近。没有证据时 prompt 与原来逐字一致。

## 7. capability 接入

`KNOWLEDGE_ENABLED=true` 时（默认 true），启动期 `capability/adapters/knowledge.py` 把 `KnowledgeBackend`（`kind=native`，registry 预留的实现方式槽位）装进 Provider Runtime，并把 `knowledge.search` 能力注册进注册表（examples 是用户语料，**刻意不给 L0 keywords**——字面命中会强制执行检索，工具假阳是高代价错误）。

关键安全设计：工具的 `query` / `kb_ids` 由模型给，但 **ACL 主体永远从聊天事件推导**（`get_sender_id` / `get_group_id` / `resolve_space`），模型无从伪造身份——prompt injection 让模型带 `user_id=别人` 也带不进来。

hooks 把 knowledge.search 的结果分流进 `ctx.knowledge_evidence`（结构化摘录 + 引用），**不进** `tool_summaries`，也不进直回文本。

## 8. 配置（config/settings.py）

| 键 | 默认 | 说明 |
|---|---|---|
| `KNOWLEDGE_ENABLED` | true | 子系统总开关（false 时能力不注册、路由不可达） |
| `KNOWLEDGE_DB_PATH` | `<home>/knowledge/knowledge.db` | 独立存储路径 |
| `KNOWLEDGE_SEARCH_TOP_K` | 8 | 每路候选上限 |
| `KNOWLEDGE_RRF_K` | 60 | RRF 融合常数 |
| `KNOWLEDGE_EVIDENCE_MAX_ITEMS` | 4 | 证据条数硬上限 |
| `KNOWLEDGE_EVIDENCE_MAX_TOKENS` | 600 | 证据 token 硬上限 |
| `KNOWLEDGE_EVIDENCE_MAX_CHARS` | 700 | 单条摘录字符上限 |
| `KNOWLEDGE_RERANK_ENABLED` | false | 可选 rerank（需注入 reranker） |
| `KNOWLEDGE_EMBEDDING_BASE_URL` / `_MODEL` | 空 | 留空继承 `MEMORY_EMBEDDING_*`（同一本地实例与闸门） |
| `KNOWLEDGE_URL_TIMEOUT` / `_MAX_BYTES` | 15s / 2MiB | URL 抓取边界 |
| `KNOWLEDGE_IMPORT_MAX_BYTES` | 20MiB | 单文件导入上限 |

## 9. 运维

```bash
python -m knowledge.schema --dry-run   # 预览（SCHEMA_VERSION=1，独立于记忆库迁移）
python -m knowledge.schema             # 建库/迁移
```

状态面（当前是 Python API，WebUI deferred）：`knowledge.service.get_service().kb_status(kb_id, principal)` 返回指纹锁定/匹配状态、每文档版本、最近导入作业（含失败原因）与授权摘要；`list_accessible_kbs(principal, in_group=)` 列出主体可见的库。导入失败会留在 `kb_import_job`，重启不丢。

## 10. 测试

`tests/knowledge/` 六个文件覆盖 plan §8 的矩阵：领域/ACL/生命周期、存储（原子激活/FTS 同步）、解析与导入（幂等/替换/失败态）、检索（BM25 精确词、语义无词面重叠、RRF、指纹重建、证据上限、去重）、服务层 ACL 矩阵（投稿/审核/直发/群聊可见性/状态面）、能力接线（backend、工具 ACL、hooks 分流）与隔离护栏。既有记忆/能力/管线测试保持全绿（`test_access_semantics.py`、`tests/capability/`、`test_pipeline_compose.py`、`test_context_budget.py`）。
