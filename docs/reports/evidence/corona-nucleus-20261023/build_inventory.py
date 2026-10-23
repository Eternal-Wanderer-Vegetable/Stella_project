import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

root = Path.cwd()
out = Path("/tmp/stella-corona-plan-20261023")
base = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
packages = [
    (
        "CN00",
        "冻结基线、兼容性与框架初始化合同",
        [],
        [
            "bot.py",
            "config/settings.py",
            "deploy/process.py",
            "runtime-manager/src/main.rs",
            "tests/test_self_restart.py",
        ],
        ["tests/corona/", "tests/nucleus/"],
    ),
    (
        "CN01",
        "纯启动层与不可变配置快照",
        ["CN00"],
        [
            "config/__init__.py",
            "config/home.py",
            "config/instance.py",
            "config/settings.py",
            "deploy/env_schema.py",
            "deploy/env_merge.py",
            "webui/services/envfile.py",
            "core/transport/adapter_loader.py",
        ],
        ["stella_bootstrap/", "stella_contracts/config.py"],
    ),
    (
        "CN02",
        "Nucleus 托管入口与有界生命周期",
        ["CN01"],
        [
            "bot.py",
            "core/self_restart.py",
            "core/stop_signal.py",
            "stella_project/plugins/bot_main/ai_gateway.py",
            "core/runtime/facade.py",
            "cometa/runtime.py",
            "cometa/supervisor.py",
            "astrbot_compat/render.py",
        ],
        [
            "nucleus/__main__.py",
            "nucleus/bootstrap.py",
            "nucleus/framework.py",
            "nucleus/lifecycle.py",
        ],
    ),
    (
        "CN03",
        "Corona 监管器与独立控制应用",
        ["CN02"],
        [
            "webui/app.py",
            "webui/security.py",
            "webui/auth.py",
            "webui/static.py",
            "webui/source_build.py",
            "config/instance.py",
        ],
        [
            "corona/__main__.py",
            "corona/app.py",
            "corona/supervisor.py",
            "corona/process_tree.py",
            "corona/store.py",
            "corona/ownership.py",
        ],
    ),
    (
        "CN04",
        "内部协议、鉴权、身份与业务接口",
        ["CN02", "CN03"],
        [
            "webui/responses.py",
            "webui/status_source.py",
            "stella_project/plugins/bot_main/status_api.py",
            "webui/chat_ingress.py",
            "webui/routers/chat.py",
        ],
        [
            "stella_contracts/control.py",
            "nucleus/api.py",
            "corona/nucleus_client.py",
            "corona/local_control.py",
        ],
    ),
    (
        "CN05",
        "配置事务、应用操作与配置恢复",
        ["CN01", "CN03", "CN04"],
        [
            "webui/services/envfile.py",
            "webui/services/config.py",
            "webui/services/providers.py",
            "webui/services/platformcfg.py",
            "webui/services/groups.py",
        ],
        ["corona/config_store.py", "corona/operations.py", "corona/recovery.py"],
    ),
    (
        "CN06",
        "WebUI 控制与业务路由分离",
        ["CN04", "CN05"],
        [
            "webui/app.py",
            "webui/mount.py",
            "webui/routers/config.py",
            "webui/services/groups.py",
            "webui/services/spaces.py",
            "webui/services/runtime.py",
            "webui/services/evaluation.py",
            "webui/audit.py",
            "webui/db.py",
        ],
        ["corona/routes.py", "corona/proxy.py", "nucleus/routes.py"],
    ),
    (
        "CN07",
        "稳定公网入口与适配器 HTTP/WebSocket 代理",
        ["CN03", "CN04", "CN06"],
        [
            "core/transport/adapter_loader.py",
            "stella_project/plugins/bot_main/status_api.py",
            "webui/mount.py",
            "tests/webui/test_webui_mount.py",
        ],
        ["corona/adapter_proxy.py", "nucleus/route_catalog.py"],
    ),
    (
        "CN08",
        "Dashboard 操作进度与核心离线体验",
        ["CN05", "CN06", "CN07"],
        [
            "dashboard/src/api/http.ts",
            "dashboard/src/api/sse.ts",
            "dashboard/src/views/ConfigPage.vue",
            "dashboard/src/views/BackendOfflinePage.vue",
            "dashboard/src/stores/auth.ts",
            "dashboard/src/api/tauri.ts",
        ],
        [
            "dashboard/src/api/system.ts",
            "dashboard/src/stores/system.ts",
            "dashboard/src/components/CoreLifecycleBanner.vue",
        ],
    ),
    (
        "CN09",
        "统一 CLI、桌面、Runtime 和启动入口",
        ["CN06", "CN07", "CN08"],
        [
            "bot.py",
            "deploy/__main__.py",
            "deploy/process.py",
            "deploy/runtime.py",
            "runtime-manager/src/lib.rs",
            "runtime-manager/src/main.rs",
            "desktop/src-tauri/src/commands.rs",
            "desktop/src-tauri/src/lib.rs",
            "desktop/src-tauri/src/python.rs",
            "cli/src/main.rs",
            "cli/src/runner.rs",
            "release_assets/start.bat",
        ],
        ["deploy/control_client.py"],
    ),
    (
        "CN10",
        "故障注入、恢复、负载与跨平台验收",
        ["CN09"],
        [
            "tests/test_deploy_process.py",
            "tests/test_graceful_shutdown.py",
            "tests/test_instance.py",
            "tests/cometa/test_g09_policy_runtime.py",
            "tests/cometa/test_runtime_assembly.py",
            "tests/windows/test_process_tree.py",
            "scripts/generate_message_flow.py",
            ".github/workflows/ci.yml",
        ],
        [
            "tests/corona/test_restart_e2e.py",
            "tests/corona/test_crash_recovery.py",
            "tests/corona/test_proxy_contract.py",
            "tests/corona/test_resource_bounds.py",
        ],
    ),
    (
        "CN11",
        "发布负载、灰度切换与可验证回退",
        ["CN10"],
        [
            "Dockerfile",
            "docker-compose.yml",
            "entrypoint.sh",
            ".dockerignore",
            ".github/workflows/release.yml",
            ".github/workflows/docker-publish.yml",
            "scripts/build_release_package.py",
            "scripts/check_release_layout.py",
            "scripts/check_release_archive.py",
            "deploy/install_contract.py",
            "pyproject.toml",
            "requirements.txt",
            "docs/guides/webui.md",
            "docs/guides/webui.en.md",
            "docs/development/deployment.md",
            "docs/development/deployment.en.md",
            "docs/development/contracts.md",
            "docs/development/contracts.en.md",
        ],
        [],
    ),
]
extras = {
    "CN00": ["requirements-platform.lock", "requirements.txt", "pyproject.toml"],
    "CN01": [".env.example"],
    "CN06": [
        p.as_posix()
        for pattern in ("webui/routers/*.py", "webui/services/*.py")
        for p in Path().glob(pattern)
    ],
    "CN08": [
        "dashboard/src/views/ProvidersPage.vue",
        "dashboard/src/views/PlatformsPage.vue",
        "dashboard/src/views/GroupsPage.vue",
        "dashboard/src/views/PersonaPage.vue",
        "dashboard/src/views/ChatPage.vue",
        "dashboard/src/views/SettingsPage.vue",
        "dashboard/src/views/CometaPage.vue",
        "dashboard/src/views/CronPage.vue",
        "dashboard/src/views/auth/LoginPage.vue",
        "dashboard/src/views/auth/SetupPage.vue",
    ],
    "CN09": [
        "runtime-manager/schemas/runtime-manifest.schema.json",
        "runtime-manager/schemas/runtime-state.schema.json",
        "runtime-manager/schemas/fixtures/runtime-manifest.json",
        "runtime-manager/schemas/fixtures/runtime-state.json",
    ],
    "CN10": [
        "core/observability/internal_flow_catalog.py",
        "core/observability/flow_catalog.py",
    ],
    "CN11": [
        "docs/architecture/overview.md",
        "docs/architecture/overview.en.md",
        "docs/architecture/integrations.md",
        "docs/architecture/integrations.en.md",
        "docs/guides/deployment-docker.md",
        "docs/guides/deployment-docker.en.md",
        "scripts/build_release_manifest.py",
        "release_assets/VM-MATRIX.md",
    ],
}
packages = [
    (i, n, d, sorted(set(f + extras.get(i, []))), p) for i, n, d, f, p in packages
]
work = []
for ident, name, deps, files, new in packages:
    for f in files:
        assert (root / f).is_file(), f
    work.append(
        {
            "id": ident,
            "name": name,
            "status": "planned",
            "depends_on": deps,
            "owner": "单一实施负责人；同轮只激活一个工作包",
            "existing_files": files,
            "new_paths": new,
            "exit_criteria_ref": f"2026-10-23-corona-nucleus-engineering-plan.md#{ident.lower()}",
        }
    )
