import { defineStore } from 'pinia';

export interface ToastItem {
  id: number;
  message: string;
  color: 'success' | 'error' | 'info' | 'warning';
}

let nextId = 1;

// 全局 toast 队列（对齐 AstrBot 的 toast store 范式）：App.vue 渲染唯一的
// v-snackbar，页面用 useToast().success/error(...) 反馈操作结果。
export const useToastStore = defineStore('toast', {
  state: () => ({
    items: [] as ToastItem[],
    current: null as ToastItem | null,
  }),
  actions: {
    push(message: string, color: ToastItem['color'] = 'info'): void {
      this.items.push({ id: nextId++, message, color });
      if (!this.current) this._next();
    },
    _next(): void {
      this.current = this.items.shift() ?? null;
    },
    done(): void {
      this.current = null;
      if (this.items.length) this._next();
    },
    success(message: string): void {
      this.push(message, 'success');
    },
    error(message: string): void {
      this.push(message, 'error');
    },
    info(message: string): void {
      this.push(message, 'info');
    },
    warning(message: string): void {
      this.push(message, 'warning');
    },
  },
});

export function useToast() {
  const store = useToastStore();
  return {
    success: (m: string) => store.success(m),
    error: (m: string) => store.error(m),
    info: (m: string) => store.info(m),
    warning: (m: string) => store.warning(m),
  };
}

/** axios 错误 → 可展示文案（envelope.message 优先，见 webui/responses.py）。 */
export function toastApiError(store: ReturnType<typeof useToast>, err: unknown): void {
  const maybe = err as { response?: { data?: { message?: string } }; message?: string };
  store.error(maybe?.response?.data?.message ?? maybe?.message ?? '请求失败');
}
