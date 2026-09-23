<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';

// 追踪页（评审定案硬性交付）：决策轨迹流 + 单条消息回放（方案 §6.9）
// 轨迹流 = 记忆决策（memory_traces）+ 参与决策（participation_log）两个数据源。
interface TraceCounts {
  candidates: number;
  filtered: number;
  final: number;
  rejected: number;
  behavior: number;
}
interface TraceItem {
  id: number;
  ts: string;
  group_id: string;
  group_shared_space: string;
  user_id: string;
  message: string;
  mode: string;
  trigger: string;
  counts: TraceCounts;
  debug: boolean;
}
interface ParticipationItem {
  id: number;
  ts: string;
  group_id: string;
  final_score: number;
  mode: string;
  decision: string;
  reason_flags: string[];
  snapshot: Record<string, unknown>;
  relevance: number;
}
interface ResolvedMemory {
  id: string;
  type?: string;
  content?: string;
  user_id?: string;
  score?: number;
  missing?: boolean;
}
interface TraceDetail extends TraceItem {
  memories: {
    candidates: ResolvedMemory[];
    filtered: ResolvedMemory[];
    final: ResolvedMemory[];
    rejected: ResolvedMemory[];
    behavior: ResolvedMemory[];
  };
  score_map: Record<string, number>;
  prompt_snapshot: string;
  output: string;
}

const tab = ref<'memory' | 'participation'>('memory');
const group = ref<string | null>(null);
const groups = ref<{ group_id: string }[]>([]);
const traces = ref<TraceItem[]>([]);
const participations = ref<ParticipationItem[]>([]);
const auto = ref(true);
const error = ref('');
const replay = ref<TraceDetail | null>(null);
const replayLoading = ref(false);

let timer: number | null = null;

async function loadGroups(): Promise<void> {
  try {
    const data = await unwrap<{ groups: { group_id: string }[] }>(
      api.get('/conversations/groups'),
    );
    groups.value = data.groups;
  } catch {
    // 筛选下拉缺失不阻塞主数据
  }
}

async function load(): Promise<void> {
  error.value = '';
  const params = group.value ? { group_id: group.value } : {};
  try {
    if (tab.value === 'memory') {
      const data = await unwrap<{ items: TraceItem[] }>(
        api.get('/trace/memory', { params }),
      );
      traces.value = data.items;
    } else {
      const data = await unwrap<{ items: ParticipationItem[] }>(
        api.get('/trace/participation', { params }),
      );
      participations.value = data.items;
    }
  } catch (err) {
    error.value = (err as Error).message;
  }
}

function pickTab(value: 'memory' | 'participation'): void {
  tab.value = value;
  void load();
}

async function openReplay(item: TraceItem): Promise<void> {
  replayLoading.value = true;
  try {
    replay.value = await unwrap<TraceDetail>(api.get(`/trace/memory/${item.id}`));
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    replayLoading.value = false;
  }
}

const decisionColor = (decision: string): string => {
  switch (decision) {
    case 'ALLOW_LLM':
      return 'success';
    case 'CANDIDATE':
      return 'info';
    case 'OBSERVE':
      return 'warning';
    default:
      return 'default';
  }
};

