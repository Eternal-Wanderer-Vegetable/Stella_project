<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';

import { sseStream } from '@/api/sse';

// 日志页：history 拉平 + SSE live tail（Last-Event-ID 续传，方案 §6.9/§8.3）
interface LogItem {
  ts?: string;
  level?: string;
  module?: string;
  message?: string;
  raw?: string;
}

const MAX_LINES = 2000;
const lines = ref<LogItem[]>([]);
const connected = ref(false);
const autoscroll = ref(true);
const levelFilter = ref<string | null>(null);
const search = ref('');
const listEl = ref<HTMLElement | null>(null);

let abort: AbortController | null = null;
let lastEventId = '';
let reconnectTimer: number | null = null;
const LEVELS = ['INFO', 'WARNING', 'ERROR', 'DEBUG'];

const visible = ref<LogItem[]>([]);

function recompute(): void {
  let items = lines.value;
  if (levelFilter.value) items = items.filter((i) => i.level === levelFilter.value);
  const kw = search.value.trim().toLowerCase();
  if (kw) {
    items = items.filter(
      (i) =>
        (i.message ?? '').toLowerCase().includes(kw) ||
        (i.module ?? '').toLowerCase().includes(kw),
    );
  }
  visible.value = items.slice(-MAX_LINES);
  if (autoscroll.value) {
    requestAnimationFrame(() => {
      listEl.value?.scrollTo({ top: listEl.value.scrollHeight });
    });
  }
}

function push(item: LogItem): void {
  lines.value.push(item);
  if (lines.value.length > MAX_LINES * 2) {
    lines.value = lines.value.slice(-MAX_LINES);
  }
  recompute();
}

async function connect(): Promise<void> {
  abort?.abort();
  abort = new AbortController();
  connected.value = false;
  try {
    await sseStream(
      '/api/v1/logs/live',
      (id, data) => {
        connected.value = true;
        if (id) lastEventId = id;
        try {
          push(JSON.parse(data) as LogItem);
        } catch {
          push({ raw: data });
        }
      },
      { signal: abort.signal, lastEventId },
    );
    connected.value = false;
    scheduleReconnect();
  } catch (err) {
    connected.value = false;
    if ((err as Error).name !== 'AbortError') scheduleReconnect();
  }
}

function scheduleReconnect(): void {
  if (reconnectTimer !== null) return;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    void connect();
  }, 2000);
}

async function loadHistory(): Promise<void> {
  const { api, unwrap } = await import('@/api/http');
  try {
    const data = await unwrap<{ items: LogItem[] }>(
      api.get('/logs/history', { params: { tail: 800 } }),
    );
    lines.value = data.items;
    recompute();
  } catch {
    // 历史缺失不阻塞 live
  }
}

onMounted(async () => {
  await loadHistory();
  void connect();
});
onBeforeUnmount(() => {
  abort?.abort();
  if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
});

function levelColor(level?: string): string {
  switch (level) {
    case 'ERROR':
      return 'error';
    case 'WARNING':
      return 'warning';
    case 'DEBUG':
      return 'info';
    default:
      return undefined as unknown as string;
  }
}
</script>

<template>
  <v-card class="pa-4">
    <div class="d-flex align-center ga-3 mb-3 flex-wrap">
      <v-chip :color="connected ? 'success' : 'warning'" size="small" variant="tonal">
        {{ connected ? '实时连接中' : '重连中…' }}
      </v-chip>
      <v-select
        v-model="levelFilter"
        :items="LEVELS"
        label="级别"
        clearable
        density="compact"
        hide-details
        style="max-width: 8rem"
        @update:model-value="recompute"
      />
      <v-text-field
        v-model="search"
        label="搜索"
        density="compact"
        hide-details
        clearable
        style="max-width: 16rem"
        @update:model-value="recompute"
      />
      <v-spacer />
      <v-checkbox
        v-model="autoscroll"
        label="自动滚动"
        density="compact"
        hide-details
      />
    </div>
    <div ref="listEl" class="log-scroll font-weight-light">
      <div v-for="(item, i) in visible" :key="i" class="log-line">
        <span class="text-disabled">{{ item.ts?.slice(11, 19) ?? '' }}</span>
        <v-chip
          v-if="item.level"
          :color="levelColor(item.level)"
          size="x-small"
          variant="tonal"
          class="mx-1"
        >
          {{ item.level }}
        </v-chip>
        <span class="text-info mr-1">{{ item.module }}</span>
        <span>{{ item.message ?? item.raw }}</span>
      </div>
      <div v-if="!visible.length" class="text-body-2 text-medium-emphasis pa-4">
        暂无日志（Bot 运行后这里实时滚动显示结构化日志）
      </div>
    </div>
  </v-card>
</template>

<style scoped>
.log-scroll {
  height: calc(100vh - 300px);
  min-height: 320px;
  overflow-y: auto;
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 0.8rem;
  background: rgba(var(--v-theme-background), 0.6);
  border-radius: 8px;
  padding: 8px;
}
.log-line {
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 0;
}
</style>
