<script setup lang="ts">
import { onMounted, ref } from 'vue';

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
  await loadGroups();
  await loadMessages();
});
</script>

<template>
  <div>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>
    <v-card class="pa-4">
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
              {{ item.timestamp }} · 用户 {{ item.user_id }}
            </v-list-item-subtitle>
          </v-list-item>
        </v-list>
        <div v-else class="text-body-2 text-medium-emphasis pa-4">
          没有消息。群消息按 QQ 群落库（含 Bot 自己的发言与被动摄入），积分后进入记忆。
        </div>
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
