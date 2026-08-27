# 配置导入（预演，未落盘）

- 来源目录：`D:\Stella-2.2.0`
- 来源版本：2.2.0
- 目标目录：`D:\Stella-3.1.0`
- 目标版本：3.1.0

## 文件

| 项目 | 结果 | 说明 |
|---|---|---|
| `deploy.answers.toml` | 将导入 | 1 KB |
| `memory/agent_memory.db` | 将导入 | 20480 KB |
| `memory/.space_assignments.json` | 将导入 | 1 KB |
| `config/spaces/` | 已导入 | 复制 2 个文件 |
| `system_prompts/` | 已导入 | 保留你改过的 1 个；1 个未改动、用新版 |
| `data/plugins/` | 已导入 | 复制 37 个文件 |
| `runtime` | 将复用 | 省下一次约 100MB 的下载 |
| `数据库` | 预演通过 | v5 → v10，改动 428 行 |

### 配置文件（.env）

- 沿用旧值：23 项
- 新版新增、走默认值：6 项
- 已废弃、已移除：2 项
- 无法识别、保留在文件末尾：0 项

**已移除的废弃配置**：
- `NAPCAT_QQ_ACCOUNT`：启动流程已与 NapCat 完全分离，Bot 只连现成的 OneBot 端点
- `NAPCAT_AUTO_START`：同上：不再由 Stella 拉起 NapCat

敏感项已沿用（值不打印）：ONEBOT_ACCESS_TOKEN

### 数据库迁移

- 版本：v5 → v10（预演，未落盘）
- 改动行数：428
- 加列/建索引：14 项
- **v8**
  - user_profiles 主键 user_id → (group_shared_space, user_id)，迁移 3 条画像
  - 画像 10001 已归入 casual（该用户 182/213 ≈ 85% 的消息在此空间），其余空间将重新建立认知
  - memories.group_shared_space: 263402786 → casual（301 行）
  - memories_fts 已重建并重灌 297 行

校验通过：行数守恒、归属非空、空间名可解析、FTS 索引对齐。

## 需要你注意

- `config/capabilities/entertainment.toml` 你改过，已保留你的版本；新版默认值在 `config/capabilities/entertainment.toml.new`，可自行对照
