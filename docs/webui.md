# WebUI（v2 控制面）

浏览器与桌面壳共用的管理面板。与 Bot 进程同一 HTTP 服务（`HOST:PORT`，
默认 8080），**不新增端口**。设计与契约见
[design_docs/Stella GUI v2 与 WebUI 建设方案 v1.0.md](../design_docs/Stella%20GUI%20v2%20与%20WebUI%20建设方案%20v1.0.md)。

## 快速开始

1. 启动 Bot（`python bot.py` 或桌面壳启动）；
2. 浏览器打开 `http://127.0.0.1:8080/`；
3. 首次访问走 **setup 向导**创建管理员（凭据存 `STELLA_HOME/webui/auth.json`）；
4. 登录后即可使用：欢迎总览、聊天、平台、提供商、扩展（插件/MCP/Skills）、
   配置、知识库、人格、定时任务、群组、数据（统计/会话/日志/追踪）、设置。

忘记密码 / 想重新初始化：

```bash
python scripts/webui_reset_auth.py --yes
```

## 前端开发

```bash
cd dashboard && pnpm install
pnpm dev            # Vite :5173，/api 反代到 127.0.0.1:8080（建议设 WEBUI_SERVE_DIST=false）
pnpm build          # vue-tsc 类型门禁 + vite 构建
```

不依赖 Bot 的界面调试：`python scripts/dev_webui.py --port 8091`
（独立 WebUI 服务器：鉴权/配置/日志可用，聊天等 Bot 域功能不可用）。

部署：把 `dashboard/dist` 拷到 `webui/dist`（发布包已内置），或开发期
保持 `WEBUI_SERVE_DIST=false` 用 Vite 反代。

## 安全要点（方案 §9）

- 所有 `/api/v1/*` 需要 JWT（Bearer 或 HttpOnly Cookie）；公开端点仅
  setup-status / setup / login / desktop-session；
- 登录/setup/desktop-session 有限流（`WEBUI_LOGIN_RATELIMIT_PER_MIN`）；
- `HOST=0.0.0.0` 时管理面暴露到局域网：请确保网络可信，或使用反向代理
  + HTTPS；doctor 会对该配置告警；
- 写操作全部落审计（`logs/webui_audit.jsonl`）；任何响应不回显
  api_key/token 明文。

## 里程碑对照

| 里程碑 | 内容 |
|---|---|
| M0 | 骨架：挂载/鉴权/静态托管/契约/CI |
| M1 | 只读面板：统计/会话/日志 SSE/追踪（轨迹流+单条回放）/providers 运行态/平台链路/插件清单 |
| M2 | 写入面：/config 全量编辑、providers/platform 编辑、人格与空间、群组绑定、设置、重启；桌面壳 |
| M3 | 插件（启停/配置/安装/卸载/多源市场）、MCP、Skills、知识库、定时任务 |
| M4 | WebChat（虚拟群 + webchat 空间隔离） |
| M5 | 分包优化（vuetify/charts 独立 chunk）等打磨 |
| M6 | 发布切换（release 流水线产出桌面壳安装器 + webui/dist 随包）、v1 冻结归档 |
