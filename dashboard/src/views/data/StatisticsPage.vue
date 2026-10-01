<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';

import { useTheme } from 'vuetify';

import { api, unwrap } from '@/api/http';

// 统计页：概览大数字 + token 趋势 + 调用图表 + 排行（方案 §6.9，数据=usage 日账）
type ChartKind = 'line' | 'bar';

const CHART_KIND_KEY = 'stella.data.chartKind';

function readChartKind(): ChartKind {
  try {
    const stored = localStorage.getItem(CHART_KIND_KEY);
    return stored === 'bar' ? 'bar' : 'line';
  } catch {
    return 'line';
  }
}

interface DailyTotals {
  calls: number;
  failures: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
}
interface DailyRow extends DailyTotals {
  date: string;
}
interface Ranking {
  name: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}
interface UsageToday {
  accounting: boolean;
  budget: number;
  used_tokens: number;
  remaining_tokens: number | null;
  over_budget: boolean;
  paused_roles: string[];
  totals: {
    calls: number;
    failures: number;
    prompt_tokens: number;
    completion_tokens: number;
    cache_hit_rate: number;
    estimated_cache_hit_rate?: number;
  };
  fallback_states: Record<string, unknown>;
}

const days = ref<7 | 30>(7);
const today = ref<UsageToday | null>(null);
const daily = ref<{
  accounting: boolean;
  series: DailyRow[];
  by_role: Ranking[];
  by_slot: Ranking[];
  by_model: Ranking[];
} | null>(null);
const loadError = ref('');

async function load(): Promise<void> {
  loadError.value = '';
  try {
    const [t, d] = await Promise.all([
      unwrap<UsageToday>(api.get('/usage/today')),
      unwrap<{ accounting: boolean; series: DailyRow[]; by_role: Ranking[]; by_slot: Ranking[]; by_model: Ranking[] }>(
        api.get('/usage/daily', { params: { days: days.value } }),
      ),
    ]);
    today.value = t;
    daily.value = d;
  } catch (err) {
    loadError.value = (err as Error).message;
  }
}

onMounted(load);

const chartHeight = 260;

// 图表形态用户可选（折线/柱状），偏好记忆在 localStorage；两张图共用同一口味。
const chartKind = ref<ChartKind>(readChartKind());
watch(chartKind, (kind) => {
  try {
    localStorage.setItem(CHART_KIND_KEY, kind);
  } catch {
    /* 隐私模式等存不了就算了，仅本次会话生效 */
  }
});

// apexcharts 默认文字色是为浅色底设计的深灰——暗色主题里坐标轴/图例几乎不可读
//（实测）。配色跟随 Vuetify 当前主题动态生成。
const vuetifyTheme = useTheme();
const isDark = computed(() => vuetifyTheme.current.value.dark);
const chartFore = computed(() =>
  isDark.value ? 'rgba(232, 236, 241, 0.72)' : 'rgba(0, 0, 0, 0.66)',
);
const chartGrid = computed(() =>
  isDark.value ? 'rgba(255, 255, 255, 0.10)' : 'rgba(0, 0, 0, 0.10)',
);
const chartThemeMode = computed(() => (isDark.value ? 'dark' : 'light'));

function compactTokens(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
  return String(v);
}

const trendOptions = computed(() => ({
  theme: { mode: chartThemeMode.value },
  chart: {
    type: chartKind.value,
    toolbar: { show: false },
    zoom: { enabled: false },
    foreColor: chartFore.value,
    background: 'transparent',
  },
  grid: { borderColor: chartGrid.value },
  stroke: { curve: 'smooth', width: 2 },
  dataLabels: { enabled: false },
  xaxis: {
    categories: daily.value?.series.map((s) => s.date.slice(5)) ?? [],
    labels: { style: { colors: chartFore.value } },
    axisBorder: { color: chartGrid.value },
    axisTicks: { color: chartGrid.value },
  },
  yaxis: {
    labels: { style: { colors: chartFore.value }, formatter: compactTokens },
  },
  colors: ['#8FB0CC', '#E5CE9C'],
  legend: { position: 'top', labels: { colors: chartFore.value } },
  tooltip: { theme: chartThemeMode.value },
}));
const trendSeries = computed(() => [
  { name: '输入 token', data: daily.value?.series.map((s) => s.prompt_tokens) ?? [] },
  { name: '输出 token', data: daily.value?.series.map((s) => s.completion_tokens) ?? [] },
]);
const callOptions = computed(() => ({
  theme: { mode: chartThemeMode.value },
  chart: {
    type: chartKind.value,
    toolbar: { show: false },
    foreColor: chartFore.value,
    background: 'transparent',
  },
  grid: { borderColor: chartGrid.value },
  plotOptions: { bar: { columnWidth: '55%' } },
  dataLabels: { enabled: false },
  xaxis: {
    categories: daily.value?.series.map((s) => s.date.slice(5)) ?? [],
    labels: { style: { colors: chartFore.value } },
    axisBorder: { color: chartGrid.value },
    axisTicks: { color: chartGrid.value },
  },
  yaxis: { labels: { style: { colors: chartFore.value } } },
  // 深浅两套主题下都可见的中调蓝（原 #2E3B4E 在暗色主题里隐形）
  colors: ['#5C8AC7'],
  tooltip: { theme: chartThemeMode.value },
}));
const callSeries = computed(() => [
  { name: '调用次数', data: daily.value?.series.map((s) => s.calls) ?? [] },
]);

