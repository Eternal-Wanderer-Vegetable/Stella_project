/** 轮次和工具调用边界设置日志关联字段；Logger 写入时从异步作用域读取。 */
import { AsyncLocalStorage } from 'node:async_hooks';

export interface LogAnchors {
  /** session 声明 id。 */
  sess?: string;
  /** 主循环轮次,进程内单调 */
  round?: number;
  /** 本轮的 response id */
  resp?: string;
  /** 正在执行的 tool_call id */
  call?: string;
  /** 事件游标 */
  ev?: number;
  /** World 任务号 */
  task?: number;
}

const storage = new AsyncLocalStorage<LogAnchors>();

/** 在 fn 及其派生的异步操作中合并关联字段；新字段覆盖同名继承值。 */
export function withAnchors<T>(anchors: LogAnchors, fn: () => T): T {
  return storage.run({ ...storage.getStore(), ...anchors }, fn);
}

/** 修改最近一次 withAnchors 建立的作用域；没有作用域时不修改。 */
export function setAnchors(patch: LogAnchors): void {
  const current = storage.getStore();
  if (!current) return;
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) delete (current as Record<string, unknown>)[key];
    else (current as Record<string, unknown>)[key] = value;
  }
}

export function currentAnchors(): LogAnchors {
  return storage.getStore() ?? {};
}
