/** 管理当前颜色方案、明暗模式、自定义方案与未保存预览。首屏由 applyStoredTheme 同步应用；订阅者接收变化，图表据此重绘。 */

import { toDisposable, type Disposable } from '../../shared/client-panel.ts';
import {
  THEME_MODES,
  builtinSchemes,
  clonePalette,
  cloneScheme,
  defaultStoredTheme,
  fallbackPalette,
  normalizePalette,
  resolveDefaultSchemeId,
  schemeSwatches,
  schemeText,
  type InjectedTheme,
  type StoredTheme,
  type ThemeAppearance,
  type ThemeMode,
  type ThemePalette,
  type ThemeScheme,
} from './registry.ts';
import { applyPalette } from './palette.ts';
import { readInjectedTheme, readLegacyLocalTheme, saveDeploymentTheme } from './storage.ts';
import { S } from './strings.ts';

/** 方案的元信息（不含调色板本身）。 */
export interface ThemeSchemeInfo {
  id: string;
  name: string;
  note: string;
  builtin: boolean;
  custom: boolean;
}

/** 方案卡：元信息 + 一条四格色带。 */
export interface ThemeSchemeCard extends ThemeSchemeInfo {
  swatches: string[];
}

export interface ThemeSnapshot {
  selectedId: string;
  /** 用户选的挡位（可能是 `system`） */
  mode: ThemeMode;
  /** 解析之后真正生效的明暗 */
  appearance: ThemeAppearance;
  scheme: ThemeSchemeInfo;
  schemes: ThemeSchemeCard[];
  /** 当前生效的调色板；预览期间是那份草稿。 */
  palette: ThemePalette;
  /** 最近一次回写部署的失败原因；成功后为 null。当前选择在本页仍然生效。 */
  saveError: string | null;
}

export interface ThemeChange {
  readonly snapshot: ThemeSnapshot;
  /** 是否为未保存的预览变化；订阅者可据此决定是否重绘。 */
  readonly preview: boolean;
}

export type ThemeChangeListener = (change: ThemeChange) => void;

/** `matchMedia('(prefers-color-scheme: dark)')` 的最小面。 */
export interface MediaQueryLike {
  readonly matches: boolean;
  addEventListener(type: 'change', listener: () => void): void;
  removeEventListener(type: 'change', listener: () => void): void;
}

export interface ThemeStudioDeps {
  doc: Document;
  /** 不给则读服务端注入的那段 JSON。 */
  injected?: InjectedTheme;
  /** 部署没有记录时可迁移的本机旧记录；不给则读 localStorage。 */
  legacy?: StoredTheme | null;
  /** 回写部署的主题记录；不给则 POST `/api/theme`。 */
  save?(state: StoredTheme): Promise<void>;
  /** 不给则取 `doc.defaultView.matchMedia(...)`；显式给 `null` = 系统挡位当浅色。 */
  media?: MediaQueryLike | null;
  /** 订阅方回调里抛的错落这儿。默认吞掉——一张图重画失败不该拖垮换肤本身。 */
  onError?(err: unknown): void;
}

/** 系统深色偏好。拿不到（老浏览器、假文档）就是 `null`，一律当浅色。 */
function systemDarkQuery(doc: Document): MediaQueryLike | null {
  try {
    return doc.defaultView?.matchMedia('(prefers-color-scheme: dark)') ?? null;
  } catch {
    return null;
  }
}

export class ThemeStudio {
  private readonly doc: Document;
  private readonly save: (state: StoredTheme) => Promise<void>;
  private readonly media: MediaQueryLike | null;
  private readonly onError: (err: unknown) => void;
  /** 记录里没有可用选择时选哪个方案；删掉自定义方案后也回到它。 */
  private readonly defaultSchemeId: string;
  private readonly listeners = new Set<ThemeChangeListener>();
  private state: StoredTheme;
  private previewPalette: ThemePalette | null = null;
  private saveError: string | null = null;
  private closed = false;

  /** 系统挡位下跟着系统走。方法引用存下来，`dispose()` 才摘得掉。 */
  private readonly onMediaChange = (): void => {
    if (this.state.mode === 'system') this.apply();
  };

