/**
 * 路径解析(src/paths.ts):三个根的分工、CORTICO_HOME 的解析链,以及默认值解析回
 * `<主仓库>/deployments`(相对路径按主仓库算,不跟着当前 worktree 走)。
 */
import { describe, it, expect, afterEach } from 'vitest';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import {
  DEPLOYMENT_ROOT_ENV,
  deploymentDir,
  deploymentRoot,
  mainRepoRoot,
  modelsRoot,
  providersRoot,
  repoRoot,
  resolveDeploymentRoot,
  resolveMainRepoRoot,
  runtimesRoot,
} from '../src/paths.ts';

const dirs: string[] = [];

afterEach(() => {
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/** 一个真的临时目录当"检出根"。不用 fs.cpSync(本仓禁令),要什么就现写什么。 */
function tempRoot(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  dirs.push(dir);
  return dir;
}

function writeRootEnv(dir: string, body: string): void {
  writeFileSync(join(dir, '.env'), body, 'utf8');
}

describe('resolveDeploymentRoot:解析链', () => {
  const checkout = () => tempRoot('paths-checkout-');
  const MAIN = resolve(sep, 'main-repo');

  it('进程环境的 CORTICO_HOME 最优先,压过仓库根 .env', () => {
    const dir = checkout();
    writeRootEnv(dir, `${DEPLOYMENT_ROOT_ENV}=${resolve(sep, 'from-env-file')}\n`);
    const want = resolve(sep, 'from-process-env');
    expect(resolveDeploymentRoot({ [DEPLOYMENT_ROOT_ENV]: want }, dir, MAIN)).toBe(want);
  });

  it('进程环境没有时用仓库根 .env 里的值', () => {
    const dir = checkout();
    const want = resolve(sep, 'from-env-file');
    writeRootEnv(dir, `# 注释\nOTHER_KEY=x\n${DEPLOYMENT_ROOT_ENV}=${want}\n`);
    expect(resolveDeploymentRoot({}, dir, MAIN)).toBe(want);
  });

  it('进程环境里是空串/纯空白视同没设,继续往下走', () => {
    const dir = checkout();
    const want = resolve(sep, 'from-env-file');
    writeRootEnv(dir, `${DEPLOYMENT_ROOT_ENV}=${want}\n`);
    expect(resolveDeploymentRoot({ [DEPLOYMENT_ROOT_ENV]: '   ' }, dir, MAIN)).toBe(want);
  });

  it('.env 里的值可以带引号、可以含空格', () => {
    const dir = checkout();
    const want = resolve(sep, 'my deployments');
    writeRootEnv(dir, `${DEPLOYMENT_ROOT_ENV}="${want}"\n`);
    expect(resolveDeploymentRoot({}, dir, MAIN)).toBe(want);
  });

  it('被注释掉的那行不算数,落回默认值', () => {
    const dir = checkout();
    writeRootEnv(dir, `#${DEPLOYMENT_ROOT_ENV}=${resolve(sep, 'commented-out')}\n`);
    expect(resolveDeploymentRoot({}, dir, MAIN)).toBe(resolve(MAIN, 'deployments'));
  });

  it('两处都没有时用默认值:<主仓库根>/deployments', () => {
    const dir = checkout();
    expect(existsSync(join(dir, '.env'))).toBe(false);
    expect(resolveDeploymentRoot({}, dir, MAIN)).toBe(resolve(MAIN, 'deployments'));
  });

  it('相对路径按主仓库根解析,不按当前 worktree', () => {
    const dir = checkout();
    writeRootEnv(dir, `${DEPLOYMENT_ROOT_ENV}=../cortico-deployments\n`);
    expect(resolveDeploymentRoot({}, dir, MAIN)).toBe(resolve(MAIN, '../cortico-deployments'));
    expect(resolveDeploymentRoot({ [DEPLOYMENT_ROOT_ENV]: 'deployments' }, dir, MAIN))
      .toBe(resolve(MAIN, 'deployments'));
  });

  it('绝对路径原样采用,与两个仓库根都无关', () => {
    const dir = checkout();
    const want = resolve(sep, 'elsewhere', 'deployments');
    expect(resolveDeploymentRoot({ [DEPLOYMENT_ROOT_ENV]: want }, dir, MAIN)).toBe(want);
  });
});

describe('resolveMainRepoRoot:worktree 指回主仓库', () => {
  it('主仓库里就是检出根本身;worktree 里指回主仓库', () => {
    const dir = tempRoot('paths-git-');
    const main = join(dir, 'main');
    const tree = join(dir, 'tree');
    mkdirSync(main, { recursive: true });
    const git = (cwd: string, ...args: string[]): void => {
      execFileSync('git', args, { cwd, stdio: ['ignore', 'ignore', 'ignore'] });
    };
    try {
      git(main, 'init', '-q');
      git(main, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', 'root');
      git(main, 'worktree', 'add', '-q', '--detach', tree);
    } catch {
      return; // 机器上没有可用的 git:这条断言不成立,别把红报在环境上
    }
    try {
      // 主仓库里 --git-common-dir 回 `.git`,父目录就是检出根本身
      expect(resolveMainRepoRoot(main)).toBe(main);
      // worktree 里回的是共享的 <主仓库>/.git(绝对路径),父目录跨回主仓库。
      // 临时目录在 Windows 上可能带 8.3 短名,两边都过一遍 realpath 再比。
      const real = (p: string): string => realpathSync.native(p).toLowerCase();
      expect(real(resolveMainRepoRoot(tree))).toBe(real(main));
      expect(real(resolveMainRepoRoot(tree))).not.toBe(real(tree));
    } finally {
      try { git(main, 'worktree', 'remove', '--force', tree); } catch { /* 清目录时一并删 */ }
    }
  });

  it('不在 git 仓里就回退到传进来的检出根', () => {
    const dir = tempRoot('paths-nogit-');
    // 临时目录可能落在某个仓库里(极少见);那种情况下这条断言无意义,跳过
    let inRepo = true;
    try {
      execFileSync('git', ['rev-parse', '--git-dir'], { cwd: dir, stdio: ['ignore', 'ignore', 'ignore'] });
    } catch {
      inRepo = false;
    }
    if (!inRepo) expect(resolveMainRepoRoot(dir)).toBe(dir);
  });
});

describe('本进程上的三个根', () => {
  it('repoRoot() 是 src/ 的上一级,且含 package.json', () => {
    expect(repoRoot()).toBe(resolve(import.meta.dirname, '..'));
    expect(existsSync(join(repoRoot(), 'package.json'))).toBe(true);
  });

  it('deploymentDir(name) 就是部署根下的同名目录', () => {
    expect(deploymentDir('cortiv')).toBe(resolve(deploymentRoot(), 'cortiv'));
  });

  it('端点表、运行时与模型三个机器级根都直接挂在部署根下', () => {
    expect(providersRoot()).toBe(resolve(deploymentRoot(), 'providers'));
    expect(runtimesRoot()).toBe(resolve(deploymentRoot(), 'runtimes'));
    expect(modelsRoot()).toBe(resolve(deploymentRoot(), 'models'));
  });

  it('没设 CORTICO_HOME 时 deploymentDir("cortiv") 落在 <主仓库>/deployments/cortiv', () => {
    const configured =
      (process.env[DEPLOYMENT_ROOT_ENV] ?? '').trim() !== '' || existsSync(join(repoRoot(), '.env'));
    if (configured) return; // 这台机器把部署根挪走了,判据不适用
    expect(deploymentDir('cortiv')).toBe(resolve(mainRepoRoot(), 'deployments', 'cortiv'));
  });
});