files = {f for w in work for f in w["existing_files"]}
for pattern in [
    "webui/routers/*.py",
    "webui/services/*.py",
    "tests/webui/test_*.py",
    "core/observability/flows/catalog.py",
]:
    files.update(p.as_posix() for p in root.glob(pattern) if p.is_file())
for f in [
    "config/spaces.py",
    "config/space_map.py",
    "core/logging_sink.py",
    "deploy/windows_reliability.py",
    "deploy/llama.py",
    "dashboard/src/views/PlatformsPage.vue",
    "dashboard/src/views/ProvidersPage.vue",
    "dashboard/src/views/GroupsPage.vue",
    "dashboard/src/views/SpacesPage.vue",
    "dashboard/src/views/WebChatPage.vue",
]:
    if (root / f).is_file():
        files.add(f)
source = []
for file in sorted(files):
    source.append(
        {
            "path": file,
            "sha256": hashlib.sha256((root / file).read_bytes()).hexdigest(),
            "work_packages": [w["id"] for w in work if file in w["existing_files"]],
            "review_role": "boundary-audit"
            if not any(file in w["existing_files"] for w in work)
            else "implementation-candidate",
        }
    )
routes = []
control_paths = {
    "/api/v1/config",
    "/api/v1/config/schema",
    "/api/v1/providers/endpoints",
    "/api/v1/providers/roles",
    "/api/v1/platform/onebot",
    "/api/v1/platform/adapters",
    "/api/v1/system/restart",
    "/api/v1/system/doctor",
    "/api/v1/status",
}
for path in sorted(Path("webui/routers").glob("*.py")):
    tree = ast.parse(path.read_text())
    prefixes = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "APIRouter"
        ):
            prefix = next(
                (
                    ast.literal_eval(k.value)
                    for k in node.value.keywords
                    if k.arg == "prefix"
                ),
                "",
            )
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if (
                not isinstance(d, ast.Call)
                or not isinstance(d.func, ast.Attribute)
                or d.func.attr
                not in {"get", "post", "put", "patch", "delete", "websocket"}
            ):
                continue
            if not d.args or not isinstance(d.args[0], ast.Constant):
                continue
            route = prefixes.get(getattr(d.func.value, "id", ""), "") + d.args[0].value
            owner = (
                "corona"
                if route.startswith("/api/v1/auth/") or route in control_paths
                else "nucleus"
            )
            if route == "/api/v1/groups/bindings":
                owner = "split-config-and-business"
            routes.append(
                {
                    "method": d.func.attr.upper(),
                    "path": route,
                    "symbol": node.name,
                    "source": path.as_posix(),
                    "line": node.lineno,
                    "proposed_owner": owner,
                    "status": "planned",
                    "auth": "preserve current route auth; internal hop additionally requires generation capability",
                    "unavailable": "available during core outage"
                    if owner == "corona"
                    else "503 core_unavailable; streaming requests terminal error/close; never auto-replay write",
                }
            )