onMounted(async () => {
  await loadGroups();
  await load();
  timer = window.setInterval(() => {
    if (auto.value) void load();
  }, 5000);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <div>
    <div class="d-flex align-center ga-3 mb-3 flex-wrap">
      <v-btn-toggle :model-value="tab" mandatory density="compact" @update:model-value="pickTab">
        <v-btn value="memory">记忆决策</v-btn>
        <v-btn value="participation">参与决策</v-btn>
      </v-btn-toggle>
      <v-select
        v-model="group"
        :items="groups"
        item-title="group_id"
        item-value="group_id"
        label="群（全部）"
        clearable
        density="compact"
        hide-details
        style="max-width: 12rem"
        @update:model-value="load"
      />
      <v-spacer />
      <v-checkbox v-model="auto" label="5s 自动刷新" density="compact" hide-details />
    </div>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <!-- 记忆决策轨迹流 -->
    <v-card v-if="tab === 'memory'" class="pa-2">
      <v-list density="compact">
        <v-list-item
          v-for="item in traces"
          :key="item.id"
          @click="openReplay(item)"
          class="trace-row"
        >
          <template #prepend>
            <v-chip size="x-small" variant="tonal" class="mr-2">
              {{ item.trigger || 'reply' }}
            </v-chip>
          </template>
          <v-list-item-title class="text-body-2">
            {{ item.message || '(空)' }}
          </v-list-item-title>
          <v-list-item-subtitle>
            {{ item.ts }} · 群 {{ item.group_id }} · 用户 {{ item.user_id }} ·
            采纳 {{ item.counts.final }} / 候选 {{ item.counts.candidates }} · 淘汰
            {{ item.counts.rejected }}
          </v-list-item-subtitle>
          <template #append>
            <v-icon icon="mdi-chevron-right" size="small" />
          </template>
        </v-list-item>
      </v-list>
      <div v-if="!traces.length" class="text-body-2 text-medium-emphasis pa-4">
        还没有决策轨迹。每次回复会在这里留下「为什么调用这些记忆、为什么不用那些」的完整记录。
      </div>
    </v-card>

    <!-- 参与决策流 -->
    <v-card v-else class="pa-2">
      <v-list density="compact">
        <v-list-item v-for="item in participations" :key="item.id">
          <template #prepend>
            <v-chip :color="decisionColor(item.decision)" size="x-small" variant="tonal" class="mr-2">
              {{ item.decision }}
            </v-chip>
          </template>
          <v-list-item-title class="text-body-2">
            得分 {{ Math.round(item.final_score) }} · 话题相关度 {{ item.relevance?.toFixed?.(2) }}
          </v-list-item-title>
          <v-list-item-subtitle>
            {{ item.ts }} · 群 {{ item.group_id }}
            <v-chip
              v-for="flag in item.reason_flags"
              :key="flag"
              size="x-small"
              variant="outlined"
              class="ml-1"
            >
              {{ flag }}
            </v-chip>
          </v-list-item-subtitle>
        </v-list-item>
      </v-list>
      <div v-if="!participations.length" class="text-body-2 text-medium-emphasis pa-4">
        还没有参与评分记录。「为什么这次没说话」的直接答案在这里。
      </div>
    </v-card>

    <!-- 单条消息回放抽屉 -->
    <v-navigation-drawer
      :model-value="replay !== null"
      location="right"
      width="520"
      temporary
      @update:model-value="replay = null"
    >
      <div v-if="replay" class="pa-4">
        <div class="d-flex align-center mb-2">
          <div class="text-h6">单条消息回放</div>
          <v-spacer />
          <v-btn icon="mdi-close" size="small" variant="text" @click="replay = null" />
        </div>
        <v-card variant="tonal" class="pa-3 mb-3">
          <div class="text-body-2">
            <b>用户输入</b>：{{ replay.message }}
          </div>
          <div class="text-caption text-medium-emphasis mt-1">
            {{ replay.ts }} · 触发 {{ replay.trigger }} · 模式 {{ replay.mode || '—' }} ·
            群 {{ replay.group_id }}（空间 {{ replay.group_shared_space || '—' }}）
          </div>
        </v-card>

        <div class="text-subtitle-2 mb-1">回复</div>
        <v-card variant="outlined" class="pa-3 mb-3 text-body-2">{{ replay.output || '(无)' }}</v-card>

        <div class="text-subtitle-2 mb-1">记忆链</div>
        <div
          v-for="section in [
            ['final', '最终采纳'],
            ['candidates', '候选'],
            ['filtered', '被过滤'],
            ['rejected', '被淘汰'],
            ['behavior', '行为约束'],
          ] as const"
          :key="section[0]"
          class="mb-2"
        >
          <div class="text-caption text-medium-emphasis">
            {{ section[1] }}（{{ replay.memories[section[0]].length }}）
          </div>
          <v-chip
            v-for="mem in replay.memories[section[0]]"
            :key="mem.id"
            size="x-small"
            :variant="mem.missing ? 'outlined' : 'tonal'"
            :color="section[0] === 'final' ? 'success' : section[0] === 'rejected' ? 'error' : undefined"
            class="ma-1"
            :title="mem.content ?? '数据库中已不存在该记忆'"
          >
            {{ mem.content ? mem.content.slice(0, 24) : mem.id }}
            <span v-if="mem.score !== undefined">· {{ mem.score.toFixed(2) }}</span>
          </v-chip>
          <span
            v-if="!replay.memories[section[0]].length"
            class="text-caption text-disabled"
          >
            无
          </span>
        </div>

        <v-expansion-panels class="mt-2">
          <v-expansion-panel title="完整 Prompt 快照">
            <v-expansion-panel-text>
              <pre class="prompt-pre">{{ replay.prompt_snapshot || '(空)' }}</pre>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
        <div class="text-caption text-disabled mt-3">
          Router 命中、工具调用与预算分配目前记录在 thought 日志（Markdown），暂不在回放中。
        </div>
      </div>
    </v-navigation-drawer>
  </div>
</template>

<style scoped>
.trace-row {
  cursor: pointer;
}
.prompt-pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.72rem;
  max-height: 300px;
  overflow-y: auto;
}
</style>
