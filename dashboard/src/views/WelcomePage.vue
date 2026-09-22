<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import { api, unwrap } from '@/api/http';

// M0 验收页：后端可达时展示一帧真实状态（复用 /stella/status 的聚合），
// Onboarding 时间线给出 M2 的落点预览。
const { t } = useI18n();

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

    <!-- Onboarding（对齐 AstrBot WelcomePage 的时间线范式；M2 接真实完成判定） -->
    <v-card class="mt-4 pa-4">
      <div class="text-subtitle-1 font-weight-medium mb-2">
        {{ $t('features.welcome.onboard') }}
      </div>
      <v-timeline side="end" density="comfortable" truncate-line="both">
        <v-timeline-item dot-color="secondary" size="small">
          <div class="text-body-2">{{ $t('features.welcome.step1') }}</div>
          <v-chip size="x-small" variant="tonal" class="mt-1">
            {{ $t('features.welcome.todoMilestone') }} · M2
          </v-chip>
        </v-timeline-item>
        <v-timeline-item dot-color="secondary" size="small">
          <div class="text-body-2">{{ $t('features.welcome.step2') }}</div>
          <v-chip size="x-small" variant="tonal" class="mt-1">
            {{ $t('features.welcome.todoMilestone') }} · M2
          </v-chip>
        </v-timeline-item>
        <v-timeline-item
          :dot-color="status?.pid ? 'success' : 'secondary'"
          size="small"
        >
          <div class="text-body-2">{{ $t('features.welcome.step3') }}</div>
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
