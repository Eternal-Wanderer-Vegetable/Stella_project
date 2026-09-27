/**
 * 观察者客户端那扇窗:有没有出来、改标题。
 *
 * 走 Windows PowerShell + user32(见 client-window.ps1),不引第三方原生依赖。
 * 认哪扇窗一律按 `ownerPid`:同一台机器上还有人自己玩的那份客户端,
 * 除了进程没有第二个凭据分得开她的窗口和别人的窗口。标题改成账号名是给 OBS 认的。
 */
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import type { Logger } from '../../core/types.ts';

const SCRIPT = fileURLToPath(new URL('./client-window.ps1', import.meta.url));

interface ScriptOutput {
  ok?: boolean;
  error?: string;
  title?: string;
}

function runScript(args: string[], timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const proc = spawn(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', SCRIPT, ...args],
      { windowsHide: true },
    );
    let out = '';
    let err = '';
    const timer = setTimeout(() => {
      try { proc.kill(); } catch { /* 已退出 */ }
      reject(new Error(`窗口探测超时 ${timeoutMs}ms`));
    }, timeoutMs);
    proc.stdout.on('data', (c: Buffer) => { out += c.toString(); });
    proc.stderr.on('data', (c: Buffer) => { err += c.toString(); });
    proc.on('error', (e) => { clearTimeout(timer); reject(e); });
    proc.on('close', (code) => {
      clearTimeout(timer);
      if (code !== 0 && !out.trim()) reject(new Error(`powershell code=${code} ${err.slice(-300)}`));
      else resolve(out);
    });
  });
}

function parseLast(raw: string): ScriptOutput | null {
  const line = raw.trim().split(/\r?\n/).filter(Boolean).pop() ?? '';
  try {
    return JSON.parse(line) as ScriptOutput;
  } catch {
    return null;
  }
}

/** 客户端就绪判定:进程名下出现了一扇可见窗口。非 Windows 一律 false。 */
export async function findWindow(opts: { ownerPid: number; log?: Logger }): Promise<boolean> {
  if (process.platform !== 'win32') return false;
  let raw: string;
  try {
    raw = await runScript(['-OwnerPid', String(opts.ownerPid)], 15_000);
  } catch (err) {
    opts.log?.warn(`窗口探测失败: ${(err as Error).message}`);
    return false;
  }
  const parsed = parseLast(raw);
  if (!parsed) {
    opts.log?.warn(`窗口探测输出看不懂: ${raw.trim().slice(-200)}`);
    return false;
  }
  if (!parsed.ok && parsed.error && parsed.error !== 'no-window') opts.log?.warn(`窗口探测: ${parsed.error}`);
  return parsed.ok === true;
}

/** 按进程改窗口标题。给 OBS 按标题区分两份客户端;失败不抛。 */
export async function setWindowTitle(opts: {
  ownerPid: number;
  title: string;
  log?: Logger;
}): Promise<boolean> {
  if (process.platform !== 'win32' || !opts.title) return false;
  let raw: string;
  try {
    raw = await runScript(['-OwnerPid', String(opts.ownerPid), '-SetTitle', opts.title], 8_000);
  } catch (err) {
    opts.log?.warn(`窗口标题未改成 ${opts.title}: ${(err as Error).message}`);
    return false;
  }
  const parsed = parseLast(raw);
  if (!parsed) {
    opts.log?.warn(`窗口标题输出看不懂: ${raw.trim().slice(-200)}`);
    return false;
  }
  if (parsed.ok) return true;
  if (parsed.error && parsed.error !== 'no-window') {
    opts.log?.warn(`窗口标题未改成 ${opts.title}: ${parsed.error}`);
  }
  return false;
}