const budgetPercent = computed(() => {
  const t = today.value;
  if (!t || !t.budget) return 0;
  return Math.min(100, Math.round((t.used_tokens / t.budget) * 100));
});

// 展示口径用理论哈希估算（本地端点不报 cached_tokens，真实口径恒零）；
// estimated 字段缺省时回落到端点上报口径（兼容旧 API 形状）。
const displayHitRate = computed(
  () => today.value?.totals.estimated_cache_hit_rate ?? today.value?.totals.cache_hit_rate ?? 0,
);
</script>

<template>
  <div>
    <v-alert v-if="loadError" type="error" variant="tonal" class="mb-4">{{ loadError }}</v-alert>
    <v-alert v-if="daily && !daily.accounting" type="info" variant="tonal" class="mb-4">
      用量记账未启用（LLM_USAGE_ACCOUNTING=false），统计不可用。
    </v-alert>

    <!-- 概览大数字 -->
    <v-row v-if="today">
      <v-col cols="6" md="3">
        <v-card class="pa-4">
          <div class="text-caption text-medium-emphasis">今日 token</div>
          <div class="text-h5">{{ today.totals.prompt_tokens + today.totals.completion_tokens }}</div>
        </v-card>
      </v-col>
      <v-col cols="6" md="3">
        <v-card class="pa-4">
          <div class="text-caption text-medium-emphasis">今日调用 / 失败</div>
          <div class="text-h5">{{ today.totals.calls }} / {{ today.totals.failures }}</div>
        </v-card>
      </v-col>
      <v-col cols="6" md="3">
        <v-card class="pa-4">
          <div class="text-caption text-medium-emphasis">
            缓存命中率
            <v-tooltip location="top" :max-width="420">
              <template #activator="{ props: tip }">
                <v-icon v-bind="tip" size="x-small" class="ml-1" icon="mdi-help-circle-outline" />
              </template>
              这里的缓存命中率为理论哈希值计算（按提示词前缀复用估算），跟实际缓存命中率有可能不一致。分母是输入 token。
            </v-tooltip>
          </div>
          <div class="text-h5">
            {{ Math.round(displayHitRate * 100) }}%
          </div>
        </v-card>
      </v-col>
      <v-col cols="6" md="3">
        <v-card class="pa-4">
          <div class="text-caption text-medium-emphasis">预算</div>
          <v-progress-linear
            :model-value="budgetPercent"
            :color="today.over_budget ? 'error' : 'primary'"
            class="mt-2"
          />
          <div class="text-caption mt-1">
            {{ today.used_tokens }} / {{ today.budget > 0 ? today.budget : '不限' }}
          </div>
        </v-card>
      </v-col>
    </v-row>
    <v-alert
      v-if="today && today.paused_roles.length"
      type="warning"
      variant="tonal"
      class="mt-2"
    >
      预算暂停中的角色：{{ today.paused_roles.join('、') }}
    </v-alert>

    <!-- 图表 -->
    <v-row class="mt-2">
      <v-col cols="12" md="8">
        <v-card class="pa-4">
          <div class="d-flex align-center mb-2">
            <div class="text-subtitle-1 font-weight-medium">token 趋势</div>
            <v-spacer />
            <v-btn-toggle v-model="chartKind" mandatory density="compact" class="mr-2">
              <v-btn value="line">折线</v-btn>
              <v-btn value="bar">柱状</v-btn>
            </v-btn-toggle>
            <v-btn-toggle v-model="days" mandatory density="compact" @update:model-value="load">
              <v-btn :value="7">7 天</v-btn>
              <v-btn :value="30">30 天</v-btn>
            </v-btn-toggle>
          </div>
          <!-- :key 强制重建：apexcharts 对 type/主题切换的原地更新不可靠 -->
          <apexchart
            :key="`trend-${chartKind}-${isDark}`"
            :type="chartKind"
            :height="chartHeight"
            :options="trendOptions"
            :series="trendSeries"
          />
        </v-card>
      </v-col>
      <v-col cols="12" md="4">
        <v-card class="pa-4">
          <div class="d-flex align-center mb-2">
            <div class="text-subtitle-1 font-weight-medium">调用次数</div>
            <v-spacer />
            <v-btn-toggle v-model="chartKind" mandatory density="compact">
              <v-btn value="line">折线</v-btn>
              <v-btn value="bar">柱状</v-btn>
            </v-btn-toggle>
          </div>
          <apexchart
            :key="`calls-${chartKind}-${isDark}`"
            :type="chartKind"
            :height="chartHeight"
            :options="callOptions"
            :series="callSeries"
          />
        </v-card>
      </v-col>
    </v-row>

    <!-- 排行 -->
    <v-row class="mt-2">
      <v-col cols="12" md="4" v-for="(rank, key) in { 角色: daily?.by_role, 端点: daily?.by_slot, 模型: daily?.by_model }" :key="key">
        <v-card class="pa-4">
          <div class="text-subtitle-1 font-weight-medium mb-2">按{{ key }}排行</div>
          <v-table density="compact" v-if="rank && rank.length">
            <thead>
              <tr><th>名称</th><th class="text-right">调用</th><th class="text-right">token</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in rank.slice(0, 8)" :key="item.name">
                <td>{{ item.name }}</td>
                <td class="text-right">{{ item.calls }}</td>
                <td class="text-right">{{ item.total_tokens }}</td>
              </tr>
            </tbody>
          </v-table>
          <div v-else class="text-body-2 text-medium-emphasis">暂无数据</div>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>
