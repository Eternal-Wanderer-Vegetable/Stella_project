<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import {
  applyApiKey,
  applyCustomEndpoint,
  getAuthStatus,
  getDeviceLogin,
  listBackends,
  logoutBackend,
  migrateLegacyAuth,
  startDeviceLogin,
  testAuthEndpoint,
  type CometaAuthStatus,
  type CometaDeviceLogin,
  type CometaBackend,
} from '@/api/cometa';
import { toastApiError, useToast } from '@/stores/toast';

// Codex 后端认证卡片（提供商页 / 外部 Agent 页共用）。
// 三条路线：ChatGPT 设备码登录 / OpenAI API key / 自定义 OpenAI 兼容端点
// （须支持 Responses API——codex 0.159.2 已移除 chat wire API）。
// 与「端点与角色」的有意差异：认证即时生效、无需重启（托管 codex_home
// 由 probe/任务启动现读）。cometa 未启用（503）时整个卡片自动隐藏。
const emit = defineEmits<{ backends: [backends: CometaBackend[]] }>();

const toast = useToast();
const available = ref(true); // cometa 未启用/未装配 → 卡片整体隐藏
const codexBackends = ref<CometaBackend[]>([]);
const authBackendId = ref('');
const authStatus = ref<CometaAuthStatus | null>(null);
const authBusy = ref(false);
const apiKeyInput = ref('');
const customBase = ref('');
const customModel = ref('');
const customKey = ref('');
const customModels = ref<string[]>([]);
const deviceLogin = ref<CometaDeviceLogin | null>(null);
const deviceTimer = ref<number | null>(null);

const modeLabel = (m: string): string =>
  ({
    ready_custom: '自定义端点', ready_chatgpt: 'ChatGPT 已登录',
    ready_api_key: 'API Key 已登录', legacy: '检测到旧版登录', none: '未配置',
  })[m] ?? m;

const modeColor = (m: string): string =>
  m.startsWith('ready') ? 'success' : m === 'legacy' ? 'warning' : 'default';

async function loadAuthStatus(): Promise<void> {
  if (!authBackendId.value) return;
  try {
    authStatus.value = await getAuthStatus(authBackendId.value);
  } catch (err) {
    toastApiError(toast, err);
  }
}

function selectAuthBackend(id: string): void {
  authBackendId.value = id;
  deviceLogin.value = null;
  customModels.value = [];
  void loadAuthStatus();
}

async function applyKey(): Promise<void> {
  if (!authBackendId.value || authBusy.value || !apiKeyInput.value.trim()) return;
  authBusy.value = true;
  try {
    authStatus.value = await applyApiKey(authBackendId.value, apiKeyInput.value.trim());
    apiKeyInput.value = '';
    toast.info('API key 登录成功（即时生效，无需重启）');
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    authBusy.value = false;
  }
}

async function saveCustom(): Promise<void> {
  if (!authBackendId.value || authBusy.value) return;
  authBusy.value = true;
  try {
    authStatus.value = await applyCustomEndpoint(authBackendId.value, {
      base_url: customBase.value.trim(),
      api_key: customKey.value.trim(),
      model: customModel.value.trim(),
    });
    customKey.value = '';
    toast.info('自定义端点已保存（即时生效，无需重启）');
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    authBusy.value = false;
  }
}

async function testCustom(): Promise<void> {
  if (!authBackendId.value || !customBase.value.trim()) return;
  authBusy.value = true;
  try {
    const res = await testAuthEndpoint(authBackendId.value, {
      base_url: customBase.value.trim(),
      api_key: customKey.value.trim(),
    });
    if (res.error) {
      toast.error(`端点测试失败：${res.error}`);
    } else {
      customModels.value = res.models.slice(0, 12);
      if (res.models.length > 0 && !customModel.value.trim()) {
        customModel.value = res.models[0];
      }
      toast.info(`端点可达，${res.models.length} 个模型`);
    }
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    authBusy.value = false;
  }
}

function pollDevice(): void {
  const login = deviceLogin.value;
  if (!login || !authBackendId.value) return;
  void getDeviceLogin(authBackendId.value, login.session_id)
    .then((snap) => {
      deviceLogin.value = snap;
      if (snap.state === 'completed') {
        if (deviceTimer.value !== null) window.clearInterval(deviceTimer.value);
        deviceTimer.value = null;
        toast.info('ChatGPT 登录成功（即时生效，无需重启）');
        void loadAuthStatus();
      } else if (snap.state === 'failed') {
        if (deviceTimer.value !== null) window.clearInterval(deviceTimer.value);
        deviceTimer.value = null;
        toast.error(`登录失败：${snap.error || '未知原因'}`);
      }
    })
    .catch(() => {
      /* 单次轮询失败静默（网络抖动），下一周期重试 */
    });
}

async function startDevice(): Promise<void> {
  if (!authBackendId.value || authBusy.value) return;
  authBusy.value = true;
  try {
    deviceLogin.value = await startDeviceLogin(authBackendId.value);
    if (deviceTimer.value !== null) window.clearInterval(deviceTimer.value);
    deviceTimer.value = window.setInterval(pollDevice, 2000);
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    authBusy.value = false;
  }
}

async function migrateLegacy(): Promise<void> {
  if (!authBackendId.value || authBusy.value) return;
  authBusy.value = true;
  try {
    authStatus.value = await migrateLegacyAuth(authBackendId.value);
    toast.info('旧版认证已迁移（即时生效，无需重启）');
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    authBusy.value = false;
  }
}

