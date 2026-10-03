import { clearToken, getToken } from './http';

/** 401 未授权（与 Axios 拦截器同一处理后的标记错误）：调用方据此停止重连。 */
export class SseAuthError extends Error {
  constructor() {
    super('SSE 连接未授权（401）');
    this.name = 'SseAuthError';
  }
}

/**
 * SSE-over-fetch：EventSource 带不了 Authorization 头，改用 fetch 流解析。
 * 帧协议见 webui/services/logs.py（id: 字节偏移 / data: JSON / : 心跳）。
 * 返回 Last-Event-ID 的维护交给调用方（onMessage 收到的 id 存起来即可）。
 */
export async function sseStream(
  url: string,
  onMessage: (id: string, data: string) => void,
  opts: { signal?: AbortSignal; lastEventId?: string; method?: string; body?: string } = {},
): Promise<void> {
  const headers: Record<string, string> = { Accept: 'text/event-stream' };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.lastEventId) headers['Last-Event-ID'] = opts.lastEventId;
  if (opts.body) headers['Content-Type'] = 'application/json';

  const resp = await fetch(url, {
    method: opts.method ?? 'GET',
    body: opts.body,
    headers,
    signal: opts.signal,
  });
  if (resp.status === 401) {
    // O09：SSE 收到 401 走与 Axios 拦截器（http.ts）完全相同的处理——
    // 清登录态并回登录页；调用方凭 SseAuthError 停止重连。
    clearToken();
    if (typeof window !== 'undefined' && !window.location.hash.startsWith('#/auth/login')) {
      window.location.hash = '/auth/login';
    }
    throw new SseAuthError();
  }
  if (!resp.ok || !resp.body) {
    throw new Error(`SSE 连接失败（${resp.status}）`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let id = '';
      const datas: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith('id:')) id = line.slice(3).trim();
        else if (line.startsWith('data:')) datas.push(line.slice(5).trim());
        // ': ' 开头是心跳注释，忽略
      }
      if (datas.length > 0) onMessage(id, datas.join('\n'));
    }
  }
}
