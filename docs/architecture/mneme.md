# Mneme：记忆子系统正式命名

中文 | [English](mneme.en.md) · [架构导航](README.md)

Mneme 是 Stella 记忆子系统的正式 Python 包（2026-11-03 计划 §3.1，S1-03 起）。
设计正文与闸门规则见 [记忆系统](memory-system.md)——本页只登记命名与
代码边界，不维护第二份正文。

## 代码边界

- 正式实现位于 `mneme/`（检索、整合、晋升、schema、社交、表达学习等全部
  记忆模块）；`memory/*` 是指向 `mneme/*` 的显式别名层：每个模块导入时
  自替换 `sys.modules`，新旧路径得到同一 module 对象。monkeypatch
  `memory.schema.DB_PATH` 与 `mneme.schema.DB_PATH` 命中同一实现。
- CLI 双向可用：`python -m memory.schema` 转发到 `python -m mneme.schema`，
  退出码与输出一致。
- 主动参与子系统在 [Aoede](aoede.md)；Mneme 不导入 Aoede，二者通过
  `stella_contracts/aoede.py` 的端口交互。`mneme/verification.py` 与求证
  attempt/tombstone 的持久生命周期在阶段二（S2-01）落地。
- `memory_rust` 发行名、native ABI、`BACKEND_API_VERSION` 与 SQLite 文件名
  不随本改名变化；Rust wheel 是有版本的可选后端，仍通过 `memory_rust.selector`
  接入 Mneme：`mneme.retrieval_v2` 调用 selector，native 结果重建为 Mneme 的
  `RetrievalResult`；晋升由 `mneme.memory_manager` 管理，Python 保留门槛与提交后副作用。
  默认 backend 仍是 Python，需显式设置 `MEMORY_BACKEND` 才会选择其他模式。
  详见 [Rust 后端接线与兼容](memory-rust-backend.md)。

## 数据与资源（不变）

数据库路径仍是 `DB_PATH`（默认用户目录 `memory/agent_memory.db`）；
`memory/SYSTEM.md`、`memory/benchmark/` 数据集与用户自定义覆盖保持原位，
来源可追溯。包改名不迁移任何用户数据。