assert len({(r["method"], r["path"]) for r in routes}) == len(routes)
keys = {}
for file in ["config/settings.py", "config/instance.py", "config/home.py"]:
    tree = ast.parse(Path(file).read_text())
    for n in ast.walk(tree):
        if (
            not isinstance(n, ast.Call)
            or not n.args
            or not isinstance(n.args[0], ast.Constant)
            or not isinstance(n.args[0].value, str)
        ):
            continue
        helper = ast.unparse(n.func)
        key = n.args[0].value
        if helper == "_endpoint_slot":
            if len(n.args) < 2 or not isinstance(n.args[1], ast.Constant):
                continue
            field = n.args[1].value
            for prefix_arg in [n.args[0], *n.args[3:]]:
                if isinstance(prefix_arg, ast.Constant) and isinstance(
                    prefix_arg.value, str
                ):
                    endpoint_key = prefix_arg.value + field
                    keys.setdefault(
                        endpoint_key,
                        {
                            "key": endpoint_key,
                            "scope": "nucleus",
                            "source_sites": [],
                            "status": "literal endpoint slot/legacy alias; managed effective config preserves fallback precedence",
                        },
                    )["source_sites"].append(
                        {"path": file, "line": n.lineno, "reader": helper}
                    )
            continue
        if not (
            helper.startswith("_env")
            or helper == "_endpoint_slot"
            or helper in ("os.getenv", "os.environ.get")
        ):
            continue
        if not re.fullmatch("[A-Z][A-Z0-9_]*", key):
            continue
        scope = "corona" if key.startswith("WEBUI_") else "nucleus"
        if key in {
            "STELLA_HOME",
            "STELLA_INSTANCE_ID",
            "STELLA_LAUNCH_TOKEN",
            "STELLA_STOP_SENTINEL",
            "STELLA_RESTART_PARENT_PID",
            "ENVIRONMENT",
        }:
            scope = "bootstrap-identity"
        keys.setdefault(
            key,
            {
                "key": key,
                "scope": scope,
                "source_sites": [],
                "status": "proposed ownership; CN00 reconcile dynamic/plugin keys",
            },
        )["source_sites"].append({"path": file, "line": n.lineno, "reader": helper})
