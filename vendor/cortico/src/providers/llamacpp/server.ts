/**
 * One llama-server process in router mode: no model on the command line, models come from
 * `LLAMA_CACHE` and `--models-dir`, and the router loads them on first request.
 *
 * A server someone else started at the same endpoint is left alone: `start()` probes first and
 * only spawns when nothing answers.
 */
import { execFile, spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import type { Logger } from '../../core/types.ts';
import type { Language } from '../../core/language.ts';
import type { LaunchOptions } from './options.ts';
import { text, type Text } from './strings.ts';

export type ServerPhase = 'stopped' | 'starting' | 'running' | 'error';

export interface ServerState {
  phase: ServerPhase;
  baseUrl: string;
  detail: string | null;
  pid: number | null;
  /** Whether the endpoint answers `/health` now, whoever started it. */
  reachable: boolean;
}

export interface LlamaServerOptions {
  name: string;
  baseUrl: string;
  /** Directory holding the server executable and its shared libraries. */
  runtimeDir: string;
  serverExe: string;
  /** `LLAMA_CACHE` for the process: where `-hf` style pulls land. */
  cacheDir: string;
  /** `--models-dir`: GGUF files the operator put there by hand. */
  localModelsDir: string;
  apiKey?: string;
  launch: LaunchOptions;
  log: Logger;
  /** Test injection: replaces the spawned command. */
  commandOverride?: { command: string; args: string[] };
  healthIntervalMs?: number;
  healthTimeoutMs?: number;
  fetchImpl?: typeof fetch;
}

type Detail = (S: Text) => string;

export function serverExecutable(platform: NodeJS.Platform = process.platform): string {
  return platform === 'win32' ? 'llama-server.exe' : 'llama-server';
}

/** baseUrl → host / port / origin; null when it names no port. */
export function parseEndpoint(baseUrl: string): { host: string; port: number; origin: string } | null {
  try {
    const url = new URL(baseUrl);
    const port = Number(url.port);
    if (!Number.isFinite(port) || port <= 0) return null;
    return { host: url.hostname, port, origin: url.origin };
  } catch {
    return null;
  }
}

/** Command line of the router; exported so the launch contract is testable without a spawn. */
export function launchArgs(options: Pick<LlamaServerOptions, 'launch' | 'localModelsDir'>, host: string, port: number): string[] {
  const { launch } = options;
  return [
    '--host', host,
    '--port', String(port),
    '--models-dir', options.localModelsDir,
    '-c', String(launch.contextSize),
    '-ngl', String(launch.nGpuLayers),
    '--parallel', String(launch.parallel),
    '--jinja',
    '--reasoning-format', 'deepseek',
    ...launch.extraArgs.split(/\s+/).filter((arg) => arg.length > 0),
  ];
}

/** Library lookup for the spawned process: the archives put everything next to the executable. */
export function launchEnv(runtimeDir: string, cacheDir: string, apiKey: string | undefined, base: NodeJS.ProcessEnv = process.env, platform: NodeJS.Platform = process.platform): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...base, LLAMA_CACHE: cacheDir };
  if (apiKey) env.LLAMA_API_KEY = apiKey;
  if (platform === 'win32') env.PATH = `${runtimeDir};${base.PATH ?? ''}`;
  else if (platform === 'darwin') env.DYLD_LIBRARY_PATH = [runtimeDir, base.DYLD_LIBRARY_PATH].filter(Boolean).join(':');
  else env.LD_LIBRARY_PATH = [runtimeDir, base.LD_LIBRARY_PATH].filter(Boolean).join(':');
  return env;
}

/**
 * Windows UNKNOWN errors include the executable path and a conditional application-control check.
 * The error code alone does not identify an application-control block.
 */
function spawnFailDetail(error: unknown, exe: string): Detail {
  const e = error as NodeJS.ErrnoException;
  if (process.platform === 'win32' && e?.code === 'UNKNOWN') return (S) => S.spawnBlocked(exe);
  return (S) => S.spawnFailed(e?.message ?? String(error));
}

/** Smart App Control: 0 off, 1 enforced, 2 evaluation; null where the value cannot be read. */
export async function smartAppControlState(platform: NodeJS.Platform = process.platform): Promise<0 | 1 | 2 | null> {
  if (platform !== 'win32') return null;
  const output = await new Promise<string>((resolve) => {
    execFile(
      'reg',
      ['query', 'HKLM\\SYSTEM\\CurrentControlSet\\Control\\CI\\Policy', '/v', 'VerifiedAndReputablePolicyState'],
      { windowsHide: true },
      (error, stdout) => resolve(error ? '' : String(stdout)),
    );
  });
  return parseRegDword(output);
}

export function parseRegDword(output: string): 0 | 1 | 2 | null {
  const match = /REG_DWORD\s+0x([0-9a-f]+)/i.exec(output);
  if (!match) return null;
  const value = Number.parseInt(match[1], 16);
  return value === 0 || value === 1 || value === 2 ? value : null;
}

export class LlamaServerManager {
  private phase: ServerPhase = 'stopped';
  private detail: Detail | null = null;
  private proc: ChildProcess | null = null;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private stderrTail = '';
  private readonly fetchImpl: typeof fetch;

