<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { api, unwrap } from '@/api/http';

// 欢迎页：后端可达时展示一帧真实状态（复用 /stella/status 的聚合），
// Onboarding 时间线的每一步可点击跳转到对应功能页。
const { t } = useI18n();
const router = useRouter();

interface StatusPayload {
  version: string;
  pid: number;
  uptime_seconds: number;
  allowed_group_count: number;
  link: { connected?: boolean } | null;
  usage: { totals: { prompt_tokens: number; completion_tokens: number } | null } | null;
  webui?: { username: string };
}

const status = ref<StatusPayload | null>(null);
const loadError = ref('');

// 今日 token：与统计页同一口径（totals.prompt + totals.completion，来自
// usage 日账的当日累计）。status.usage 里没有现成的 tokens_today 字段，
// 之前读它永远是 undefined，显示成「—」（2026-09-25 用户报告）。
const tokensToday = computed(() => {
  const totals = status.value?.usage?.totals;
  if (!totals) return '—';
  return (totals.prompt_tokens ?? 0) + (totals.completion_tokens ?? 0);
});

// step1「配置模型端点」的完成判定（2026-09-25 用户要求）：**必选**的对话与记忆
// 两槽都配好（地址 + 模型），且本地端点能实际连通（拉到模型列表）。视觉是可选
// 增强，不参与判定。null = 判定进行中，圆点保持待办色。
const endpointsReady = ref<boolean | null>(null);

interface EndpointLike {
  slot: string;
  base_url: string;
  model: string;
  kind: string;
  has_api_key: boolean;
}

async function checkEndpointsReady(): Promise<void> {
  try {
    const { endpoints } = await unwrap<{ endpoints: EndpointLike[] }>(
      api.get('/providers/endpoints'),
    );
    const required = ['CHAT', 'MEMORY'].map((slot) =>
      endpoints.find((e) => e.slot === slot),
    );
    // 配置齐全是第一道门槛（地址 + 模型都在）；在线端点凭 key 才能验证
    //（key 不回显），配置齐全即算过；本地端点用「拉模型列表」做真实连通
    // 探测（fetch_endpoint_models，5s 超时）。
    const configured = required.every(
      (e) => e !== undefined && !!e.base_url && !!e.model,
    );
    if (!configured) {
      endpointsReady.value = false;
      return;
    }
    const localChecks = required
      .filter((e): e is EndpointLike => !!e && e.kind === 'local')
      .map((e) =>
        unwrap<{ models: string[]; error: string }>(
          api.get('/providers/models', { params: { base_url: e.base_url } }),
        ).then((r) => !r.error),
      );
    endpointsReady.value = localChecks.length
      ? (await Promise.all(localChecks)).every(Boolean)
      : true;
  } catch {
    // 探测失败（后端刚重启等）按未完成处理，不报错——这只是一个引导圆点
    endpointsReady.value = false;
  }
}

