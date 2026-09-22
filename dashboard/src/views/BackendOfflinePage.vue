<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { useAuthStore } from '@/stores/auth';

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();

async function retry(): Promise<void> {
  const state = await auth.probe();
  if (state === 'online') {
    router.go(0); // 整页重载，让路由守卫按在线状态重走
  }
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