for key in [
    "HOST",
    "PORT",
    "ONEBOT_WS_URLS",
    "ONEBOT_ACCESS_TOKEN",
    "DRIVER",
    "SUPERUSERS",
    "NICKNAME",
    "COMMAND_START",
    "COMMAND_SEP",
    "STELLA_HOME",
    "STELLA_INSTANCE_ID",
    "STELLA_LAUNCH_TOKEN",
    "STELLA_STOP_SENTINEL",
    "STELLA_RESTART_PARENT_PID",
]:
    keys.setdefault(
        key,
        {
            "key": key,
            "scope": "corona-public-listener"
            if key in ("HOST", "PORT")
            else "nucleus-framework",
            "source_sites": [],
            "status": "NoneBot/adapter direct environment key; requires driver snapshot contract",
        },
    )
for key in [
    "STELLA_HOME",
    "STELLA_INSTANCE_ID",
    "STELLA_LAUNCH_TOKEN",
    "STELLA_STOP_SENTINEL",
    "STELLA_RESTART_PARENT_PID",
]:
    keys[key]["scope"] = "bootstrap-identity"
scenarios = [
    ("A01", "配置新增/修改", "new .env value is applied and revision equals desired"),
    (
        "A02",
        "配置删除/继承/空值",
        "removed key returns default; secret blank remains unchanged",
    ),
    (
        "A03",
        "外部覆盖与环境文件",
        "external overrides base, selected overlay overrides external; source displayed",
    ),
    (
        "A04",
        "语法/类型/跨字段错误",
        "reject before old core drains; keep management available",
    ),
    ("A05", "双浏览器并发保存", "expected_revision mismatch 409; no lost updates"),
    (
        "A06",
        "重复重启与断线重试",
        "same idempotency key returns same operation; one child generation",
    ),
    (
        "A07",
        "保存后进程崩溃",
        "journal reconciles file digest and committed revision without duplicate spawn",
    ),
    (
        "A08",
        "新核心导入/端口/ready失败",
        "failure visible, old generation not falsely healthy, bounded restore",
    ),
    (
        "A09",
        "排空超时/不合作任务",
        "deadline enforced; owned tree terminated; no second writer before exit",
    ),
    (
        "A10",
        "重启期间WebUI/登录",
        "management HTML, auth and operations remain available with same token",
    ),
    (
        "A11",
        "WebChat在途重启/断连",
        "terminal interrupted/unknown; no automatic model/tool replay",
    ),
    (
        "A12",
        "QQ/适配器重连",
        "same public URL reconnects; no promise to buffer outage messages",
    ),
    (
        "A13",
        "Cometa在途/未知投递",
        "preserve owner lease/recovery matrix; no unconditional requeue",
    ),
    (
        "A14",
        "调度到期/重复发送",
        "single owner; existing delivery_unknown contract honored",
    ),
    (
        "A15",
        "记忆整合/Compact中断",
        "failed work does not advance successful watermark; no production fixture",
    ),
    (
        "A16",
        "MCP/插件/Chromium子进程",
        "only owned resources stopped; zero leaked owned descendants",
    ),
    (
        "A17",
        "核心SIGKILL/退出风暴",
        "bounded backoff then failed; management remains available",
    ),
    (
        "A18",
        "Corona崩溃/整机重启",
        "orphan core fenced; reconcile owned tree before new generation",
    ),
    (
        "A19",
        "PID复用/外国进程",
        "no kill based on PID or name alone; ownership failure blocks start",
    ),
    (
        "A20",
        "多实例/共享数据根",
        "distinct control dirs; same canonical business home cannot host two managed writer cores",
    ),
    (
        "A21",
        "伪造内部头/直连内部端口",
        "401/403; private capability/actor never accepted from browser",
    ),
    (
        "A22",
        "远端访问旧状态端点",
        "/stella/status keeps original loopback-only boundary after proxy",
    ),
    (
        "A23",
        "SSE/WS/上传/下载",
        "bounded streaming, cancellation, headers/query/body preserved",
    ),
    (
        "A24",
        "HEAD/编码路径/重定向",
        "reserved namespaces not bypassed; no redirect to private endpoint",
    ),
    (
        "A25",
        "模型离线/平台未连接",
        "core can become ready with explicit degraded external dependencies",
    ),
    ("A26", "坏业务配置/缺失依赖", "Corona import fence keeps repair UI available"),
    (
        "A27",
        "修改Corona端口/禁用WebUI",
        "explicit corona restart scope; no false nucleus-only success",
    ),
    (
        "A28",
        "旧启动/CLI/桌面/容器停止",
        "one ownership chain; controlled shutdown within host budget",
    ),
    (
        "A29",
        "配置回退/数据库迁移",
        "only config reverts automatically; schema-changing release rollback blocked",
    ),
    (
        "A30",
        "源码/发行包前端资产",
        "core restart never runs pnpm; source build on Corona code startup only",
    ),
    (
        "A31",
        "长时间与100次重启",
        "fake-core real-process cycles: one core max, no FD/thread/child growth trend",
    ),
    (
        "A32",
        "Windows/Linux/容器产品矩阵",
        "native clean environments and final package checks recorded separately",
    ),
    (
        "A33",
        "NoneBot二次读取配置",
        "managed settings and driver consume one immutable revision; root .env cannot reintroduce removed values",
    ),
    (
        "A34",
        "混合群绑定写入",
        "config and space changes expose substep outcomes; reconciliation/compensation prevents false atomic success",
    ),
]
inv = {
    "schema_version": 1,
    "date": "2026-10-23",
    "timezone": "Asia/Shanghai",
    "baseline_commit": base,
    "status": "planning_in_progress_implementation_not_started",
    "repository": "Stella_project",
    "work_packages": work,
    "source_inventory": source,
    "webui_routes": routes,
    "configuration_keys": sorted(keys.values(), key=lambda x: x["key"]),
    "acceptance_scenarios": [
        {
            "id": i,
            "scenario": s,
            "assertion": a,
            "status": "not_run_for_new_architecture",
        }
        for i, s, a in scenarios
    ],
    "graph_limitations": [
        "814 inferred flows are a bounded graph snapshot, not the denominator of runtime entries",
        "Prior analyzer reported 2889 candidate entries omitted, 804 callees omitted, 41 walks budget-limited, 21 depth-limited traces",
        "File-level impact has no process/community membership; zero flow count is not absence",
        "UNKNOWN/file omissions/dynamic decorators/cross-language Tauri invokes require source evidence",
        "Plugin-provided/dynamically configured environment keys and adapter routes are not exhaustively enumerable from static AST",
    ],
}
(out / "inventory.json").write_text(
    json.dumps(inv, ensure_ascii=False, indent=2) + "\n"
)
print(
    json.dumps(
        {
            "packages": len(work),
            "source_files": len(source),
            "routes": len(routes),
            "route_owners": {
                o: sum(r["proposed_owner"] == o for r in routes)
                for o in sorted({r["proposed_owner"] for r in routes})
            },
            "config_keys": len(keys),
            "scenarios": len(scenarios),
        },
        ensure_ascii=False,
    )
)
