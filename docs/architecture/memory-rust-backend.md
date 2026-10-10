# Rust 记忆后端

中文 | [English](memory-rust-backend.en.md) · [文档总览](../README.md)

Stella 默认使用 `memory/` 中的 Python 引擎，也以它作为回退。
可选的 `stella-memory-rust` wheel 经 `memory_rust` 命名空间提供原生检索与晋升。
当前分支要求两侧均为 **backend API 3 / memory schema 19**（[源码合同](../development/contracts.md)）；已发布 6.1.0 的 API 2/schema 18 是历史快照。
wheel 包版本与 Stella 应用版本独立。

## 运行模式

启动前设置 `MEMORY_BACKEND`：

| 模式 | 行为 |
| --- | --- |
| `python` | 默认 Python 实现 |
| `rust` | 使用兼容的原生检索/晋升，加载或运行错误直接报告 |
| `auto` | 原生可用且合同匹配时选 Rust，否则回退 Python |
| `shadow` | 返回 Python 结果，旁路比较只读 Rust 检索；不执行原生写入或提交后副作用 |
| `strict` | 必须使用 Rust，加载/合同错误不回退 |

未显式设置 `MEMORY_BACKEND` 时，旧开关 `MEMORY_RUST_SHADOW=true` 选择 shadow，
`MEMORY_RUST_STRICT=true` 选择 strict；两者同时开启时 strict 优先。
显式 `MEMORY_BACKEND` 始终优先。切回 Python：设置 `MEMORY_BACKEND=python` 并重启。

Rust 不负责 embedding HTTP、LLM 整合、schema 迁移、Python 异步锁、调度、
缓存失效与压缩器副作用；这些仍由 Python 集成层管理。

## 兼容矩阵

| 原生负载来源 | Backend API | Memory schema | Python |
| --- | ---: | ---: | --- |
| 当前分支原生源码（需重新核验 wheel） | 3 | 19 | 3.10+（`abi3`） |
| Stella `v6.1.0` 原生源码（`stella-memory-rust 0.1.0`） | 2 | 18 | 3.10+（`abi3`） |

加载器先验证导出的 API/schema 常量，再选择 Rust。旧 wheel 也可能标为 `0.1.0`，
**仅看包版本不能证明兼容**；使用对应 Stella Release 随包的 wheel，并核对导出常量。
两侧必须遵守同一 owner/audience 合同，包括个人记忆作用域与来源绑定晋升。

## 发布资产

```text
Stella-OneClick-Rust-v6.1.0-windows-amd64.exe
Stella-OneClick-Rust-Offline-v6.1.0-windows-amd64.exe
Stella-Standalone-Rust-v6.1.0-windows-amd64.zip
```

Standalone-Rust 在 `wheels/` 内附带一个 wheel。`start.bat` 或 `Stella.exe`
完成首次运行准备后，从本地安装该 wheel 到应用目录，并选择 `MEMORY_BACKEND=rust`。
OneClick 在安装阶段完成同样的准备，Offline 额外携带运行时与依赖。
Python 产品使用 Python 引擎。原生扩展安装在随包 `memory_rust` 旁，供嵌入式
Python 导入。`VERSION.txt` 与 `SHA256SUMS.txt` 描述负载，资产名使用主 Release tag。

## 验收边界

[P8 报告](../reports/2026-10-05-dialogue-attribution-p8-acceptance.md)记录了
API 2/schema 18 加载、原生测试与检索 benchmark 21/24 硬匹配；
3 个 conversation 排序差异仍未闭环。这是有日期的历史证据，并非每份下载的
6.1.0 资产都重新跑过 benchmark。要求排序一致的部署保持 Python，切换前先观察 shadow。
