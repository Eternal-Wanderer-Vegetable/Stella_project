<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { formatDbTime } from '@/utils/time';

import { api, unwrap } from '@/api/http';

// 会话页：群筛选 + 消息分页（只读）+ 整合 checkpoint（方案 §6.9）
interface MessageItem {
  id: number;
  timestamp: string;
  user_id: string;
  content: string;
  source_kind: string;
  msg_id: number | null;
}
interface GroupInfo {
  group_id: string;
  messages: number;
  last_ts: string;
}
interface TransportScene {
  conversation_key: string;
  connection_id: string;
  adapter: string;
  self_id: string;
  kind: string;
  scene_id: string;
  parent_path: string[];
  thread_id: string | null;
  messages: number;
  last_ts: string | null;
}
interface TransportMessage extends MessageItem {
  platform_message_id: string | null;
}

const groups = ref<GroupInfo[]>([]);
const selectedGroup = ref<string | null>(null);
const messages = ref<MessageItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 50;
const checkpoint = ref<{ last_processed_id: number; skip_streak: number; updated_at: string } | null>(
  null,
);
const loading = ref(false);
const error = ref('');
const activeView = ref<'legacy' | 'transport'>('legacy');
const transportScenes = ref<TransportScene[]>([]);
const selectedTransportKey = ref('');
const transportMessages = ref<TransportMessage[]>([]);
const transportTotal = ref(0);
const transportPage = ref(1);
const transportCursor = ref<number | null>(null);
const transportSnapshotId = ref<number | null>(null);
const transportNextCursor = ref<number | null>(null);
const transportCursorStack = ref<Array<{ cursor: number | null; snapshotId: number | null }>>([]);
const transportLoading = ref(false);
const transportError = ref('');
const transportSceneOptions = computed(() => transportScenes.value.map((scene) => ({
  value: scene.conversation_key,
  title: `${scene.adapter} · ${scene.self_id} · ${scene.kind}:${scene.scene_id}`,
  subtitle: `${scene.parent_path.join(' / ') || '—'}${scene.thread_id ? ` · ${scene.thread_id}` : ''}`,
})));

const KIND_META: Record<string, { label: string; color: string }> = {
  AT_MENTION: { label: '@机器人', color: 'primary' },
  PASSIVE: { label: '被动摄入', color: 'default' },
  BOT_SELF: { label: 'Bot 发言', color: 'secondary' },
};

async function loadGroups(): Promise<void> {
  try {
    const data = await unwrap<{ groups: GroupInfo[] }>(api.get('/conversations/groups'));
    groups.value = data.groups;
    if (data.groups.length && !selectedGroup.value) {
      selectedGroup.value = data.groups[0].group_id;
    }
  } catch (err) {
    error.value = (err as Error).message;
  }
}

async function loadMessages(): Promise<void> {
  if (!selectedGroup.value) return;
  loading.value = true;
  error.value = '';
  try {
    const data = await unwrap<{ total: number; items: MessageItem[] }>(
      api.get('/conversations', {
        params: { group_id: selectedGroup.value, page: page.value, page_size: pageSize },
      }),
    );
    messages.value = data.items;
    total.value = data.total;
    const ctx = await unwrap<{ consolidation: typeof checkpoint.value }>(
      api.get('/conversations/context', { params: { group_id: selectedGroup.value } }),
    );
    checkpoint.value = ctx.consolidation;
  } catch (err) {
    error.value = (err as Error).message;
  } finally {
    loading.value = false;
  }
}

async function loadTransportScenes(): Promise<void> {
  transportError.value = '';
  try {
    const data = await unwrap<{ scenes: TransportScene[] }>(api.get('/conversations/scenes'));
    transportScenes.value = data.scenes;
    if (!selectedTransportKey.value && data.scenes.length) {
      selectedTransportKey.value = data.scenes[0].conversation_key;
    }
    if (selectedTransportKey.value) {
      resetTransportPaging();
      await loadTransportMessages();
    }
  } catch (err) {
    transportError.value = (err as Error).message;
  }
}

