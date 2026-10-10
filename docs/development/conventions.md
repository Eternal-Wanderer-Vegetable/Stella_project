# 代码约定

中文 | [English](conventions.en.md) · [文档总览](../README.md)

## 代码约定

**Lint / 格式**：ruff（配置在 `pyproject.toml`）。未使用 black —— 不要引入 black 格式化，会造成大面积无意义 diff。

**类型检查**：pyright（`pyrightconfig.json`）。CI 不跑类型检查，但新代码应带类型标注。

**注释写「为什么」而不是「做什么」**。项目里大量注释记录了某个阈值的实测依据、某个顺序的必要性、某个 bug 的成因——这类信息删掉之后无法从代码反推。例如：

```python
# confidence / importance 权重刻意压到 0.05：它们描述「记忆本身可靠/重要」，
# 与「当前该不该用这条」关系弱，只适合做 tie-breaker。否则 conf≈0.98 的
# 高质量诱饵会在「该不该用」上作弊。
```

**逻辑不要有第二份副本**。`memory/text_similarity.py` 的存在就是因为相似度判定曾在三个模块各有一份，跨用户合并 bug 需要修三次而漏了两次。

**静默降级必须留痕**。项目里大量 `except sqlite3.OperationalError` 是为了容忍「表还不存在」（惰性建表），这个设计是对的。但它同时会吞掉「列名不匹配」这类致命错误——2026-08-17 的两次故障（记忆表列名遗漏、@ 消息不入库）都因此持续数小时无人察觉。

约定：捕获 SQLite 异常时按消息内容分级。

```python
if "no such table" in str(e):
    logger.debug(...)   # 惰性建表的正常情况
else:
    logger.warning(...)  # 尤其 no such column，必须可见
```

同理，任何「失败时返回空结果继续跑」的路径都要留下 warning。功能静默失效比崩溃难查得多。

**Prompt 改动需要护栏**。`tests/test_consolidation_prompt.py`、`tests/test_proactive_prompt.py` 对关键条款做字符串断言，包括反向断言（确认已移除的条款没被写回来）。这类条款删掉后功能仍「正常工作」但效果立刻变差，只能靠断言锁住。
## 提交与贡献

**提交信息**用简短的英文或中文描述改动实质，避免「fix bug」「update」这类无信息量的描述。

**PR 前确认**：

- `python -m pytest tests -q` 全绿
- `ruff check .` 无警告
- 改了 prompt → 跑过双向闸门（正例回归 + 真实窗口）
- 改了 schema → `python -m memory.schema --dry-run` 输出符合预期
- 改了配置项 → `.env.example` 同步（`deploy init` 基于它渲染，漏改会让新配置项不出现在生成的 `.env` 里），`docs/configuration.md` 同步
- 改了监听器 priority / 新增 block=True 的处理器 → 确认落库监听器仍是最高优先级，且发一条 @ 消息验证 `AT_MENTION` 入库
- 改了记忆表的 SQL → 确认用的是 `group_shared_space` 而非 `group_id`（两层归属见 architecture.md）
- 改了 Router 规则 / 能力声明 → `python -m capability.router.benchmark --rules-only` 的记忆假阴与工具假阳仍为 0
- 打算打开 `ROUTER_GATE_MEMORY` → 跑全链路 benchmark（需 embedding 服务）并确认退出码为 0；这是唯一能验证「不会悄悄丢记忆」的手段
- 新增能力 Provider 类型（MCP / API / native）→ 在 `capability/comes/executor.py::resolve_tools` 里实现对应分支，别让它静默落进 `missing`

**改动涉及以下内容时请在 PR 描述里说明理由**：

- 记忆晋升的阈值或判定逻辑
- prompt 中的防编造条款
- 三条合并路径的归属过滤
- 链路监测的判活 / 告警逻辑（心跳 + 主动探活，只告警不重启）
- 监听器的优先级与 block 关系
- 两层归属（QQ 群 / 共享空间）的划分

这些地方都有过实测依据（记录在 `design_docs/check_point/` 与 `bug_report/`），改动前建议先读相关记录。
