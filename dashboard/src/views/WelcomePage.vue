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
  usage: { tokens_today?: number } | null;
  webui?: { username: string };
}

const status = ref<StatusPayload | null>(null);
const loadError = ref('');

const uptimeText = computed(() => {
  if (!status.value) return '—';
  const s = Math.floor(status.value.uptime_seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`;
});

// 引导步骤 → 功能页。step 的完成态只用在有现成数据的地方（不为此多发请求）：
// step2 看已绑定群数，step3 看进程存活（pid）；step1 无现成判据，保持待办色。
const steps = computed(() => [
  { key: 'step1', to: '/providers', done: false },
  { key: 'step2', to: '/groups', done: (status.value?.allowed_group_count ?? 0) > 0 },
  { key: 'step3', to: '/settings', done: !!status.value?.pid },
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
          <div class="text-h6">{{ status.usage?.tokens_today ?? '—' }}</div>
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