async function loadTransportMessages(): Promise<void> {
  if (!selectedTransportKey.value) {
    transportMessages.value = [];
    transportTotal.value = 0;
    return;
  }
  transportLoading.value = true;
  transportError.value = '';
  transportNextCursor.value = null;
  try {
    const params: Record<string, string | number> = {
      conversation_key: selectedTransportKey.value,
      page_size: pageSize,
    };
    if (transportCursor.value !== null) params.cursor = transportCursor.value;
    if (transportSnapshotId.value !== null) params.snapshot_id = transportSnapshotId.value;
    const data = await unwrap<{
      total: number;
      items: TransportMessage[];
      snapshot_id: number;
      next_cursor: number | null;
    }>(
      api.get('/conversations/messages', {
        params,
      }),
    );
    transportMessages.value = data.items;
    transportTotal.value = data.total;
    transportSnapshotId.value = data.snapshot_id;
    transportNextCursor.value = data.next_cursor;
  } catch (err) {
    transportError.value = (err as Error).message;
  } finally {
    transportLoading.value = false;
  }
}

function pickTransportScene(key: string): void {
  selectedTransportKey.value = key;
  resetTransportPaging();
  void loadTransportMessages();
}

function resetTransportPaging(): void {
  transportPage.value = 1;
  transportCursor.value = null;
  transportSnapshotId.value = null;
  transportNextCursor.value = null;
  transportCursorStack.value = [];
}

function nextTransportPage(): void {
  if (transportNextCursor.value === null || transportSnapshotId.value === null) return;
  transportCursorStack.value.push({
    cursor: transportCursor.value,
    snapshotId: transportSnapshotId.value,
  });
  transportCursor.value = transportNextCursor.value;
  transportPage.value += 1;
  void loadTransportMessages();
}

function previousTransportPage(): void {
  const previous = transportCursorStack.value.pop();
  if (!previous) return;
  transportCursor.value = previous.cursor;
  transportSnapshotId.value = previous.snapshotId;
  transportPage.value = Math.max(1, transportPage.value - 1);
  void loadTransportMessages();
}

function pickGroup(groupId: string): void {
  selectedGroup.value = groupId;
  page.value = 1;
  void loadMessages();
}

function prev(): void {
  if (page.value > 1) {
    page.value -= 1;
    void loadMessages();
  }
}
function next(): void {
  if (page.value * pageSize < total.value) {
    page.value += 1;
    void loadMessages();
  }
}

onMounted(async () => {
  await Promise.all([loadGroups(), loadTransportScenes()]);
  await loadMessages();
});
</script>

