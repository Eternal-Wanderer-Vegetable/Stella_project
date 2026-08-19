/**
 * 前后端契约层。原型阶段返回 mock，移植到 Tauri 时把每个函数体换成
 * invoke("命令名") 即可 —— 界面代码只认这一层，不直接碰后端。
 *
 * 这份文件同时是「Rust 侧要实现哪些 command」的清单，两边照它写就不会对不上。
 */


const MOCK_DELAY = 600; // 模拟真实调用耗时，便于看 loading 状态


function delay(ms) {
  return new Promise((r) => setTimeout(r, ms));
}


/** 环境自检。对应 `python -m deploy doctor --json`。 */
export async function runDoctor(scenario = "mixed") {
  await delay(MOCK_DELAY);
  const res = await fetch(`./mock/doctor-${scenario}.json`);
  return await res.json();
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


/** 复制到剪贴板。Tauri 侧用 clipboard 插件，浏览器用 navigator。 */
export async function copyText(text) {
  await navigator.clipboard.writeText(text);
}