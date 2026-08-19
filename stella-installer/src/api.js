/**
 * 前后端契约层。改这一个文件即可在 mock 与真实后端之间切换 ——
 * 界面代码只认这一层，不直接碰后端。
 *
 * USE_MOCK 保留的理由：改 CSS 时用 mock 更快（不需要 Python 环境、
 * 不需要等真实检查跑完），且能一键构造「全通过」这类难以真实复现的场景。
 */
const USE_MOCK = false;


// withGlobalTauri: true 时可直接用 window.__TAURI__，无需 npm 包
const invoke = window.__TAURI__?.core?.invoke;


const MOCK_DELAY = 600; // 模拟真实调用耗时，便于看 loading 状态


function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}


/** 环境自检。对应 `python -m deploy doctor --json`。 */
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
