<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import {
  applyApiKey,
  applyCustomEndpoint,
  artifactDownloadUrl,
  cancelTask,
  getAuthStatus,
  getDeviceLogin,
  getHealth,
  getTask,
  getResult,
  listBackends,
  listEvents,
  listTasks,
  logoutBackend,
  migrateLegacyAuth,
  respondInput,
  startDeviceLogin,
  submitTask,
  testAuthEndpoint,
  type CometaAuthStatus,
  type CometaDeviceLogin,
  type CometaEvent,
  type CometaResult,
  type CometaTask,
} from '@/api/cometa';
import { toastApiError, useToast } from '@/stores/toast';

// cometa 外部 Agent 任务页（design_docs/Cometa 外部 Agent 任务运行层实施方案
// v1.0 §6.14）：任务列表 / 阶段 / 等待问题 / 结果 / 产物下载；提交、取消、
// 补充输入与审批。轮询 5s —— SSE 走 /events 游标补读，这里的间隔轮询是
// 防断线的兜底，两者共用同一份数据真源（任务库）。
interface Backend { backend_id: string; type: string; capabilities: string[] }

const tasks = ref<CometaTask[]>([]);
const backends = ref<Backend[]>([]);
const selected = ref<CometaTask | null>(null);
const detailEvents = ref<CometaEvent[]>([]);
const detailResult = ref<CometaResult | null>(null);
const objective = ref('');
const answer = ref('');
const busy = ref(false);
const disabled = ref(false); // COMETA_ENABLED=false / runtime 未装配（health=disabled）
const pollTimer = ref<number | null>(null);
const toast = useToast();

const ACTIVE_STATES = new Set([
  'queued', 'starting', 'running', 'waiting_input', 'waiting_approval', 'cancelling', 'recovering',
]);

const stateColor = (s: string): string =>
  s === 'succeeded' ? 'success'
  : s === 'failed' || s === 'timed_out' ? 'error'
  : s === 'cancelled' ? 'default'
  : s.startsWith('waiting') || s === 'recovery_required' ? 'warning'
  : 'info';

const stateLabel = (s: string): string =>
  ({
    queued: '排队中', starting: '启动中', running: '执行中',
    waiting_input: '等待补充', waiting_approval: '等待审批',
    cancelling: '取消中', cancelled: '已取消', succeeded: '已完成',
    partial: '部分完成', failed: '失败', timed_out: '超时',
    recovering: '核对中', recovery_required: '需管理员处理',
  })[s] ?? s;

const canSubmit = computed(() => objective.value.trim().length >= 8);

