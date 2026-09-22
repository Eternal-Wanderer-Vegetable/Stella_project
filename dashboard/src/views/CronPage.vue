<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

// 定时任务页（方案 §6.10）：群内指令与 WebUI 共用 SchedulingService 校验
interface Task {
  task_id: string; group_id: number; mode: string; objective: string;
  cron_expr: string; timezone: string; revision: number; status: string;
}

const tasks = ref<Task[]>([]);
const createDialog = ref(false);
const payload = ref({
  group_id: 0, mode: 'reminder', objective: '',
  cron_expr: '0 9 * * MON-FRI', timezone: 'Asia/Shanghai',
});
const history = ref<{ runs: { run_id: string; state: string; ts: string; note: string }[] } | null>(null);
const historyTask = ref('');
const audit = ref<{ entries: { ts: string; group_id: string; action: string; task_id: string; actor_id: number }[] } | null>(null);
const toast = useToast();

const CRON_TEMPLATES = [
  { label: '每天 9:00', value: '0 9 * * *' },
  { label: '工作日 9:00', value: '0 9 * * MON-FRI' },
  { label: '每 15 分钟', value: '*/15 * * * *' },
  { label: '每周一 9:00', value: '0 9 * * MON' },
];

async function load(): Promise<void> {
  try {
    tasks.value = (await unwrap<{ tasks: Task[] }>(api.get('/scheduling/tasks'))).tasks;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function create(): Promise<void> {
  try {
    await unwrap(api.post('/scheduling/tasks', payload.value));
    toast.success('任务已创建');
    createDialog.value = false;
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function action(task: Task, action: string): Promise<void> {
  try {
    // 乐观锁冲突时由前端重取修订后重试一次（与后端契约一致）
    await unwrap(api.post(`/scheduling/tasks/${task.task_id}/${action}`, {
      group_id: task.group_id, expected_revision: task.revision,
    }));
    toast.success(`已${action === 'run_now' ? '立即执行' : action === 'pause' ? '暂停' : action === 'resume' ? '恢复' : '取消'}`);
    await load();
  } catch (err) {
    toastApiError(toast, err);
    await load();
  }
}

async function showHistory(task: Task): Promise<void> {
  try {
    history.value = await unwrap(
      api.get(`/scheduling/tasks/${task.task_id}/history`, {
        params: { group_id: task.group_id },
      }),
    );
    historyTask.value = task.task_id;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function showAudit(): Promise<void> {
  try {
    audit.value = await unwrap(api.get('/scheduling/audit'));
  } catch (err) {
    toastApiError(toast, err);
  }
}

const statusColor = (s: string): string =>
  s === 'ACTIVE' ? 'success' : s === 'PAUSED' ? 'warning' : 'default';

onMounted(load);
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">定时任务</h1>
      <v-spacer />
      <v-btn variant="text" @click="showAudit">审计记录</v-btn>
      <v-btn color="primary" prepend-icon="mdi-plus" @click="createDialog = true">新建任务</v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      与群内「定时」指令共用同一套校验：群内配额、主动发言闸门、审计全部照常。
    </p>

    <v-card class="pa-2">
      <v-table v-if="tasks.length">
        <thead>
          <tr><th>群</th><th>类型</th><th>内容</th><th>Cron</th><th>时区</th><th>状态</th><th>修订</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in tasks" :key="t.task_id">
            <td>{{ t.group_id }}</td>
            <td><v-chip size="x-small" variant="tonal" :color="t.mode === 'agent' ? 'secondary' : 'primary'">{{ t.mode }}</v-chip></td>
            <td class="text-body-2">{{ t.objective.slice(0, 40) }}</td>
            <td><code class="text-caption">{{ t.cron_expr }}</code></td>
            <td class="text-caption">{{ t.timezone }}</td>
            <td><v-chip size="x-small" :color="statusColor(t.status)" variant="tonal">{{ t.status }}</v-chip></td>
            <td>{{ t.revision }}</td>
            <td class="d-flex ga-1">
              <v-btn size="x-small" variant="text" @click="showHistory(t)">历史</v-btn>
              <v-btn size="x-small" variant="text" @click="action(t, 'run_now')">立即</v-btn>
              <v-btn v-if="t.status === 'ACTIVE'" size="x-small" variant="text" @click="action(t, 'pause')">暂停</v-btn>
              <v-btn v-if="t.status === 'PAUSED'" size="x-small" variant="text" @click="action(t, 'resume')">恢复</v-btn>
              <v-btn size="x-small" variant="text" color="error" @click="action(t, 'cancel')">取消</v-btn>
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis pa-4">
        没有定时任务。
      </div>
    </v-card>

    <v-dialog
      :model-value="historyTask !== ''"
      width="560"
      @update:model-value="historyTask = ''"
    >
      <v-card>
        <v-card-title>运行历史</v-card-title>
        <v-card-text>
          <v-list density="compact">
            <v-list-item v-for="r in history?.runs ?? []" :key="r.run_id">
              <v-list-item-title class="text-body-2">{{ r.state }}</v-list-item-title>
              <v-list-item-subtitle>{{ r.ts }} {{ r.note }}</v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <div v-if="!history?.runs?.length" class="text-caption">还没有运行记录。</div>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn @click="historyTask = ''">关闭</v-btn></v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog
      :model-value="audit !== null"
      width="640"
      @update:model-value="audit = null"
    >
      <v-card>
        <v-card-title>审计记录</v-card-title>
        <v-card-text>
          <v-list density="compact">
            <v-list-item v-for="(e, i) in audit?.entries ?? []" :key="i">
              <v-list-item-title class="text-body-2">{{ e.action }} · 群 {{ e.group_id }}</v-list-item-title>
              <v-list-item-subtitle>{{ e.ts }} · 任务 {{ e.task_id.slice(0, 8) }} · 操作者 {{ e.actor_id }}</v-list-item-subtitle>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn @click="audit = null">关闭</v-btn></v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="createDialog" width="560">
      <v-card>
        <v-card-title>新建定时任务</v-card-title>
        <v-card-text>
          <div class="d-flex ga-2">
            <v-text-field v-model.number="payload.group_id" label="QQ 群号" density="compact" />
            <v-select v-model="payload.mode" :items="['reminder', 'agent']" label="类型" density="compact"
                      hint="agent 仅管理员，会消耗模型调用" persistent-hint style="max-width: 10rem" />
          </div>
          <v-text-field v-model="payload.objective" label="提醒内容 / 目标描述" density="compact" class="mt-2" />
          <div class="d-flex ga-2 align-center">
            <v-text-field v-model="payload.cron_expr" label="Cron（五段式）" density="compact" />
            <v-select
              v-model="payload.cron_expr" :items="CRON_TEMPLATES" item-title="label" item-value="value"
              label="模板" density="compact" hide-details style="max-width: 10rem"
            />
            <v-text-field v-model="payload.timezone" label="时区" density="compact" />
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDialog = false">取消</v-btn>
          <v-btn color="primary" @click="create">创建</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
