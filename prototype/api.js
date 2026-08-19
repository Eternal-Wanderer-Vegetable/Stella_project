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


/** 进程状态。对应 `python -m deploy status --json`。 */
export async function getStatus() {
  await delay(200);
  return { pid: null, alive: false, log_file: "logs/stella.jsonl", recent_log: null };
}


/** 复制到剪贴板。Tauri 侧用 clipboard 插件，浏览器用 navigator。 */
export async function copyText(text) {
  await navigator.clipboard.writeText(text);
}