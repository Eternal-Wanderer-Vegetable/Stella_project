// 将 dashboard/dist 同步为 Bot 托管面板的前端快照（webui/dist）。
//
// webui/static.py 服务的是 PROJECT_ROOT/webui/dist（gitignore 的本地构建
// 产物）；只在 dashboard/ 里 pnpm build 不会让界面变化生效——必须同步
// （2026-10-02 实测：新增「消息流程」页签后重启 Bot 仍不出现，根因即此）。
// 桌面壳快照 desktop/dashboard-dist 存在时一并镜像，避免两条入口不同步。
//
// 用法：pnpm --dir dashboard sync:webui（先 build，或直接 pnpm build && pnpm sync:webui）
import { cpSync, existsSync, rmSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const src = resolve(repoRoot, 'dashboard', 'dist');
const targets = [
  resolve(repoRoot, 'webui', 'dist'),
  resolve(repoRoot, 'desktop', 'dashboard-dist'),
];

if (!existsSync(resolve(src, 'index.html'))) {
  console.error('dashboard/dist/index.html 不存在：请先 pnpm --dir dashboard build');
  process.exit(1);
}

for (const target of targets) {
  try {
    if (target.includes('dashboard-dist') && !statSync(resolve(target, '..')).isDirectory()) {
      continue;
    }
  } catch {
    // desktop/ 不存在（纯后端检出）：跳过桌面快照
    if (target.includes('dashboard-dist')) continue;
  }
  rmSync(target, { recursive: true, force: true });
  cpSync(src, target, { recursive: true });
  console.log(`synced dashboard/dist -> ${target}`);
}
