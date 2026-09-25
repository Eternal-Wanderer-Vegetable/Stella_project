<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

// 定时任务页（方案 §6.10）：群内指令与 WebUI 共用 SchedulingService 校验。
// 新建表单不暴露裸 Cron：星期 + 时间图形化选择，cron 表达式由前端生成
//（2026-09-25 用户要求：群号来自 .env 白名单、避免非法输入）。
interface Task {
  task_id: string; group_id: number; mode: string; objective: string;
  cron_expr: string; timezone: string; revision: number; status: string;
}
interface GroupItem { group_id: number; space: string }

const tasks = ref<Task[]>([]);
const groups = ref<GroupItem[]>([]);
const createDialog = ref(false);
const groupId = ref<number | null>(null);
const mode = ref('reminder');
const objective = ref('');
const selectedDays = ref<string[]>(['MON', 'TUE', 'WED', 'THU', 'FRI']);
const timeOfDay = ref('09:00');
const timezone = ref('Asia/Shanghai');
const history = ref<{ runs: { run_id: string; state: string; ts: string; note: string }[] } | null>(null);
const historyTask = ref('');
const audit = ref<{ entries: { ts: string; group_id: string; action: string; task_id: string; actor_id: number }[] } | null>(null);
const toast = useToast();

const WEEKDAYS = [
  { title: '一', value: 'MON' }, { title: '二', value: 'TUE' }, { title: '三', value: 'WED' },
  { title: '四', value: 'THU' }, { title: '五', value: 'FRI' }, { title: '六', value: 'SAT' },
  { title: '日', value: 'SUN' },
];
const WEEKDAY_ORDER = WEEKDAYS.map((d) => d.value);
const TIMEZONES = [
  'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Asia/Singapore', 'UTC',
  'Europe/London', 'Europe/Berlin', 'America/New_York', 'America/Los_Angeles',
];

// 快捷预设：点一下把星期 + 时间填好（不直接写 cron，杜绝非法表达式）
const PRESETS = [
  { label: '每天 9:00', days: WEEKDAY_ORDER, time: '09:00' },
  { label: '工作日 9:00', days: ['MON', 'TUE', 'WED', 'THU', 'FRI'], time: '09:00' },
  { label: '每周一 9:00', days: ['MON'], time: '09:00' },
  { label: '每天 22:30', days: WEEKDAY_ORDER, time: '22:30' },
];

const groupItems = computed(() =>
  groups.value.map((g) => ({
    value: g.group_id,
    title: `群 ${g.group_id}${g.space ? ` · ${g.space}` : ''}`,
  })),
);

// 由星期 + 时间生成五段式 cron。Cron 的顺序是「分 时」，而 timeOfDay 是
// 「HH:MM」——别被变量名顺序骗了（曾经生成过 22:30 → `22 30` 的颠倒表达式）。
const cronExpr = computed(() => {
  const [hh, mm] = timeOfDay.value.split(':');
  const minute = String(Number(mm ?? 0));
  const hour = String(Number(hh ?? 0));
  const days =
    selectedDays.value.length === 7
      ? '*'
      : WEEKDAY_ORDER.filter((d) => selectedDays.value.includes(d)).join(',');
  return `${minute} ${hour} * * ${days || '*'}`;
});

const canCreate = computed(
  () =>
    groupId.value !== null &&
    groupId.value !== 0 &&
    objective.value.trim().length > 0 &&
    selectedDays.value.length > 0 &&
    /^\d{1,2}:\d{2}$/.test(timeOfDay.value),
);

function applyPreset(preset: { days: string[]; time: string }): void {
  selectedDays.value = [...preset.days];
  timeOfDay.value = preset.time;
}

