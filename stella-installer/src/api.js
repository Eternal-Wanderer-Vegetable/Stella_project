/**
 * 前后端契约层。改这一个文件即可在 mock 与真实后端之间切换 ——
 * 界面代码只认这一层，不直接碰后端。
 *
 * USE_MOCK 保留的理由：改 CSS 时用 mock 更快（不需要 Python 环境、
 * 不需要等真实检查跑完），且能一键构造「全通过」这类难以真实复现的场景。
 */
const USE_MOCK = false;


// withGlobalTauri: true 时前端可直接用 window.__TAURI__，无需 npm 包。
// 但 invoke 的位置在 Tauri 2.x 的不同 patch 版本间有过调整
// （曾在 window.__TAURI__.invoke，后移到 window.__TAURI__.core.invoke），
// 因此两处都探测，取不到才退回 mock。
const invoke =
  window.__TAURI__?.core?.invoke ??
  window.__TAURI__?.invoke ??
  null;


// 启动时打一行，便于确认走的是真实调用还是 mock
console.log("[api] invoke =", invoke ? "已就绪" : "不可用（将使用 mock）",
            "window.__TAURI__ =", window.__TAURI__);


const MOCK_DELAY = 600; // 模拟真实调用耗时，便于看 loading 状态


function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}


/**
 * 环境自检。对应 `python -m deploy doctor --json`。
 *
 * scenario 只在 mock 模式下生效（切换 doctor-*.json 看不同界面状态）；
 * 走真实后端时它被忽略——检查结果由环境决定，不是前端能选的。
 */
export async function runDoctor(scenario = "mixed") {
  if (USE_MOCK || !invoke) {
    await delay(MOCK_DELAY);
    const res = await fetch(`./mock/doctor-${scenario}.json`);
    return await res.json();
  }
  const raw = await invoke("run_doctor");
  return JSON.parse(raw);
}


/** 进程与链路状态。对应 `python -m deploy status --json`。 */
export async function getStatus(scenario = "running") {
  if (USE_MOCK || !invoke) {
    await delay(200);
    const res = await fetch(`./mock/status-${scenario}.json`);
    return await res.json();
  }
  return JSON.parse(await invoke("get_status"));
}


/**
 * 读日志尾部。Rust 侧直读文件（不经 Python）——更快，且 Bot 崩了之后
 * 仍能读到崩溃前的日志。
 *
 * path 来自 getStatus() 的 log_file 字段：日志路径由 STELLA_JSON_LOG_PATH
 * 配置决定，硬编码会在用户改过配置时读错文件。
 */
export async function readLogTail(path = null, maxBytes = 262144) {
  let text;
  if (USE_MOCK || !invoke) {
    await delay(150);
    text = await (await fetch("./mock/logs.jsonl")).text();
  } else {
    text = await invoke("read_log_tail", { path, maxBytes });
  }
  return text
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => {
      try {
        return JSON.parse(l);
      } catch {
        // 轮转瞬间可能读到半行，跳过而非崩溃
        return null;
      }
    })
    .filter(Boolean);
}


/** 启动 Bot（后台）。force=true 时忽略 doctor 的阻塞问题。 */
export async function startBot(force = false) {
  if (USE_MOCK || !invoke) {
    await delay(1200);
    return { ok: true };
  }
  return { ok: true, message: await invoke("start_bot", { force }) };
}


/** 优雅停止。可能耗时较久（等在途任务收尾）。 */
export async function stopBot() {
  if (USE_MOCK || !invoke) {
    await delay(1500);
    return { ok: true };
  }
  return { ok: true, message: await invoke("stop_bot") };
}

/** 读取 GUI 配置向导的当前值。 */
export async function getConfig() {
  if (USE_MOCK || !invoke) {
    return {
      configured: false,
      allowed_groups: "",
      onebot_mode: "reverse",
      host: "127.0.0.1",
      port: 8080,
      ws_urls: "",
      access_token: "",
      lm_base_url: "http://127.0.0.1:1234",
      chat_model: "",
      consolidation_model: "",
      embedding_model: "",
      spaces: "",
      advanced_env: "",
      advanced_values: {},
      schema: { version: 1, fields: [] },
    };
  }
  return JSON.parse(await invoke("get_config"));
}

/** 保存 GUI 配置，实际校验和 .env 渲染由 deploy init 完成。 */
export async function saveConfig(config) {
  if (USE_MOCK || !invoke) return { ok: true };
  return await invoke("save_config", { config });
}

/**
 * 读某个 OpenAI 兼容端点的模型列表（`/v1/models`）。
 *
 * apiKey 可留空：本机 LM Studio 一般不校验，在线端点必须带。key 只在这一次
 * 请求里当 Authorization 头用掉，不写盘、不进任何返回值。
 */
export async function listModels(baseUrl, apiKey = "") {
  if (USE_MOCK || !invoke) return [];
  return JSON.parse(await invoke("list_models", { baseUrl, apiKey }));
}

export async function getVersion() {
  if (USE_MOCK || !invoke) return "2.6.0";
  return await invoke("get_version");
}

export async function getPersonas() {
  if (USE_MOCK || !invoke) return [];
  return JSON.parse(await invoke("get_personas"));
}

export async function savePersona(space, promptFile, content) {
  if (USE_MOCK || !invoke) return "已保存";
  return await invoke("save_persona", { space, promptFile, content });
}


/**
 * 从旧版本导入用户数据。对应 `python -m deploy migrate`。
 *
 * 返回 Markdown 报告原文——同一份内容也会写进 migration_report.md 给用户留档，
 * 只生成一次就不会两处不一致。dryRun=true 既是预览也是探测：没找到旧目录时
 * 报告里会写明，界面据此决定要不要显示导入按钮。
 */
export async function runMigrate({ source = null, dryRun = true } = {}) {
  if (USE_MOCK || !invoke) {
    await delay(MOCK_DELAY);
    return await (await fetch("./mock/migrate-report.md")).text();
  }
  return await invoke("run_migrate", { source, dryRun });
}

export async function installCloseOverlay() {
  const listen = window.__TAURI__?.event?.listen;
  if (!listen) return;
  await listen("close-requested", () => {
    if (document.getElementById("close-overlay")) return;
    const overlay = document.createElement("div");
    overlay.id = "close-overlay";
    overlay.innerHTML = `<div class="close-card"><div class="close-spinner"></div><strong>正在安全关闭 Stella</strong><span>正在等待 Bot 完成退出……若有未完成的记忆整合，可能需要数十秒，请勿强制关闭窗口。</span></div>`;
    document.body.appendChild(overlay);
  });
  await listen("close-failed", (event) => {
    document.getElementById("close-overlay")?.remove();
    const msg = event?.payload ?? event;
    alert(`安全关闭失败：\n${msg}\n\n可再次尝试关闭窗口，或手动执行 stop.bat / python -m deploy stop。`);
  });
}


/** 复制到剪贴板。 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // WebView 里 clipboard API 可能因权限受限失败，退化到 execCommand
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}
