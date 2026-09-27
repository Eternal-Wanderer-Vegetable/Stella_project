/**
 * Per-endpoint controller of the managed side: which build the endpoint wants, whether it is
 * installed, and the one llama-server process that serves the endpoint.
 *
 * Launch configuration is latched on start: editing it while the server runs marks the state
 * `configurationPending`, and the next start applies it.
 */
import { join } from 'node:path';
import type { LLMProviderEntry, Logger } from '../../core/types.ts';
import type { Language } from '../../core/language.ts';
import { backendChoices, llamacppOptions, releasePlan, type LaunchOptions, type ReleasePlan } from './options.ts';
import { RuntimeStore, type InstallState } from './runtime-store.ts';
import { LlamaServerManager, serverExecutable, smartAppControlState, type ServerState } from './server.ts';
import { text } from './strings.ts';

export interface RuntimeRoots {
  runtimes: string;
  models: string;
}

export interface LlamaRuntimeOptions {
  name: string;
  entry: () => LLMProviderEntry;
  secret: (name: string) => string;
  log: Logger;
  roots: RuntimeRoots;
  store?: RuntimeStore;
  fetchImpl?: typeof fetch;
  commandOverride?: { command: string; args: string[] };
  platform?: NodeJS.Platform;
  arch?: string;
}

export interface RuntimeState {
  managed: boolean;
  release: string | null;
  backend: string | null;
  backendChoices: string[];
  /** Directory the server runs from: the install, or the operator's own runtime directory. */
  runtimeDir: string | null;
  own: boolean;
  /** False when the upstream ships no build for this backend on this platform. */
  supported: boolean;
  install: InstallState;
  server: (ServerState & { configurationPending: boolean }) | null;
  launch: LaunchOptions | null;
  autoStart: boolean;
  /** Windows Smart App Control: 0 off, 1 enforced, 2 evaluation; null elsewhere. */
  smartAppControl: 0 | 1 | 2 | null;
  cacheDir: string;
  localModelsDir: string;
}

interface Target {
  release: string;
  backend: string;
  own: boolean;
  plan: ReleasePlan | null;
  dir: string | null;
  serverExe: string;
}

export class LlamaRuntime {
  private readonly store: RuntimeStore;
  private current: { key: string; manager: LlamaServerManager } | null = null;
  private transition: Promise<unknown> = Promise.resolve();
  private sac: Promise<0 | 1 | 2 | null> | null = null;
  private readonly platform: NodeJS.Platform;
  private readonly arch: string;

  constructor(private readonly opts: LlamaRuntimeOptions) {
    this.platform = opts.platform ?? process.platform;
    this.arch = opts.arch ?? process.arch;
    this.store = opts.store ?? new RuntimeStore(opts.roots.runtimes, opts.log, opts.fetchImpl);
  }

  managed(): boolean {
    return Boolean(llamacppOptions(this.opts.entry()).runtime);
  }

  modelDirs(): { cacheDir: string; localModelsDir: string } {
    const base = join(this.opts.roots.models, 'llamacpp');
    return { cacheDir: join(base, 'cache'), localModelsDir: join(base, 'local') };
  }

  private target(): Target | null {
    const runtime = llamacppOptions(this.opts.entry()).runtime;
    if (!runtime) return null;
    const own = Boolean(runtime.runtimeDir);
    const plan = own ? null : releasePlan(runtime.release, runtime.backend, this.platform, this.arch);
    return {
      release: runtime.release,
      backend: runtime.backend,
      own,
      plan,
      dir: own ? runtime.runtimeDir! : plan ? this.store.dir(runtime.release, plan) : null,
      serverExe: plan?.serverExe ?? serverExecutable(this.platform),
    };
  }

  installState(language: Language = 'zh'): InstallState {
    const target = this.target();
    if (!target?.dir) return { phase: 'absent', file: null, done: 0, total: null, detail: null };
    if (target.own) return { phase: 'installed', file: null, done: 0, total: null, detail: null };
    return this.store.state(target.dir, language);
  }

  async install(language: Language = 'zh'): Promise<void> {
    const target = this.target();
    if (!target) throw new Error(text(language).notManaged);
    if (target.own) return;
    if (!target.plan) throw new Error(text(language).runtimeUnsupported);
    await this.store.install(target.release, target.plan, language);
  }

  async state(language: Language = 'zh'): Promise<RuntimeState> {
    const options = llamacppOptions(this.opts.entry());
    const target = this.target();
    const dirs = this.modelDirs();
    const base = {
      backendChoices: backendChoices(this.platform, this.arch),
      autoStart: options.autoStart === true,
      smartAppControl: await this.smartAppControl(),
      ...dirs,
    };
    if (!target) {
      return {
        ...base,
        managed: false,
        release: null,
        backend: null,
        runtimeDir: null,
        own: false,
        supported: true,
        install: this.installState(language),
        server: null,
        launch: null,
      };
    }
    const launch = this.launch(language);
    const manager = this.current?.manager ?? launch?.manager();
    return {
      ...base,
      managed: true,
      release: target.release,
      backend: target.backend,
      runtimeDir: target.dir,
      own: target.own,
      supported: target.own || target.plan !== null,
      install: this.installState(language),
      server: manager
        ? { ...(await manager.state(language)), configurationPending: this.current !== null && this.current.key !== launch?.key }
        : null,
      launch: options.launch ?? null,
    };
  }

  private smartAppControl(): Promise<0 | 1 | 2 | null> {
    if (!this.sac) this.sac = smartAppControlState(this.platform);
    return this.sac;
  }

  private launch(language: Language): { key: string; manager: () => LlamaServerManager } | null {
    const entry = this.opts.entry();
    const options = llamacppOptions(entry);
    const target = this.target();
    if (!target?.dir || !options.launch) return null;
    const launch = options.launch;
    const dirs = this.modelDirs();
    const apiKey = entry.secret ? this.opts.secret(entry.secret) : undefined;
    return {
      key: JSON.stringify([entry.baseUrl, target.dir, launch, entry.secret ?? null]),
      manager: () =>
        new LlamaServerManager({
          name: this.opts.name,
          baseUrl: entry.baseUrl,
          runtimeDir: target.dir!,
          serverExe: target.serverExe,
          ...dirs,
          apiKey,
          launch,
          log: this.opts.log,
          commandOverride: this.opts.commandOverride,
          fetchImpl: this.opts.fetchImpl,
        }),
    };
  }

  private schedule<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.transition.then(operation, operation);
    this.transition = next;
    return next;
  }

  start(language: Language = 'zh'): Promise<ServerState | undefined> {
    return this.schedule(async () => {
      const S = text(language);
      const target = this.target();
      if (!target) throw new Error(S.notManaged);
      if (!target.own && this.installState(language).phase !== 'installed') throw new Error(S.runtimeNotInstalled);
      const launch = this.launch(language);
      if (!launch) throw new Error(S.notManaged);
      if (this.current?.key !== launch.key) {
        await this.current?.manager.stop();
        this.current = { key: launch.key, manager: launch.manager() };
      }
      return this.current.manager.start(language);
    });
  }

  stop(language: Language = 'zh'): Promise<ServerState | undefined> {
    return this.schedule(async () => this.current?.manager.stop(language));
  }
}
