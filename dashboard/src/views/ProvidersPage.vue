<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';

// 提供商页（M1 只读运行态）：调度器闸门排队 + 降级状态；端点/角色配置编辑属 M2
interface GateState {
  limit: number;
  holding: number;
  holders: string[];
  waiting: number;
  holder: string | null;
  held_seconds: number;
  acquired: number;
  avg_wait: number;
  peak_waiting: number;
}
interface RuntimePayload {
  scheduler: Record<string, GateState>;
  fallback_states: Record<string, Record<string, unknown>>;
}

const runtime = ref<RuntimePayload | null>(null);
const error = ref('');
let timer: number | null = null;

async function load(): Promise<void> {
  try {
    runtime.value = await unwrap<RuntimePayload>(api.get('/providers/runtime'));
    error.value = '';
  } catch (err) {
    error.value = (err as Error).message;
  }
}

const gates = computed(() => Object.entries(runtime.value?.scheduler ?? {}));
const fallbacks = computed(() => Object.entries(runtime.value?.fallback_states ?? {}));

onMounted(() => {
  void load();
  timer = window.setInterval(load, 5000);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-1">
      <h1 class="text-h5 font-weight-bold">提供商</h1>
      <v-chip size="small" variant="tonal" color="secondary" class="ml-3">M1 · 只读运行态</v-chip>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      这里是模型调度器的实时闸门与降级状态。端点与角色的配置编辑在 M2 上线。
    </p>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <v-card class="pa-4 mb-4">
      <div class="text-subtitle-1 font-weight-medium mb-2">模型闸门（每端点串行）</div>
      <v-table density="compact" v-if="gates.length">
        <thead>
          <tr>
            <th>资源（端点槽）</th><th>并发上限</th><th>持有中</th>
            <th>排队</th><th>累计获取</th><th>平均等待</th><th>当前持有者</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[name, g] in gates" :key="name">
            <td>{{ name }}</td>
            <td>{{ g.limit }}</td>
            <td>{{ g.holding }}</td>
            <td>
              <v-chip v-if="g.waiting > 0" size="x-small" color="warning" variant="tonal">
                {{ g.waiting }}
              </v-chip>
              <span v-else>0</span>
            </td>
            <td>{{ g.acquired }}</td>
            <td>{{ g.avg_wait.toFixed(2) }}s</td>
            <td>{{ g.holder ?? '—' }}</td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis">
        尚无调度记录（Bot 至少完成一次 LLM 调用后这里才有数据）。
      </div>
    </v-card>

    <v-card class="pa-4">
      <div class="text-subtitle-1 font-weight-medium mb-2">降级状态</div>
      <div v-if="fallbacks.length">
        <div v-for="[role, state] in fallbacks" :key="role" class="mb-2">
          <b class="text-body-2">{{ role }}</b>
          <pre class="text-caption text-medium-emphasis">{{ JSON.stringify(state, null, 2) }}</pre>
        </div>
      </div>
      <div v-else class="text-body-2 text-medium-emphasis">
        没有角色正在降级（配了降级链且调用过的角色才会出现在这里）。
      </div>
    </v-card>
  </v-container>
</template>