async function loadGroups(): Promise<void> {
  try {
    groups.value = (await unwrap<{ groups: GroupItem[] }>(api.get('/groups'))).groups;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function load(): Promise<void> {
  try {
    tasks.value = (await unwrap<{ tasks: Task[] }>(api.get('/scheduling/tasks'))).tasks;
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openCreate(): void {
  if (groups.value.length === 0) void loadGroups();
  if (groupId.value === null && groups.value.length) {
    groupId.value = groups.value[0].group_id;
  }
  createDialog.value = true;
}

async function create(): Promise<void> {
  try {
    await unwrap(api.post('/scheduling/tasks', {
      group_id: groupId.value,
      mode: mode.value,
      objective: objective.value.trim(),
      cron_expr: cronExpr.value,
      timezone: timezone.value,
    }));
    toast.success('任务已创建');
    createDialog.value = false;
    objective.value = '';
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

onMounted(() => {
  void load();
  void loadGroups();
});
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">定时任务</h1>
      <v-spacer />
      <v-btn variant="text" @click="showAudit">审计记录</v-btn>
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openCreate">新建任务</v-btn>
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

    <v-dialog v-model="createDialog" width="620">
      <v-card>
        <v-card-title>新建定时任务</v-card-title>
        <v-card-text>
          <div class="d-flex ga-3 align-start mt-2">
            <v-select
              v-model="groupId"
              :items="groupItems"
              label="QQ 群"
              density="compact"
              style="flex: 1"
            />
            <v-select
              v-model="mode"
              :items="['reminder', 'agent']"
              label="类型"
              density="compact"
              hide-details
              style="max-width: 9rem"
            />
            <v-tooltip location="top" :max-width="380">
              <template #activator="{ props: tip }">
                <v-icon
                  v-bind="tip"
                  icon="mdi-help-circle-outline"
                  size="x-small"
                  class="text-medium-emphasis stella-tip-icon mt-3"
                />
              </template>
              <span class="text-body-2">
                QQ 群来自 .env 白名单（群组页可维护）。类型：reminder 仅发提醒；
                agent 会唤醒模型按目标执行，仅管理员可触发且消耗模型调用。
              </span>
            </v-tooltip>
          </div>

          <v-text-field
            v-model="objective"
            label="提醒内容 / 目标描述"
            density="compact"
            class="mt-4"
            hide-details
          />

          <div class="text-caption text-medium-emphasis mt-4 mb-1">重复（星期几）</div>
          <v-btn-toggle
            v-model="selectedDays"
            multiple
            variant="outlined"
            density="comfortable"
            class="stella-day-toggle d-flex"
          >
            <v-btn v-for="d in WEEKDAYS" :key="d.value" :value="d.value" class="flex-grow-1">
              {{ d.title }}
            </v-btn>
          </v-btn-toggle>

          <div class="d-flex ga-3 align-center mt-4">
            <v-text-field
              v-model="timeOfDay"
              type="time"
              label="时间"
              density="compact"
              hide-details
              style="max-width: 10rem"
            />
            <v-select
              v-model="timezone"
              :items="TIMEZONES"
              label="时区"
              density="compact"
              hide-details
              style="max-width: 13rem"
            />
            <v-tooltip location="top" :max-width="380">
              <template #activator="{ props: tip }">
                <v-icon
                  v-bind="tip"
                  icon="mdi-help-circle-outline"
                  size="x-small"
                  class="text-medium-emphasis stella-tip-icon"
                />
              </template>
              <span class="text-body-2">时间与时区共同决定触发时刻；系统自动换算成 Cron 表达式，无需手写。</span>
            </v-tooltip>
          </div>

          <div class="d-flex align-center ga-2 mt-4 flex-wrap">
            <span class="text-caption text-medium-emphasis">快捷预设：</span>
            <v-chip
              v-for="preset in PRESETS"
              :key="preset.label"
              size="small"
              variant="outlined"
              @click="applyPreset(preset)"
            >
              {{ preset.label }}
            </v-chip>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDialog = false">取消</v-btn>
          <v-btn color="primary" :disabled="!canCreate" @click="create">创建</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
/* 选中的星期按钮用星芒金（Stella logo 同色）：金底 + 深板岩字，高对比 */
.stella-day-toggle :deep(.v-btn--active) {
  background-color: #e5ce9c !important;
  color: #171d24 !important;
}

.stella-day-toggle :deep(.v-btn--active:hover) {
  background-color: #eeddb2 !important;
}

.stella-tip-icon {
  cursor: help;
}
</style>