  constructor(deps: ThemeStudioDeps) {
    this.doc = deps.doc;
    this.save = deps.save ?? saveDeploymentTheme;
    this.media = deps.media === undefined ? systemDarkQuery(deps.doc) : deps.media;
    this.onError = deps.onError ?? ((): void => {});
    const injected = deps.injected ?? readInjectedTheme(deps.doc);
    this.defaultSchemeId = resolveDefaultSchemeId(injected.defaultScheme);
    if (injected.theme) {
      this.state = injected.theme;
    } else {
      // 部署还没有记录:把这台机器上的旧记录交上去,此后它归部署。
      const legacy = deps.legacy === undefined ? readLegacyLocalTheme(deps.doc) : deps.legacy;
      this.state = legacy ?? { ...defaultStoredTheme(), selectedId: this.defaultSchemeId };
      if (legacy) this.persist();
    }
    this.media?.addEventListener('change', this.onMediaChange);
  }

  // ── 读 ──────────────────────────────────────────────────────────────

  /** 内置在前、自定义在后。每次现算，调用方拿到的是副本。 */
  schemes(): ThemeScheme[] {
    return [...builtinSchemes(), ...this.state.custom.map((s) => ({ ...cloneScheme(s), custom: true }))];
  }

  /** 当前方案。记录指向的 id 不存在（方案在别处被删了）就退回部署默认方案。 */
  currentScheme(): ThemeScheme {
    const all = this.schemes();
    return all.find((s) => s.id === this.state.selectedId)
      ?? all.find((s) => s.id === this.defaultSchemeId)
      ?? all[0];
  }

  get appearance(): ThemeAppearance {
    if (this.state.mode !== 'system') return this.state.mode;
    return this.media?.matches ? 'dark' : 'light';
  }

  get mode(): ThemeMode {
    return this.state.mode;
  }

  snapshot(): ThemeSnapshot {
    const scheme = this.currentScheme();
    const appearance = this.appearance;
    return {
      selectedId: scheme.id,
      mode: this.state.mode,
      appearance,
      scheme: info(scheme),
      schemes: this.schemes().map((item) => ({ ...info(item), swatches: schemeSwatches(item, appearance) })),
      palette: clonePalette(this.previewPalette ?? scheme.palettes[appearance]),
      saveError: this.saveError,
    };
  }

  // ── 写 ──────────────────────────────────────────────────────────────

  /** 应用保存的选择；首屏传 notify=false，不发变化通知。 */
  apply(notify = true): void {
    this.previewPalette = null;
    const scheme = this.currentScheme();
    // 选中的方案没了（记录里指向一个已删的自定义方案）→ 把纠正结果落回部署
    if (scheme.id !== this.state.selectedId) {
      this.state.selectedId = scheme.id;
      this.persist();
    }
    const appearance = this.appearance;
    applyPalette(
      this.doc,
      normalizePalette(scheme.palettes[appearance], fallbackPalette(appearance)),
      { appearance, schemeId: scheme.id },
    );
    if (notify) this.emit(false);
  }

  select(id: string): boolean {
    if (!this.schemes().some((s) => s.id === id)) return false;
    this.state.selectedId = id;
    this.persist();
    this.apply();
    return true;
  }

  setMode(mode: ThemeMode): boolean {
    if (!THEME_MODES.includes(mode)) return false;
    this.state.mode = mode;
    this.persist();
    this.apply();
    return true;
  }

  /** 试色：刷到文档但**不回写部署**。离开这一页或调 `resetPreview()` 就没了。 */
  preview(palette: ThemePalette): void {
    const scheme = this.currentScheme();
    const appearance = this.appearance;
    this.previewPalette = normalizePalette(palette, scheme.palettes[appearance]);
    applyPalette(this.doc, this.previewPalette, { appearance, schemeId: scheme.id });
    this.emit(true);
  }

  resetPreview(): void {
    this.apply();
  }

