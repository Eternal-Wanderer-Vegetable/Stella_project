/**
 * 把 `tests/fixtures/extensions/<名>/` 下的整包复制进临时目录的 `extensions/node_modules/`,
 * 并登记进 `extensions/package.json` 的 dependencies——与 pnpm 装完之后的磁盘形态一致。
 *
 * 路径里必须带 `node_modules`:vitest 只对项目内的文件做转换,带 node_modules 的走 Node
 * 原生 import,扩展的 `cortico/*` 解析钩子才轮得到。复制而不是软链,同理由:软链会把包
 * 拉回项目树里。
 */
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const FIXTURE_ROOT = fileURLToPath(new URL('.', import.meta.url));

function copyTree(from: string, to: string): void {
  mkdirSync(to, { recursive: true });
  for (const entry of readdirSync(from, { withFileTypes: true })) {
    if (entry.isDirectory()) copyTree(join(from, entry.name), join(to, entry.name));
    else copyFileSync(join(from, entry.name), join(to, entry.name));
  }
}

/** 装一个夹具包,返回它在临时目录里的包目录。装上的名字默认就是夹具目录名。 */
export function installFixture(
  root: string,
  fixture: string,
  opts: { as?: string; spec?: string } = {},
): string {
  const name = opts.as ?? fixture;
  const dir = join(root, 'extensions');
  mkdirSync(dir, { recursive: true });
  const pkgFile = join(dir, 'package.json');
  const pkg: { name?: string; private?: boolean; dependencies: Record<string, string> } = existsSync(pkgFile)
    ? JSON.parse(readFileSync(pkgFile, 'utf8')) as { dependencies: Record<string, string> }
    : { name: 'cortico-extensions', private: true, dependencies: {} };
  pkg.dependencies[name] = opts.spec ?? '^1.0.0';
  writeFileSync(pkgFile, JSON.stringify(pkg));
  const pkgDir = join(dir, 'node_modules', ...name.split('/'));
  copyTree(join(FIXTURE_ROOT, fixture), pkgDir);
  return pkgDir;
}
