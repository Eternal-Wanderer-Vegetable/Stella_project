<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';

// 统计页：概览大数字 + token 趋势 + 调用柱状 + 排行（方案 §6.9，数据=usage 日账）
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
const trendOptions = computed(() => ({
  chart: { type: 'area', toolbar: { show: false }, zoom: { enabled: false } },
  stroke: { curve: 'smooth', width: 2 },
  dataLabels: { enabled: false },
  xaxis: { categories: daily.value?.series.map((s) => s.date.slice(5)) ?? [] },
  colors: ['#8FB0CC', '#E5CE9C'],
  legend: { position: 'top' },
}));
const trendSeries = computed(() => [
  { name: '输入 token', data: daily.value?.series.map((s) => s.prompt_tokens) ?? [] },
  { name: '输出 token', data: daily.value?.series.map((s) => s.completion_tokens) ?? [] },
]);
const callOptions = computed(() => ({
  chart: { type: 'bar', toolbar: { show: false } },
  plotOptions: { bar: { columnWidth: '55%' } },
  dataLabels: { enabled: false },
  xaxis: { categories: daily.value?.series.map((s) => s.date.slice(5)) ?? [] },
  colors: ['#2E3B4E'],
}));
const callSeries = computed(() => [
  { name: '调用次数', data: daily.value?.series.map((s) => s.calls) ?? [] },
]);

const budgetPercent = computed(() => {
  const t = today.value;
  if (!t || !t.budget) return 0;
  return Math.min(100, Math.round((t.used_tokens / t.budget) * 100));
});
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
          <div class="text-caption text-medium-emphasis">缓存命中率</div>
          <div class="text-h5">{{ Math.round((today.totals.cache_hit_rate ?? 0) * 100) }}%</div>
          <div class="text-caption text-disabled">分母是输入 token</div>
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
            <v-btn-toggle v-model="days" mandatory density="compact" @update:model-value="load">
              <v-btn :value="7">7 天</v-btn>
              <v-btn :value="30">30 天</v-btn>
            </v-btn-toggle>
          </div>
          <apexchart
            type="area"
            :height="chartHeight"
            :options="trendOptions"
            :series="trendSeries"
          />
        </v-card>
      </v-col>
      <v-col cols="12" md="4">
        <v-card class="pa-4">
          <div class="text-subtitle-1 font-weight-medium mb-2">调用次数</div>
          <apexchart
            type="bar"
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
