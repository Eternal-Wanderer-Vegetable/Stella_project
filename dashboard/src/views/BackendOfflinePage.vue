<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { isTauri, tauriBridge } from '@/api/tauri';
import { useAuthStore } from '@/stores/auth';

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();

const starting = ref(false);
const startError = ref('');
const doctorText = ref('');
const inShell = computed(() => isTauri());

async function retry(): Promise<void> {
  const state = await auth.probe();
  if (state === 'online') {
    router.go(0); // 整页重载，让路由守卫按在线状态重走
  }
}

/** 壳内启动：start_bot → 轮询就绪 → 导航到在线面板（方案 §11.2）。 */
async function startFromShell(): Promise<void> {
  starting.value = true;
  startError.value = '';
  try {
    await tauriBridge.startBot(false);
    const base = await tauriBridge.waitBotReady(180);
    window.location.href = base; // 导航到 Bot 托管的在线面板
  } catch (err) {
    startError.value = (err as Error).message;
    starting.value = false;
  }
}

/** 壳内自检：deploy doctor 的文本报告。 */
async function runShellDoctor(): Promise<void> {
  doctorText.value = await tauriBridge.runDoctor();
}

</script>

<template>
  <v-container fluid class="fill-height offline-bg">
    <v-row justify="center" align="center">
      <v-col cols="12" sm="8" md="5" lg="4">
        <v-card elevation="8" class="pa-6 text-center">
          <v-icon icon="mdi-lan-disconnect" size="48" color="warning" class="mb-3" />
          <div class="text-h6 mb-2">{{ $t('features.offline.title') }}</div>
          <p class="text-body-2 text-medium-emphasis mb-4">
            {{ $t('features.offline.hint') }}
          </p>
          <v-btn color="primary" @click="retry">
            {{ $t('features.offline.retry') }}
          </v-btn>
          <v-btn
            v-if="inShell"
            color="secondary"
            :loading="starting"
            @click="startFromShell"
          >
            启动 Bot
          </v-btn>
          <v-btn v-if="inShell" variant="text" @click="runShellDoctor">环境自检</v-btn>
          <pre v-if="doctorText" class="text-caption text-left" style="max-height: 180px; overflow-y: auto">{{ doctorText }}</pre>
          <div v-if="startError" class="text-error text-caption mt-2">{{ startError }}</div>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
.offline-bg {
  min-height: 100vh;
}
</style>
