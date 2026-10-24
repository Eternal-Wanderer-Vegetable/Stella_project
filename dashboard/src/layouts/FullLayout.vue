<script setup lang="ts">
import { useTheme } from 'vuetify';

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import { useDisplay } from 'vuetify';

import { useAuthStore } from '@/stores/auth';
import { useCustomizerStore, type ThemeMode } from '@/stores/customizer';
import { useSystemStore } from '@/stores/system';
import { useToast } from '@/stores/toast';
import SystemBanner from '@/components/SystemBanner.vue';

// 侧栏信息架构对齐 AstrBot Dashboard（方案 §6）；带里程碑徽标的条目在
// 对应里程碑落地前不可点——导航即路线图，避免「空白占位页」。
const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();
const customizer = useCustomizerStore();
const system = useSystemStore();
const toast = useToast();
const theme = useTheme();
const { mdAndDown } = useDisplay();
const isCompact = mdAndDown;
const isCollapsed = ref(false);

watch(isCompact, (compact) => {
  isCollapsed.value = compact;
}, { immediate: true });

interface DrawerView {
  id: 'primary' | 'compact-overlay';
  rail: boolean;
  temporary: boolean;
}

const drawerViews = computed<DrawerView[]>(() => {
  const primary: DrawerView = {
    id: 'primary',
    rail: isCompact.value || isCollapsed.value,
    temporary: false,
  };

  // Keep the 72px rail in the layout while a second temporary drawer overlays
  // the page, so opening the menu never changes the main content width.
  return isCompact.value && !isCollapsed.value
    ? [primary, { id: 'compact-overlay', rail: false, temporary: true }]
    : [primary];
});

interface NavItem {
  icon: string;
  title: string;
  to?: string;
}

const groups: { header?: string; items: NavItem[] }[] = [
  {
    items: [
      { icon: 'mdi-hand-wave-outline', title: t('core.navigation.welcome'), to: '/' },
      { icon: 'mdi-chat-processing-outline', title: t('core.navigation.chat'), to: '/chat' },
    ],
  },
  {
    header: 'Connect',
    items: [
      { icon: 'mdi-robot', title: t('core.navigation.platforms'), to: '/platforms' },
      { icon: 'mdi-creation', title: t('core.navigation.providers'), to: '/providers' },
    ],
  },
  {
    header: 'Capability',
    items: [
      { icon: 'mdi-puzzle', title: t('core.navigation.extension'), to: '/extension' },
      { icon: 'mdi-book-open-variant', title: t('core.navigation.knowledgeBase'), to: '/knowledge-base' },
      { icon: 'mdi-account-group', title: t('core.navigation.persona'), to: '/persona' },
      { icon: 'mdi-clock-outline', title: t('core.navigation.cron'), to: '/cron' },
      { icon: 'mdi-robot-industrial', title: t('core.navigation.cometa'), to: '/cometa' },
    ],
  },
  {
    header: 'Observability',
    items: [
      { icon: 'mdi-heart-pulse', title: t('core.navigation.gravitas'), to: '/gravitas' },
      { icon: 'mdi-database', title: t('core.navigation.data'), to: '/data' },
    ],
  },
  {
    items: [{ icon: 'mdi-cog-outline', title: t('core.navigation.settings'), to: '/settings' }],
  },
];

const isDark = computed(() => theme.global.name.value === 'StellaThemeDark');

onMounted(() => {
  void system.startMonitoring();
});
onBeforeUnmount(() => system.stopMonitoring());

function toggleTheme(): void {
  customizer.setThemeMode((isDark.value ? 'light' : 'dark') as ThemeMode);
}

async function logout(): Promise<void> {
  await auth.logout();
  toast.info(t('core.common.logout'));
  router.push({ name: 'login' });
}

function toggleSidebar(): void {
  isCollapsed.value = !isCollapsed.value;
}

function updateDrawerModel(open: boolean, temporary: boolean): void {
  if (temporary && !open && isCompact.value) isCollapsed.value = true;
}

function closeTemporaryDrawer(temporary: boolean): void {
  if (temporary && isCompact.value) isCollapsed.value = true;
}
</script>

<template>
  <v-layout>
    <!-- 顶栏横贯全宽（order=-1 使侧栏从顶栏下方开始），logo 融合进顶栏；
         页面标题不再占用顶栏（各页内容区自有标题） -->
    <v-app-bar flat order="-1">
      <v-app-bar-nav-icon
        :icon="isCollapsed ? 'mdi-menu' : 'mdi-menu-open'"
        :aria-label="t(isCollapsed ? 'core.navigation.expandMenu' : 'core.navigation.collapseMenu')"
        @click="toggleSidebar"
      />
      <v-icon icon="mdi-star-four-points" color="secondary" class="ml-4 mr-2" />
      <span class="text-h6 font-weight-bold">Stella</span>
      <v-spacer />
      <v-btn
        :icon="isDark ? 'mdi-weather-night' : 'mdi-weather-sunny'"
        variant="text"
        @click="toggleTheme"
      />
      <v-btn icon="mdi-logout" variant="text" @click="logout" />
      <v-avatar color="primary" size="32" class="mr-4">
        <span class="text-subtitle-2">{{ auth.username.slice(0, 1).toUpperCase() }}</span>
      </v-avatar>
    </v-app-bar>

    <template v-for="drawer in drawerViews" :key="drawer.id">
      <v-navigation-drawer
        :model-value="!drawer.temporary || !isCollapsed"
        :permanent="!drawer.temporary"
        :temporary="drawer.temporary"
        :rail="drawer.rail"
        :rail-width="72"
        :width="256"
        :class="{ 'navigation-drawer--overlay': drawer.temporary }"
        @update:model-value="updateDrawerModel($event, drawer.temporary)"
      >
        <v-list
          nav
          density="default"
          class="pt-2 navigation-list"
          :class="{ 'navigation-list--rail': drawer.rail }"
        >
          <template v-for="(group, gi) in groups" :key="gi">
            <v-list-subheader
              v-if="group.header && !drawer.rail"
              class="text-uppercase text-disabled"
            >
              {{ group.header }}
            </v-list-subheader>
            <template v-for="item in group.items" :key="item.title">
              <v-tooltip
                v-if="item.to"
                :text="item.title"
                location="end"
                :disabled="!drawer.rail"
              >
                <template #activator="{ props: tooltipProps }">
                  <v-list-item
                    v-bind="tooltipProps"
                    :title="item.title"
                    :prepend-icon="item.icon"
                    :active="
                      $route.path === item.to ||
                      (item.to !== '/' && $route.path.startsWith(item.to))
                    "
                    :to="item.to"
                    @click="closeTemporaryDrawer(drawer.temporary)"
                  />
                </template>
              </v-tooltip>
            </template>
          </template>
        </v-list>
      </v-navigation-drawer>
    </template>

    <v-main class="page-min-height">
      <SystemBanner />
      <router-view />
    </v-main>
  </v-layout>
</template>

<style scoped>
.page-min-height {
  min-height: 100vh;
}

.navigation-list :deep(.v-list-item--nav .v-list-item-title) {
  line-height: 1.25rem;
}

.navigation-list--rail :deep(.v-list-item__prepend) {
  flex: 0 0 40px;
  justify-content: center;
  margin-inline-end: 0;
  min-width: 40px;
  width: 40px;
}

.navigation-list--rail :deep(.v-list-item__spacer) {
  display: none;
}

.navigation-drawer--overlay {
  left: 0 !important;
  z-index: 1008 !important;
}
</style>