  constructor(private readonly opts: LlamaServerOptions) {
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  async state(language: Language = 'zh'): Promise<ServerState> {
    return {
      phase: this.phase,
      baseUrl: this.opts.baseUrl,
      detail: this.detail ? this.detail(text(language)) : null,
      pid: this.proc?.pid ?? null,
      reachable: await this.probe(),
    };
  }

  async start(language: Language = 'zh'): Promise<ServerState> {
    if (this.phase === 'starting' || this.phase === 'running') return this.state(language);
    if (await this.probe()) {
      this.detail = (S) => S.externalServer;
      return this.state(language);
    }
    const launch = this.resolveLaunch();
    if ('error' in launch) {
      this.phase = 'error';
      this.detail = launch.error;
      return this.state(language);
    }
    mkdirSync(this.opts.cacheDir, { recursive: true });
    mkdirSync(this.opts.localModelsDir, { recursive: true });
    this.stderrTail = '';
    let proc: ChildProcess;
    try {
      proc = spawn(launch.command, launch.args, {
        cwd: launch.cwd,
        env: launch.env,
        stdio: ['ignore', 'ignore', 'pipe'],
        windowsHide: true,
      });
    } catch (error) {
      this.fail(spawnFailDetail(error, launch.command));
      return this.state(language);
    }
    this.proc = proc;
    this.phase = 'starting';
    this.detail = (S) => S.starting;
    proc.stderr?.on('data', (chunk: Buffer) => {
      this.stderrTail = (this.stderrTail + chunk.toString()).slice(-2000);
    });
    proc.on('error', (error) => {
      if (this.proc !== proc) return;
      this.proc = null;
      this.fail(spawnFailDetail(error, launch.command));
    });
    proc.on('exit', (code) => {
      if (this.proc !== proc) return;
      this.proc = null;
      if (this.phase === 'stopped') return;
      const tail = this.stderrTail.slice(-400);
      this.fail((S) => S.exited(code, tail));
    });
    this.opts.log.info(`llama-server 启动中 endpoint=${this.opts.name} pid=${proc.pid} ${this.opts.baseUrl}`);
    this.beginHealthPolling();
    return this.state(language);
  }

  async stop(language: Language = 'zh'): Promise<ServerState> {
    this.clearHealthTimer();
    this.phase = 'stopped';
    this.detail = null;
    const proc = this.proc;
    this.proc = null;
    if (proc && proc.exitCode === null) {
      proc.kill();
      await new Promise<void>((resolve) => {
        const force = setTimeout(() => {
          try {
            proc.kill('SIGKILL');
          } catch {
            /* already gone */
          }
          resolve();
        }, 3_000);
        proc.once('exit', () => {
          clearTimeout(force);
          resolve();
        });
      });
      this.opts.log.info(`llama-server 已停止 endpoint=${this.opts.name}`);
    }
    return this.state(language);
  }

  async probe(): Promise<boolean> {
    const endpoint = parseEndpoint(this.opts.baseUrl);
    if (!endpoint) return false;
    try {
      const res = await this.fetchImpl(`${endpoint.origin}/health`, { signal: AbortSignal.timeout(2000) });
      return res.ok;
    } catch {
      return false;
    }
  }

  private resolveLaunch():
    | { command: string; args: string[]; cwd: string | undefined; env: NodeJS.ProcessEnv }
    | { error: Detail } {
    const endpoint = parseEndpoint(this.opts.baseUrl);
    if (!endpoint) return { error: (S) => S.badBaseUrl(this.opts.baseUrl) };
    const env = launchEnv(this.opts.runtimeDir, this.opts.cacheDir, this.opts.apiKey);
    if (this.opts.commandOverride) {
      return { command: this.opts.commandOverride.command, args: this.opts.commandOverride.args, cwd: undefined, env };
    }
    const exe = join(this.opts.runtimeDir, this.opts.serverExe);
    if (!existsSync(exe)) return { error: (S) => S.missingBinary(exe) };
    return { command: exe, args: launchArgs(this.opts, endpoint.host, endpoint.port), cwd: this.opts.runtimeDir, env };
  }

  private beginHealthPolling(): void {
    this.clearHealthTimer();
    const interval = this.opts.healthIntervalMs ?? 1_000;
    const deadline = Date.now() + (this.opts.healthTimeoutMs ?? 120_000);
    this.healthTimer = setInterval(async () => {
      if (this.phase !== 'starting') {
        this.clearHealthTimer();
        return;
      }
      if (await this.probe()) {
        this.phase = 'running';
        this.detail = null;
        this.clearHealthTimer();
        this.opts.log.info(`llama-server 就绪 ${this.opts.baseUrl}`);
        return;
      }
      if (Date.now() > deadline) {
        const orphan = this.proc;
        this.proc = null;
        this.fail((S) => S.healthTimeout);
        try {
          orphan?.kill();
        } catch {
          /* already gone */
        }
      }
    }, interval);
  }

  private clearHealthTimer(): void {
    if (this.healthTimer) clearInterval(this.healthTimer);
    this.healthTimer = null;
  }

  private fail(detail: Detail): void {
    this.clearHealthTimer();
    this.phase = 'error';
    this.detail = detail;
    this.opts.log.warn(`llama-server 异常: ${detail(text('zh'))}`);
  }
}
