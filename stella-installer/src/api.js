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
    };
  }
  return JSON.parse(await invoke("get_config"));
}

/** 保存 GUI 配置，实际校验和 .env 渲染由 deploy init 完成。 */
export async function saveConfig(config) {
  if (USE_MOCK || !invoke) return { ok: true };
  return await invoke("save_config", { config });
}

export async function listModels(baseUrl) {
  if (USE_MOCK || !invoke) return [];
  return JSON.parse(await invoke("list_models", { baseUrl }));
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
