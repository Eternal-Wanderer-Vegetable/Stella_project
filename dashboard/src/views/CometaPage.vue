<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import {
  artifactDownloadUrl,
  cancelTask,
  getHealth,
  getTask,
  getResult,
  listBackends,
  listEvents,
  listTasks,
  respondInput,
  submitTask,
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
});
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
      text="cometa 未启用（COMETA_ENABLED=false 或 runtime 未装配）。在 .env 打开开关、配置 StellaData/config/cometa.toml 并重启后，这里即可提交与跟踪外部 Agent 任务。"
    />

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
