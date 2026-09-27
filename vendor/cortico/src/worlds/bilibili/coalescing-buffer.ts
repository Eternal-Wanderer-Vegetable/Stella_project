export interface CoalescingGroup<T> {
  key: string;
  items: readonly T[];
}

interface CoalescingBufferState {
  inputs: number;
  outputs: number;
  collapsed: number;
  flushes: number;
  capacityFlushes: number;
  pendingItems: number;
  pendingGroups: number;
}

interface PendingGroup<T> {
  key: string;
  items: T[];
}

/**
 * 固定窗按各组首件到达顺序输出。窗口不续期；run scope 只合并该事件流的当前连续段。
 */
export class CoalescingBuffer<T> {
  private readonly emit: (groups: readonly CoalescingGroup<T>[]) => void;
  private groups: PendingGroup<T>[] = [];
  private sameKeyGroups = new Map<string, PendingGroup<T>>();
  private runGroups = new Map<string, PendingGroup<T>>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private pendingItems = 0;
  private inputs = 0;
  private outputs = 0;
  private flushes = 0;
  private capacityFlushes = 0;

  constructor(emit: (groups: readonly CoalescingGroup<T>[]) => void) {
    this.emit = emit;
  }

  add(key: string, item: T, opts: {
    windowMs: number;
    maxItems: number;
    /** 只与该事件流中紧邻的同 key 项归并；其他 scope 的事件不打断连续段。 */
    runScope?: string;
  }): void {
    const first = this.pendingItems === 0;
    let group: PendingGroup<T> | undefined;
    if (opts.runScope) {
      const active = this.runGroups.get(opts.runScope);
      if (active?.key === key) group = active;
      else {
        group = { key, items: [] };
        this.groups.push(group);
        this.runGroups.set(opts.runScope, group);
      }
    } else {
      group = this.sameKeyGroups.get(key);
      if (!group) {
        group = { key, items: [] };
        this.groups.push(group);
        this.sameKeyGroups.set(key, group);
      }
    }
    group.items.push(item);
    this.pendingItems += 1;
    this.inputs += 1;

    if (this.pendingItems >= opts.maxItems) {
      this.flush('capacity');
      return;
    }
    if (!first) return;
    if (opts.windowMs === 0) {
      this.flush('window');
      return;
    }
    this.timer = setTimeout(() => this.flush('window'), opts.windowMs);
  }

  flush(reason: 'window' | 'capacity' | 'barrier' | 'stop' = 'barrier'): void {
    if (this.pendingItems === 0) return;
    if (this.timer) clearTimeout(this.timer);
    const groups = this.groups;
    const outputCount = groups.length;
    this.groups = [];
    this.sameKeyGroups = new Map();
    this.runGroups = new Map();
    this.timer = null;
    this.pendingItems = 0;
    this.outputs += outputCount;
    this.flushes += 1;
    if (reason === 'capacity') this.capacityFlushes += 1;
    this.emit(groups);
  }

  /** 结束指定事件流的当前连续段；既有组仍等待原窗口冲刷。 */
  breakRun(scope: string): void {
    this.runGroups.delete(scope);
  }

  reset(): void {
    if (this.timer) clearTimeout(this.timer);
    this.groups = [];
    this.sameKeyGroups = new Map();
    this.runGroups = new Map();
    this.timer = null;
    this.pendingItems = 0;
    this.inputs = 0;
    this.outputs = 0;
    this.flushes = 0;
    this.capacityFlushes = 0;
  }

  state(): CoalescingBufferState {
    return {
      inputs: this.inputs,
      outputs: this.outputs,
      collapsed: this.inputs - this.outputs - this.groups.length,
      flushes: this.flushes,
      capacityFlushes: this.capacityFlushes,
      pendingItems: this.pendingItems,
      pendingGroups: this.groups.length,
    };
  }
}
