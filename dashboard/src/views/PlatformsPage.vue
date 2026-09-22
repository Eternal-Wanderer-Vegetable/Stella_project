<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';

// 平台页（M1 只读）：OneBot/NapCat 链路状态卡；连接配置编辑属 M2。
// link_status 契约：未连接时若干键为显式 null（前端按可空渲染）。
interface LinkStatus {
  enabled: boolean;
  connected: boolean;
  bot_self_id?: string | null;
  connected_seconds?: number | null;
  last_event_seconds_ago?: number | null;
  last_probe_ok?: boolean | null;
  healthy?: boolean;
  unavailable?: boolean;
  summary_text?: string;
}

const link = ref<LinkStatus | null>(null);
const error = ref('');
let timer: number | null = null;

async function load(): Promise<void> {
  try {
    link.value = await unwrap<LinkStatus>(api.get('/platform/link'));
    error.value = '';
  } catch (err) {
    error.value = (err as Error).message;
  }
}

const fmtSeconds = (v: number | null | undefined): string =>
  v === null || v === undefined ? '—' : `${Math.floor(v)}s`;

const healthy = computed(() => link.value?.healthy === true);

onMounted(() => {
  void load();
  timer = window.setInterval(load, 5000);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-1">
      <h1 class="text-h5 font-weight-bold">平台</h1>
      <v-chip size="small" variant="tonal" color="secondary" class="ml-3">M1 · 只读状态</v-chip>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      Stella 当前接入 OneBot V11 / NapCat。连接配置（正向 WS 地址、token）的编辑在 M2 上线。
    </p>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <v-card class="pa-4" :loading="!link">
      <div class="d-flex align-center ga-3 mb-3">
        <v-icon
          :icon="healthy ? 'mdi-lan-connect' : 'mdi-lan-disconnect'"
          :color="healthy ? 'success' : 'error'"
          size="28"
        />
        <div class="text-subtitle-1 font-weight-medium">OneBot 链路</div>
        <v-chip :color="healthy ? 'success' : 'error'" size="small" variant="tonal">
          {{ healthy ? '健康' : '未就绪' }}
        </v-chip>
      </div>
      <v-row v-if="link">
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">已连接</div>
          <div>{{ link.connected ? '是' : '否' }}</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">Bot 账号</div>
          <div>{{ link.bot_self_id ?? '—' }}</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">连接时长</div>
          <div>{{ fmtSeconds(link.connected_seconds) }}</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">最近事件</div>
          <div>{{ fmtSeconds(link.last_event_seconds_ago) }}前</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">最近探活</div>
          <div>
            {{
              link.last_probe_ok === null || link.last_probe_ok === undefined
                ? '—'
                : link.last_probe_ok
                  ? '成功'
                  : '失败'
            }}
          </div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">监测开关</div>
          <div>{{ link.enabled ? '开' : '关' }}</div>
        </v-col>
      </v-row>
      <v-alert
        v-if="link && !healthy"
        type="warning"
        variant="tonal"
        density="compact"
        class="mt-3"
      >
        链路未就绪：请确认 NapCat 已启动且反向 WS 指向本服务（HOST:PORT/onebot/v11/ws）。
      </v-alert>
    </v-card>
  </v-container>
</template>
