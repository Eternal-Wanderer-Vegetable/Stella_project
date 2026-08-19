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
  await delay(200);
  const res = await fetch(`./mock/status-${scenario}.json`);
  return await res.json();
}


/** 读日志尾部 N 行（每行一个 JSON 对象）。Rust 侧读 logs/stella.jsonl。 */
export async function readLogTail(lines = 200) {
  await delay(150);
  const res = await fetch("./mock/logs.jsonl");
  const text = await res.text();
  return text
    .split("\n")
    .filter((l) => l.trim())
    .slice(-lines)
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


/** 启动 Bot（后台）。对应 `deploy start --detach`。 */
export async function startBot() {
  await delay(1200);
  return { ok: true };
}


/** 优雅停止。对应 `deploy stop`。 */
export async function stopBot() {
  await delay(1500);
  return { ok: true };
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
