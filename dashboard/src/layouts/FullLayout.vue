<script setup lang="ts">
import { useTheme } from 'vuetify';

import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { useAuthStore } from '@/stores/auth';
import { useCustomizerStore, type ThemeMode } from '@/stores/customizer';
import { useToast } from '@/stores/toast';

// 侧栏信息架构对齐 AstrBot Dashboard（方案 §6）；带里程碑徽标的条目在
// 对应里程碑落地前不可点——导航即路线图，避免「空白占位页」。
const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();
const customizer = useCustomizerStore();
const toast = useToast();
const theme = useTheme();

interface NavItem {
  icon: string;
  title: string;
  to?: string;
  milestone?: string;
}

const groups: { header?: string; items: NavItem[] }[] = [
  {
    items: [
      { icon: 'mdi-hand-wave-outline', title: t('core.navigation.welcome'), to: '/' },
      { icon: 'mdi-chat-processing-outline', title: t('core.navigation.chat'), milestone: 'M4' },
    ],
  },
  {
    header: 'Connect',
    items: [
      { icon: 'mdi-robot', title: t('core.navigation.platforms'), milestone: 'M2' },
      { icon: 'mdi-creation', title: t('core.navigation.providers'), milestone: 'M2' },
      { icon: 'mdi-cog', title: t('core.navigation.config'), milestone: 'M2' },
    ],
  },
  {
    header: 'Capability',
    items: [
      { icon: 'mdi-puzzle', title: t('core.navigation.extension'), milestone: 'M3' },
      { icon: 'mdi-book-open-variant', title: t('core.navigation.knowledgeBase'), milestone: 'M3' },
      { icon: 'mdi-heart', title: t('core.navigation.persona'), milestone: 'M2' },
      { icon: 'mdi-clock-outline', title: t('core.navigation.cron'), milestone: 'M3' },
      { icon: 'mdi-account-group', title: t('core.navigation.groups'), milestone: 'M2' },
    ],
  },
  {
    header: 'Observability',
    items: [{ icon: 'mdi-database', title: t('core.navigation.data'), milestone: 'M1' }],
  },
  {
    items: [{ icon: 'mdi-cog-outline', title: t('core.navigation.settings'), milestone: 'M2' }],
  },
];

const isDark = computed(() => theme.global.name.value === 'StellaThemeDark');

function toggleTheme(): void {
  customizer.setThemeMode((isDark.value ? 'light' : 'dark') as ThemeMode);
}

async function logout(): Promise<void> {
  await auth.logout();
  toast.info(t('core.common.logout'));
  router.push({ name: 'login' });
}
</script>

<template>
  <v-layout>
    <v-navigation-drawer>
      <div class="d-flex align-center pa-4">
        <v-icon icon="mdi-star-four-points" color="secondary" class="mr-2" />
        <span class="text-h6 font-weight-bold">Stella</span>
      </div>
      <v-divider />
      <v-list nav density="comfortable">
        <template v-for="(group, gi) in groups" :key="gi">
          <v-list-subheader v-if="group.header" class="text-uppercase text-disabled">
            {{ group.header }}
          </v-list-subheader>
          <template v-for="item in group.items" :key="item.title">
            <v-list-item
              v-if="item.to"
              :title="item.title"
              :prepend-icon="item.icon"
              :active="$route.path === item.to"
              :to="item.to"
            />
            <v-list-item v-else :title="item.title" :prepend-icon="item.icon" disabled>
              <template #append>
                <v-chip size="x-small" variant="tonal" color="secondary">
                  {{ item.milestone }}
                </v-chip>
              </template>
            </v-list-item>
          </template>
        </template>
      </v-list>
    </v-navigation-drawer>

    <v-app-bar flat>
      <v-app-bar-title class="text-subtitle-1">
        {{ $t('features.welcome.title') }}
      </v-app-bar-title>
      <template #append>
        <v-btn
          :icon="isDark ? 'mdi-weather-night' : 'mdi-weather-sunny'"
          variant="text"
          @click="toggleTheme"
        />
        <v-btn icon="mdi-logout" variant="text" @click="logout" />
        <v-avatar color="primary" size="32" class="mr-4">
          <span class="text-subtitle-2">{{ auth.username.slice(0, 1).toUpperCase() }}</span>
        </v-avatar>
      </template>
    </v-app-bar>

    <v-main class="page-min-height">
      <router-view />
    </v-main>
  </v-layout>
</template>

<style scoped>
.page-min-height {
  min-height: 100vh;
}
</style>
