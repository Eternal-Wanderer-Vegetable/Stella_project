import { defineStore } from 'pinia';

import { api, clearToken, getToken, setToken, unwrap } from '@/api/http';

export interface SessionData {
  token: string;
  expires_at: string;
  username: string;
}

type BackendState = 'unknown' | 'online' | 'offline';

export const useAuthStore = defineStore('auth', {
  state: () => ({
    // token 放响应式 state 而不是只读 localStorage：getter 依赖非响应式的
    // localStorage 时 computed 会缓存首值且永不失效——setup 成功后路由守卫
    // 仍看到「未登录」把人踢回登录页（M0 浏览器验收实测）。localStorage
    // 只做持久化镜像，真值在这里。
    token: getToken() ?? '',
    username: localStorage.getItem('stella-user') ?? '',
    setupRequired: false,
    backend: 'unknown' as BackendState,
  }),
  getters: {
    loggedIn: (state) => state.token.length > 0,
  },
  actions: {
    /** 探测后端是否可达 + 是否需要初始化。路由守卫的第一步。 */
    async probe(): Promise<BackendState> {
      try {
        const data = await unwrap<{ setup_required: boolean }>(
          api.get('/auth/setup-status', { timeout: 4000 }),
        );
        this.setupRequired = data.setup_required;
        this.backend = 'online';
      } catch {
        this.backend = 'offline';
      }
      return this.backend;
    },
    async login(username: string, password: string): Promise<void> {
      const data = await unwrap<SessionData>(
        api.post('/auth/login', { username, password }),
      );
      this._adopt(data);
    },
    async setup(username: string, password: string): Promise<void> {
      const data = await unwrap<SessionData>(
        api.post('/auth/setup', { username, password }),
      );
      this._adopt(data);
      this.setupRequired = false;
    },
    async logout(): Promise<void> {
      try {
        await api.post('/auth/logout');
      } catch {
        // 服务端 Cookie 清理失败不阻塞本地登出
      }
      clearToken();
      localStorage.removeItem('stella-user');
      this.token = '';
      this.username = '';
    },
    /** 401 拦截器清 localStorage 后同步内存态（见 api/http.ts）。 */
    evict(): void {
      this.token = '';
      this.username = '';
    },
    _adopt(data: SessionData): void {
      setToken(data.token);
      localStorage.setItem('stella-user', data.username);
      this.token = data.token;
      this.username = data.username;
    },
  },
});