<template>
  <div>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>
    <v-tabs v-model="activeView" class="mb-3">
      <v-tab value="legacy">QQ 群历史（兼容）</v-tab>
      <v-tab value="transport">跨平台会话历史</v-tab>
    </v-tabs>
    <v-card v-if="activeView === 'legacy'" class="pa-4">
      <div class="d-flex align-center ga-3 mb-3 flex-wrap">
        <v-select
          :model-value="selectedGroup"
          :items="groups"
          item-title="group_id"
          item-value="group_id"
          label="群"
          density="compact"
          hide-details
          style="max-width: 14rem"
          @update:model-value="pickGroup"
        />
        <span v-if="groups.length" class="text-caption text-medium-emphasis">
          共 {{ total }} 条 · 第 {{ page }}/{{ Math.max(1, Math.ceil(total / pageSize)) }} 页
        </span>
        <v-spacer />
        <v-btn icon="mdi-chevron-left" size="small" variant="text" :disabled="page <= 1" @click="prev" />
        <v-btn
          icon="mdi-chevron-right"
          size="small"
          variant="text"
          :disabled="page * pageSize >= total"
          @click="next"
        />
        <v-btn icon="mdi-refresh" size="small" variant="text" @click="loadMessages" />
      </div>

      <div v-if="checkpoint" class="text-caption text-medium-emphasis mb-2">
        整合 checkpoint：已处理到消息 id {{ checkpoint.last_processed_id }} ·
        连续跳过 {{ checkpoint.skip_streak }} · 更新于 {{ checkpoint.updated_at }}
      </div>

      <div class="msg-scroll">
        <v-list density="compact" v-if="messages.length">
          <v-list-item v-for="item in messages" :key="item.id">
            <template #prepend>
              <v-chip
                :color="KIND_META[item.source_kind]?.color ?? 'default'"
                size="x-small"
                variant="tonal"
                class="mr-2"
              >
                {{ KIND_META[item.source_kind]?.label ?? item.source_kind }}
              </v-chip>
            </template>
            <v-list-item-title class="text-body-2">
              {{ item.content }}
            </v-list-item-title>
            <v-list-item-subtitle>
              {{ formatDbTime(item.timestamp) }} · 用户 {{ item.user_id }}
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
        <div v-else class="text-body-2 text-medium-emphasis pa-4">
          没有消息。群消息按 QQ 群落库（含 Bot 自己的发言与被动摄入），积分后进入记忆。
        </div>
      </div>
    </v-card>
    <v-card v-else class="pa-4">
      <v-alert v-if="transportError" type="warning" variant="tonal" class="mb-3">
        {{ transportError }}
      </v-alert>
      <div class="d-flex align-center ga-3 mb-3 flex-wrap">
        <v-select
          :model-value="selectedTransportKey"
          :items="transportSceneOptions"
          item-title="title"
          item-value="value"
          label="平台 / 连接 / 场景"
          density="compact"
          hide-details
          style="min-width: 20rem; max-width: 42rem"
          :disabled="transportLoading || !transportSceneOptions.length"
          @update:model-value="pickTransportScene"
        >
          <template #item="{ props: itemProps, item }">
            <v-list-item v-bind="itemProps" :subtitle="item.raw.subtitle" />
          </template>
        </v-select>
        <span v-if="selectedTransportKey" class="text-caption text-medium-emphasis">
          共 {{ transportTotal }} 条 · 第 {{ transportPage }} 页
        </span>
        <v-spacer />
        <v-btn icon="mdi-chevron-left" size="small" variant="text" :disabled="transportPage <= 1 || transportLoading" @click="previousTransportPage" />
        <v-btn icon="mdi-chevron-right" size="small" variant="text" :disabled="transportNextCursor === null || transportLoading" @click="nextTransportPage" />
        <v-btn icon="mdi-refresh" size="small" variant="text" :disabled="transportLoading" @click="loadTransportMessages" />
      </div>
      <div v-if="selectedTransportKey" class="msg-scroll">
        <v-list v-if="transportMessages.length" density="compact">
          <v-list-item v-for="item in transportMessages" :key="item.id">
            <template #prepend>
              <v-chip :color="KIND_META[item.source_kind]?.color ?? 'default'" size="x-small" variant="tonal" class="mr-2">
                {{ KIND_META[item.source_kind]?.label ?? item.source_kind }}
              </v-chip>
            </template>
            <v-list-item-title class="text-body-2">{{ item.content }}</v-list-item-title>
            <v-list-item-subtitle>
              {{ formatDbTime(item.timestamp) }} · 用户 {{ item.user_id }} · 外部消息 {{ item.platform_message_id || '—' }}
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
        <div v-else-if="!transportLoading" class="text-body-2 text-medium-emphasis pa-4">
          当前场景没有有效历史消息；已被后续编辑替换或删除的来源行不会显示。
        </div>
      </div>
      <div v-else-if="!transportLoading" class="text-body-2 text-medium-emphasis pa-4">
        尚无已注册的跨平台会话场景。
      </div>
    </v-card>
  </div>
</template>

<style scoped>
.msg-scroll {
  max-height: calc(100vh - 340px);
  min-height: 300px;
  overflow-y: auto;
}
</style>
