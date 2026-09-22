import axios, { type AxiosInstance } from 'axios';

// API 客户端：envelope 约定见 webui/responses.py（{status,message,data}）。
// 拦截器只管 HTTP 语义：附 Bearer、401 时清登录态回登录页（对齐 AstrBot
// http.ts 的行为，方案 §4 D4）。envelope 的 status 字段由页面自行检查。
const TOKEN_KEY = 'stella-token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  // 同步清空 Pinia 内存态：路由守卫的 loggedIn 读内存，只删 localStorage
  // 会让守卫在本次会话里仍视为已登录（动态 import 避免循环依赖）。
  void import('@/stores/auth').then(({ useAuthStore }) => {
    useAuthStore().evict();
  });
}

export const api: AxiosInstance = axios.create({ baseURL: '/api/v1' });

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const locale = localStorage.getItem('stella-locale');
  if (locale) config.headers['Accept-Language'] = locale;
  return config;
});

// 这类端点是鉴权入口本身，401 不应触发「踢回登录页」的连锁跳转
const AUTH_ENDPOINTS = ['/auth/login', '/auth/setup', '/auth/setup-status', '/auth/desktop-session'];

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const url: string = error.config?.url ?? '';
      const isAuthChallenge = AUTH_ENDPOINTS.some((p) => url.includes(p));
      if (!isAuthChallenge) {
        clearToken();
        if (!window.location.hash.startsWith('#/auth/login')) {
          window.location.hash = '/auth/login';
        }
      }
    }
    return Promise.reject(error);
  },
);

export interface Envelope<T = unknown> {
  status: 'ok' | 'error';
  message: string | null;
  data: T;
}

/** 取 envelope.data；status=error 时抛出 message（页面 catch 后直接 toast）。 */
export async function unwrap<T>(promise: Promise<{ data: Envelope<T> }>): Promise<T> {
  const resp = await promise;
  if (resp.data.status !== 'ok') {
    throw new Error(resp.data.message ?? '请求失败');
  }
  return resp.data.data;
}