async function doLogout(): Promise<void> {
  if (!authBackendId.value || authBusy.value) return;
  authBusy.value = true;
  try {
    authStatus.value = await logoutBackend(authBackendId.value);
    toast.info('已登出（自定义端点配置保留）');
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    authBusy.value = false;
  }
}

onMounted(async () => {
  try {
    const all = (await listBackends()).backends;
    codexBackends.value = all.filter((b) => b.type === 'codex');
    if (!codexBackends.value.length) {
      available.value = false; // 没有 codex 后端：卡片无意义，隐藏
      return;
    }
    authBackendId.value = codexBackends.value[0].backend_id;
    emit('backends', codexBackends.value);
    void loadAuthStatus();
  } catch {
    available.value = false; // 503：cometa 未启用——入口隐藏（既有约定）
  }
});

onBeforeUnmount(() => {
  if (deviceTimer.value !== null) window.clearInterval(deviceTimer.value);
});
</script>

<template>
  <v-card v-if="available && codexBackends.length" class="pa-4 mb-4">
    <div class="d-flex align-center mb-2">
      <div class="text-subtitle-1 font-weight-medium">外部 Agent（Codex）认证</div>
      <v-spacer />
      <v-select
        :model-value="authBackendId"
        :items="codexBackends.map((b) => ({ title: b.backend_id, value: b.backend_id }))"
        density="compact"
        hide-details
        style="max-width: 240px"
        @update:model-value="selectAuthBackend"
      />
      <v-chip
        v-if="authStatus"
        size="small"
        class="ml-2"
        :color="modeColor(authStatus.mode)"
        variant="tonal"
      >{{ modeLabel(authStatus.mode) }}</v-chip>
      <v-btn
        v-if="authStatus?.ready"
        size="small"
        variant="text"
        color="error"
        :disabled="authBusy"
        @click="doLogout"
      >登出</v-btn>
    </div>
    <div v-if="authStatus" class="text-caption text-medium-emphasis mb-2">
      {{ authStatus.reason }}
      <span v-if="authStatus.account?.type && authStatus.ready">｜账号类型：{{ authStatus.account.type }}</span>
      ｜认证即时生效，无需重启
    </div>

    <v-alert
      v-if="authStatus?.legacy_available && !authStatus?.ready"
      type="warning"
      variant="tonal"
      density="compact"
      class="mb-3"
    >
      <div class="d-flex align-center">
        <span>检测到旧版 Codex 登录（~/.codex）。任务需要把认证迁入托管目录。</span>
        <v-spacer />
        <v-btn size="small" variant="tonal" :loading="authBusy" @click="migrateLegacy">一键迁移</v-btn>
      </div>
    </v-alert>

    <v-row>
      <v-col cols="12" md="4">
        <div class="text-body-2 font-weight-medium mb-1">ChatGPT 账号登录（设备码）</div>
        <v-btn
          size="small"
          variant="tonal"
          :loading="authBusy"
          :disabled="!!deviceLogin && deviceLogin.state === 'pending'"
          @click="startDevice"
        >发起登录</v-btn>
        <div v-if="deviceLogin" class="mt-2">
          <div class="text-body-2">
            打开
            <a :href="deviceLogin.verification_url" target="_blank">{{ deviceLogin.verification_url }}</a>
            ，输入设备码：
          </div>
          <code class="text-h6">{{ deviceLogin.user_code }}</code>
          <div class="text-caption text-medium-emphasis">
            {{ deviceLogin.state === 'pending' ? '等待你在浏览器完成登录…' : deviceLogin.state === 'completed' ? '登录完成' : `失败：${deviceLogin.error}` }}
          </div>
        </div>
      </v-col>

      <v-col cols="12" md="4">
        <div class="text-body-2 font-weight-medium mb-1">OpenAI API Key</div>
        <v-text-field
          v-model="apiKeyInput"
          label="API Key"
          type="password"
          density="compact"
          hide-details
          class="mb-2"
        />
        <v-btn size="small" variant="tonal" :loading="authBusy" @click="applyKey">登录</v-btn>
        <div class="text-caption text-medium-emphasis mt-1">计费走 OpenAI 平台额度（非 ChatGPT 订阅）</div>
      </v-col>

      <v-col cols="12" md="4">
        <div class="text-body-2 font-weight-medium mb-1">自定义端点（OpenAI 兼容 / 中转）</div>
        <v-text-field v-model="customBase" label="Base URL" density="compact" hide-details class="mb-1" />
        <v-text-field v-model="customModel" label="模型名" density="compact" hide-details class="mb-1" />
        <v-text-field
          v-model="customKey"
          :label="authStatus?.has_custom_endpoint ? 'API Key（留空不变）' : 'API Key'"
          type="password"
          density="compact"
          hide-details
          class="mb-1"
        />
        <div class="d-flex ga-1 align-center">
          <v-btn size="small" variant="text" prepend-icon="mdi-lan" :loading="authBusy" @click="testCustom">测试</v-btn>
          <v-btn size="small" variant="tonal" :loading="authBusy" @click="saveCustom">保存</v-btn>
        </div>
        <div v-if="customModels.length" class="d-flex flex-wrap ga-1 mt-1">
          <v-chip v-for="m in customModels" :key="m" size="x-small" variant="tonal" @click="customModel = m">{{ m }}</v-chip>
        </div>
        <div class="text-caption text-medium-emphasis mt-1">端点须支持 OpenAI Responses API（codex 已弃用 chat 协议）</div>
      </v-col>
    </v-row>
  </v-card>
</template>