async function load(): Promise<void> {
  try {
    tasks.value = (await listTasks()).tasks;
    if (selected.value) {
      const found = tasks.value.find((t) => t.task_id === selected.value?.task_id);
      if (found) await openDetail(found, false);
    }
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function loadBackends(): Promise<void> {
  try {
    backends.value = (await listBackends()).backends;
    // 默认选中第一个 codex 型后端并拉取认证状态（认证卡片用）
    if (!authBackendId.value && codexBackends.value.length) {
      selectAuthBackend(codexBackends.value[0].backend_id);
    }
  } catch {
    backends.value = [];  // 未启用时入口本身隐藏；这里静默
  }
}

async function openDetail(task: CometaTask, reset: boolean): Promise<void> {
  selected.value = task;
  if (reset) {
    detailEvents.value = [];
    detailResult.value = null;
    answer.value = '';
  }
  try {
    const [full, eventsPage] = await Promise.all([getTask(task.task_id), listEvents(task.task_id)]);
    selected.value = full;
    detailEvents.value = eventsPage.events.slice(-30).reverse();
    if (!ACTIVE_STATES.has(full.state)) {
      detailResult.value = await getResult(task.task_id).catch(() => null);
    }
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function submit(): Promise<void> {
  if (!canSubmit.value || busy.value) return;
  busy.value = true;
  try {
    const key = `webui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const created = await submitTask({
      objective: objective.value.trim(),
      idempotency_key: key,
      request_id: key,
    });
    objective.value = '';
    toast.info(`已受理任务 ${created.task_id.slice(0, 8)}`);
    await load();
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    busy.value = false;
  }
}

async function cancel(task: CometaTask): Promise<void> {
  try {
    const res = await cancelTask(task.task_id, `webui-cancel-${task.task_id}`);
    toast.info(res.state === 'cancelled' ? '任务已取消' : '已请求取消，确认停止后回报');
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function answerWaiting(): Promise<void> {
  const task = selected.value;
  if (!task?.waiting_request_id || !answer.value.trim()) return;
  try {
    await respondInput(
      task.task_id,
      task.waiting_request_id,
      answer.value.trim(),
      task.waiting_revision ?? 1,
    );
    answer.value = '';
    toast.info('已转交任务');
    await openDetail(task, false);
  } catch (err) {
    toastApiError(toast, err);
  }
}

onMounted(async () => {
  try {
    const health = await getHealth();
    if (health.state === 'disabled') {
      // 未启用不是错误：优雅提示而不是弹 503 toast
      disabled.value = true;
      return;
    }
  } catch {
    disabled.value = true; // 503：runtime 未装配
    return;
  }
  void load();
  void loadBackends();
  pollTimer.value = window.setInterval(() => void load(), 5000);
});

onBeforeUnmount(() => {
  if (pollTimer.value !== null) window.clearInterval(pollTimer.value);
  if (deviceTimer.value !== null) window.clearInterval(deviceTimer.value);
});

// ── 后端认证（codex 双路线；与 providers 页同款纪律，但免重启）────────
// 三条路线：ChatGPT 设备码登录 / OpenAI API key / 自定义 OpenAI 兼容端点
// （须支持 Responses API——codex 0.159.2 已移除 chat wire API）。

const codexBackends = computed(() => backends.value.filter((b) => b.type === 'codex'));
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
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">外部 Agent 任务</h1>
      <v-spacer />
      <v-btn variant="text" @click="load">刷新</v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      跨轮次委派外部 Agent（Codex 等）：受理后立即返回，进度与结果在任务中心可查；
      等待输入的任务会在这里提问。与群内「委派 / 任务状态 / 取消任务」指令共用同一套服务。
    </p>

    <v-alert
      v-if="disabled"
      type="info"
      variant="tonal"
      class="mb-4"
      text="cometa 未启用（COMETA_ENABLED=false 或 runtime 未装配）。在 .env 打开开关、配置 StellaData/config/cometa.toml 并重启后，这里即可提交任务、配置后端认证与跟踪外部 Agent 任务。"
    />

    <v-card v-if="!disabled && codexBackends.length" class="pa-4 mb-4">
      <div class="d-flex align-center mb-2">
        <div class="text-subtitle-1 font-weight-medium">后端认证（Codex）</div>
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

    <v-card v-if="!disabled" class="pa-4 mb-4">
      <div class="d-flex ga-2 align-center">
        <v-text-field
          v-model="objective"
          label="委派目标（至少 8 个字符）"
          density="compact"
          hide-details
          @keyup.enter="submit"
        />
        <v-chip v-if="backends.length" size="small" variant="tonal">
          后端 {{ backends.map((b) => b.backend_id).join('、') }}
        </v-chip>
        <v-btn color="primary" :disabled="!canSubmit || busy" :loading="busy" @click="submit">
          委派
        </v-btn>
      </div>
    </v-card>

    <v-card v-if="!disabled" class="pa-2">
      <v-table v-if="tasks.length">
        <thead>
          <tr><th>短 ID</th><th>状态</th><th>阶段</th><th>最近活动</th><th>投递</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id" :class="{ 'bg-surface-light': selected?.task_id === t.task_id }">
            <td><code class="text-caption">{{ t.short_id }}</code></td>
            <td><v-chip size="x-small" :color="stateColor(t.state)" variant="tonal">{{ stateLabel(t.state) }}</v-chip></td>
            <td class="text-caption">{{ t.phase || '—' }}</td>
            <td class="text-caption">{{ t.last_activity_at ? new Date(t.last_activity_at).toLocaleString() : '—' }}</td>
            <td class="text-caption">{{ t.delivery_state || '—' }}</td>
            <td class="d-flex ga-1">
              <v-btn size="x-small" variant="text" @click="openDetail(t, true)">详情</v-btn>
              <v-btn
                v-if="ACTIVE_STATES.has(t.state)"
                size="x-small"
                variant="text"
                color="error"
                @click="cancel(t)"
              >取消</v-btn>
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis pa-4">
        没有任务。
      </div>
    </v-card>

    <v-dialog :model-value="selected !== null" width="680" @update:model-value="selected = null">
      <v-card v-if="selected">
        <v-card-title>
          任务 {{ selected.short_id }}
          <v-chip size="x-small" class="ml-2" :color="stateColor(selected.state)" variant="tonal">
            {{ stateLabel(selected.state) }}
          </v-chip>
        </v-card-title>
        <v-card-text>
          <div v-if="selected.waiting_request_id" class="mb-3">
            <div class="text-body-2 font-weight-medium mb-1">
              任务提问（{{ selected.waiting_kind === 'approval' ? '需要审批' : '需要补充信息' }}）：
            </div>
            <div class="text-body-2 mb-2">{{ selected.waiting_question || '（见任务详情）' }}</div>
            <div class="d-flex ga-2">
              <v-text-field v-model="answer" label="答复内容" density="compact" hide-details />
              <v-btn color="primary" :disabled="!answer.trim()" @click="answerWaiting">提交</v-btn>
            </div>
          </div>

          <div v-if="detailResult" class="mb-3">
            <div class="text-subtitle-2">结果（{{ detailResult.outcome }} / 验证 {{ detailResult.verification_status }}）</div>
            <div class="text-body-2" style="white-space: pre-wrap">{{ detailResult.summary }}</div>
            <div v-if="detailResult.artifacts.length" class="mt-2">
              <div class="text-caption text-medium-emphasis">产物</div>
              <v-btn
                v-for="a in detailResult.artifacts"
                :key="a.artifact_id"
                size="small"
                variant="tonal"
                class="mr-1"
                :href="artifactDownloadUrl(selected.task_id, a.artifact_id)"
                target="_blank"
              >{{ a.display_name }}（{{ a.size }} 字节）</v-btn>
            </div>
            <div v-if="detailResult.limitations.length" class="text-caption text-warning mt-1">
              限制：{{ detailResult.limitations.join('；') }}
            </div>
          </div>

          <div class="text-subtitle-2 mb-1">事件（最近 30 条）</div>
          <v-list density="compact" max-height="260">
            <v-list-item v-for="e in detailEvents" :key="e.sequence">
              <v-list-item-title class="text-body-2">{{ e.kind }}</v-list-item-title>
              <v-list-item-subtitle class="text-caption">
                #{{ e.sequence }} {{ e.occurred_at ? new Date(e.occurred_at).toLocaleTimeString() : '' }}
                {{ JSON.stringify(e.payload).slice(0, 120) }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn @click="selected = null">关闭</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