  /**
   * 另存为新的自定义方案并切过去。
   *
   * **只覆盖当前明暗变体**，另一半从源方案原样拷过来：用户在浅色下调完色，黑夜
   * 变体不该跟着变成一份浅色配色的暗抄本。
   */
  saveAs(name: string | null | undefined, palette: ThemePalette): string {
    const source = this.currentScheme();
    const appearance = this.appearance;
    const copy: ThemeScheme = {
      id: `custom-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
      name: String(name ?? '').trim().slice(0, 40) || S.copyOf(source.name),
      note: S.customNote,
      palettes: cloneScheme(source).palettes,
      custom: true,
    };
    copy.palettes[appearance] = normalizePalette(palette, source.palettes[appearance]);
    this.state.custom.push(copy);
    this.state.selectedId = copy.id;
    this.persist();
    this.apply();
    return copy.id;
  }

  /** 覆盖当前自定义方案。选中的是内置方案时返回 `false`（内置不可写）。 */
  saveCurrent(name: string | null | undefined, palette: ThemePalette): boolean {
    const scheme = this.state.custom.find((s) => s.id === this.state.selectedId);
    if (!scheme) return false;
    const appearance = this.appearance;
    scheme.name = String(name ?? '').trim().slice(0, 40) || scheme.name;
    scheme.palettes[appearance] = normalizePalette(palette, scheme.palettes[appearance]);
    this.persist();
    this.apply();
    return true;
  }

  /** 删掉当前自定义方案并切回默认方案。选中内置方案时返回 `false`。 */
  removeCurrent(): boolean {
    const before = this.state.custom.length;
    this.state.custom = this.state.custom.filter((s) => s.id !== this.state.selectedId);
    if (this.state.custom.length === before) return false;
    this.state.selectedId = this.defaultSchemeId;
    this.persist();
    this.apply();
    return true;
  }

  // ── 订阅 ────────────────────────────────────────────────────────────

  /**
   * 订阅主题变化。返回的 `Disposable` 一 `dispose()` 就退订——页面把它交给自己的
   * `lifecycle` 即可，不必记得在卸载时手动摘。
   *
   * 重复登记同一个函数只算一次（`Set` 语义）；回调里再登记/退订不影响本轮派发。
   */
  onChange(listener: ThemeChangeListener): Disposable {
    this.listeners.add(listener);
    return toDisposable(() => {
      this.listeners.delete(listener);
    });
  }

  /** 摘掉系统深色监听并清空订阅。进程级实例通常活到页面关闭，测试与热重载用。 */
  dispose(): void {
    if (this.closed) return;
    this.closed = true;
    this.media?.removeEventListener('change', this.onMediaChange);
    this.listeners.clear();
  }

  /** 回写部署。失败记在快照里,由外观页呈现;当前选择在本页仍然生效。 */
  private persist(): void {
    const sending = JSON.parse(JSON.stringify(this.state)) as StoredTheme;
    void this.save(sending).then(
      () => {
        if (this.saveError === null) return;
        this.saveError = null;
        this.emit(false);
      },
      (err: unknown) => {
        this.saveError = err instanceof Error ? err.message : String(err);
        this.emit(false);
      },
    );
  }

  /** 逐个通知订阅者；单个回调失败不阻止其他回调。 */
  private emit(preview: boolean): void {
    if (this.listeners.size === 0) return;
    const change: ThemeChange = { snapshot: this.snapshot(), preview };
    for (const listener of [...this.listeners]) {
      try {
        listener(change);
      } catch (err) {
        this.onError(err);
      }
    }
  }
}

function info(scheme: ThemeScheme): ThemeSchemeInfo {
  const text = schemeText(scheme);
  return {
    id: scheme.id,
    name: text.name,
    note: text.note,
    builtin: !!scheme.builtin,
    custom: !!scheme.custom,
  };
}

// ---------------------------------------------------------------------------
// 进程级实例
// ---------------------------------------------------------------------------

let shared: ThemeStudio | null = null;

/**
 * 取（必要时新建）那个唯一的实例。
 *
 * `deps` 只在**第一次**（真正新建的那次）生效；之后再传会被忽略，因为半路换回写
 * 目标或换文档只会让两份状态对不上。测试要换一套 deps，先 `disposeThemeStudio()`。
 */
export function getThemeStudio(deps?: Partial<ThemeStudioDeps>): ThemeStudio {
  if (shared) return shared;
  const doc = deps?.doc ?? (typeof document === 'undefined' ? null : document);
  if (!doc) throw new Error('主题需要一个 Document');
  shared = new ThemeStudio({ ...deps, doc });
  return shared;
}

/**
 * **首屏第一件事**：读服务端注入的部署主题记录、把颜色刷到 `documentElement`。
 *
 * 同步执行、不等任何路由，所以内核入口可以在第一行直接调它。部署还没有记录且这台
 * 机器存过旧记录时，构造函数会把旧记录回写一次。
 * 返回当前快照（想据此做点别的判断时用），不需要就丢掉。
 */
export function applyStoredTheme(
  doc?: Document,
  deps?: Omit<Partial<ThemeStudioDeps>, 'doc'>,
): ThemeSnapshot {
  const studio = getThemeStudio(doc ? { ...deps, doc } : deps);
  studio.apply(false);
  return studio.snapshot();
}

/** 丢掉进程级实例（测试与热重载）。生产代码里没有它的用处。 */
export function disposeThemeStudio(): void {
  shared?.dispose();
  shared = null;
}