const uptimeText = computed(() => {
  if (!status.value) return '—';
  const s = Math.floor(status.value.uptime_seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
});

// 引导步骤 → 功能页。step 的完成态只用在有现成数据的地方（不为此多发请求）：
// step1 看对话+记忆端点配置与连通（checkEndpointsReady 探测）；step2 看已绑定
// 群数；step3 看进程存活（pid）。
const steps = computed(() => [
  { key: 'step1', to: '/providers', done: endpointsReady.value === true },
  { key: 'step2', to: '/groups', done: (status.value?.allowed_group_count ?? 0) > 0 },
  { key: 'step3', to: '/platforms', done: !!status.value?.pid },
]);

function goStep(to: string) {
  router.push(to);
}

onMounted(async () => {
  try {
    status.value = await unwrap<StatusPayload>(api.get('/status'));
  } catch (err) {
    loadError.value = (err as Error).message;
  }
  void checkEndpointsReady();
});
</script>

<template>
  <v-container fluid class="pa-6">
    <h1 class="text-h5 font-weight-bold mb-1">{{ $t('features.welcome.title') }}</h1>
    <p v-if="status?.webui" class="text-body-2 text-medium-emphasis">
      {{ status.webui.username }}
    </p>

    <v-alert v-if="loadError" type="error" variant="tonal" class="mt-4">
      {{ loadError }}
    </v-alert>

    <!-- Onboarding（对齐 AstrBot WelcomePage 的时间线范式）：每步可点击跳转对应功能页 -->
    <v-card class="mt-4 pa-4">
      <div class="text-subtitle-1 font-weight-medium mb-2">
        {{ $t('features.welcome.onboard') }}
      </div>
      <v-timeline side="end" density="comfortable" truncate-line="both">
        <v-timeline-item
          v-for="step in steps"
          :key="step.key"
          :dot-color="step.done ? 'success' : 'secondary'"
          size="small"
        >
          <div
            class="stella-step d-flex align-center"
            :title="$t('features.welcome.go')"
            @click="goStep(step.to)"
          >
            <div class="text-body-2">{{ $t(`features.welcome.${step.key}`) }}</div>
            <v-spacer />
            <v-icon size="small" icon="mdi-chevron-right" class="stella-step-go" />
          </div>
        </v-timeline-item>
      </v-timeline>
    </v-card>

    <!-- 运行状态卡（数据即 v1 status payload 的聚合） -->
    <v-card class="mt-4 pa-4" :loading="!status && !loadError">
      <div class="text-subtitle-1 font-weight-medium mb-3">
        {{ $t('features.welcome.statusTitle') }}
      </div>
      <v-row v-if="status">
        <v-col cols="6" sm="4" md="3">
          <div class="text-caption text-medium-emphasis">{{ $t('features.welcome.version') }}</div>
          <div class="text-h6">v{{ status.version }}</div>
        </v-col>
        <v-col cols="6" sm="4" md="3">
          <div class="text-caption text-medium-emphasis">{{ $t('features.welcome.pid') }}</div>
          <div class="text-h6">{{ status.pid }}</div>
        </v-col>
        <v-col cols="6" sm="4" md="3">
          <div class="text-caption text-medium-emphasis">{{ $t('features.welcome.uptime') }}</div>
          <div class="text-h6">{{ uptimeText }}</div>
        </v-col>
        <v-col cols="6" sm="4" md="3">
          <div class="text-caption text-medium-emphasis">{{ $t('features.welcome.link') }}</div>
          <div class="text-h6">
            <v-icon
              size="small"
              :color="status.link?.connected ? 'success' : 'error'"
              icon="mdi-circle"
              class="mr-1"
            />
            {{ status.link?.connected ? $t('core.status.online') : $t('core.status.offline') }}
          </div>
        </v-col>
        <v-col cols="6" sm="4" md="3">
          <div class="text-caption text-medium-emphasis">{{ $t('features.welcome.groups') }}</div>
          <div class="text-h6">{{ status.allowed_group_count }}</div>
        </v-col>
        <v-col cols="6" sm="4" md="3">
          <div class="text-caption text-medium-emphasis">{{ $t('features.welcome.tokensToday') }}</div>
          <div class="text-h6">{{ tokensToday }}</div>
        </v-col>
      </v-row>
    </v-card>
  </v-container>
</template>

<style scoped>
/* 引导步骤整行可点：悬停给反馈，右侧箭头提示跳转 */
.stella-step {
  cursor: pointer;
  border-radius: 8px;
  padding: 2px 6px;
  margin: -2px -6px;
  transition: background-color 0.15s ease;
}

.stella-step:hover {
  background-color: rgba(var(--v-theme-primary), 0.08);
}

.stella-step:hover .stella-step-go {
  opacity: 1;
}

.stella-step-go {
  opacity: 0.4;
  transition: opacity 0.15s ease;
}
</style>
