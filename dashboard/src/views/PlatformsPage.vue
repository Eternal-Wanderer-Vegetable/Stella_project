<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

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

// M2 编辑面：正向 WS 地址 / token / HOST/PORT
const editing = ref(false);
const wsUrlsText = ref('');
const accessToken = ref('');
const host = ref('');
const port = ref('');
const toast = useToast();

async function loadConfig(): Promise<void> {
  try {
    const cfg = await unwrap<{ host: string; port: string; ws_urls: string[]; has_token: boolean }>(
      api.get('/platform/onebot'),
    );
    host.value = cfg.host;
    port.value = String(cfg.port);
    wsUrlsText.value = cfg.ws_urls.join(', ');
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openEditor(): void {
  void loadConfig();
  editing.value = true;
}

async function saveConfig(): Promise<void> {
  try {
    await unwrap(api.put('/platform/onebot', {
      ws_urls: wsUrlsText.value.split(/[,\s]+/).filter(Boolean),
      access_token: accessToken.value,
      host: host.value,
      port: port.value,
    }));
    toast.success('已保存，重启后生效');
    editing.value = false;
  } catch (err) {
    toastApiError(toast, err);
  }
}

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

    <v-card class="pa-4 mb-4">
      <div class="d-flex align-center">
        <div class="text-subtitle-1 font-weight-medium">连接配置</div>
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-pencil" @click="openEditor">编辑</v-btn>
      </div>
    </v-card>

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
    <!-- 连接配置编辑 -->
    <v-dialog v-model="editing" width="560">
      <v-card>
        <v-card-title>OneBot 连接配置</v-card-title>
        <v-card-text>
          <v-text-field v-model="host" label="监听地址（reverse 模式；异机 NapCat 用 0.0.0.0）" />
          <v-text-field v-model="port" label="监听端口" />
          <v-text-field
            v-model="wsUrlsText"
            label="正向 WS 上游（逗号分隔；forward 模式）"
            hint="留空 = 使用反向 WS"
            persistent-hint
          />
          <v-text-field
            v-model="accessToken" label="访问 token（留空不变）" type="password"
            hint="须与 NapCat 侧一致" persistent-hint
          />
          <v-alert type="info" density="compact" variant="tonal" class="mt-2">
            保存写入 .env，重启后生效。
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="editing = false">取消</v-btn>
          <v-btn color="primary" @click="saveConfig">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
