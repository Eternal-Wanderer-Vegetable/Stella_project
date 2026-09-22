<script setup lang="ts">
import { useTheme } from 'vuetify';

import { watch } from 'vue';

import { useCustomizerStore } from '@/stores/customizer';
import { useToastStore } from '@/stores/toast';

const customizer = useCustomizerStore();
const toast = useToastStore();
const theme = useTheme();

// 主题模式（light/dark/system）→ Vuetify 全局主题（方案 §10.5）
watch(
  () => customizer.resolvedTheme,
  (name) => {
    theme.global.name.value = name;
  },
  { immediate: true },
);
</script>

<template>
  <v-app>
    <router-view />
    <v-snackbar
      :model-value="toast.current !== null"
      :color="toast.current?.color"
      location="top"
      :timeout="3500"
      @update:model-value="(v: boolean) => (v || toast.done())"
    >
      {{ toast.current?.message }}
    </v-snackbar>
  </v-app>
</template>
