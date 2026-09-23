<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

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

// ---- M2 编辑面：端点槽 + 角色绑定 ----
interface Endpoint {
  slot: string; base_url: string; model: string; kind: string;
  concurrency: number; timeout: number; has_api_key: boolean;
}
interface Role { role: string; endpoint: string; model: string; temperature: number }
const endpoints = ref<Endpoint[]>([]);
const roles = ref<Role[]>([]);
const editing = ref(false);
const testResult = ref<{ ok: boolean; error?: string } | null>(null);
const testing = ref(false);
const apiKeyInputs = ref<Record<string, string>>({});
const fetchedModels = ref<Record<string, string[]>>({});
const toast = useToast();

async function loadConfig(): Promise<void> {
  try {
    const e = await unwrap<{ endpoints: Endpoint[] }>(api.get('/providers/endpoints'));
    endpoints.value = e.endpoints;
    const r = await unwrap<{ roles: Role[] }>(api.get('/providers/roles'));
    roles.value = r.roles;
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openEditor(): void {
  apiKeyInputs.value = {};
  testResult.value = null;
  editing.value = true;
}

async function fetchModels(ep: Endpoint): Promise<void> {
  try {
    const data = await unwrap<{ models: string[]; error: string }>(
      api.get('/providers/models', {
        params: { base_url: ep.base_url, api_key: apiKeyInputs.value[ep.slot] ?? '' },
      }),
    );
    if (data.error) {
      toast.error(data.error);
      return;
    }
    fetchedModels.value[ep.slot] = data.models;
    if (data.models.length && !ep.model) ep.model = data.models[0];
    toast.success(`拉到 ${data.models.length} 个模型，点击卡片选择`);
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function testEp(ep: Endpoint): Promise<void> {
  testing.value = true;
  try {
    testResult.value = await unwrap<{ ok: boolean; error?: string }>(
      api.post('/providers/test', {
        base_url: ep.base_url, model: ep.model,
        api_key: apiKeyInputs.value[ep.slot] ?? '',
      }),
    );
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    testing.value = false;
  }
}

async function saveConfig(): Promise<void> {
  try {
    await unwrap(api.put('/providers/endpoints', endpoints.value));
    await unwrap(api.put('/providers/roles', roles.value));
    toast.success('已保存，需重启生效');
    editing.value = false;
  } catch (err) {
    toastApiError(toast, err);
  }
}

onMounted(() => {
  void load();
  void loadConfig();
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
      <v-chip size="small" variant="tonal" color="secondary" class="ml-3">运行态 + 配置</v-chip>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      在此编辑模型端点（Base URL / 模型 / API Key）与角色绑定，并测试连通性；
    下方为调度器的实时闸门与降级状态。保存写入 .env，重启后生效。
    </p>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <v-card class="pa-4 mb-4">
      <div class="d-flex align-center mb-2">
        <div class="text-subtitle-1 font-weight-medium">端点与角色</div>
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-pencil" @click="openEditor">编辑配置</v-btn>
      </div>
      <v-table density="compact">
        <thead>
          <tr><th>端点槽</th><th>Base URL</th><th>模型</th><th>类型</th><th>API Key</th></tr>
        </thead>
        <tbody>
          <tr v-for="ep in endpoints" :key="ep.slot">
            <td>{{ ep.slot }}</td>
            <td>{{ ep.base_url || '—' }}</td>
            <td>{{ ep.model || '—' }}</td>
            <td>{{ ep.kind || '—' }}</td>
            <td>
              <v-chip size="x-small" variant="tonal" :color="ep.has_api_key ? 'success' : 'default'">
                {{ ep.has_api_key ? '已设置' : '未设置' }}
              </v-chip>
            </td>
          </tr>
        </tbody>
      </v-table>
      <div class="text-caption text-medium-emphasis mt-2">
        角色绑定：{{ roles.map((r) => `${r.role}→${r.endpoint}`).join(' · ') }}
      </div>
    </v-card>

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
    <!-- 端点/角色编辑对话框 -->
    <v-dialog v-model="editing" width="860" scrollable>
      <v-card>
        <v-card-title>编辑端点与角色绑定</v-card-title>
        <v-card-text style="max-height: 65vh; overflow-y: auto">
          <div class="text-subtitle-2 mb-2">端点槽（API Key 留空 = 不修改）</div>
          <v-card v-for="ep in endpoints" :key="ep.slot" variant="outlined" class="pa-3 mb-3">
            <div class="text-subtitle-2 mb-2">{{ ep.slot }}</div>
            <v-text-field v-model="ep.base_url" label="Base URL" density="compact" />
            <div class="d-flex ga-2 align-center">
              <v-text-field
                v-model="ep.model" label="模型 ID"
                :hint="ep.model ? undefined : '未配置模型 ID——doctor 会告警；拉取模型后点选即可'"
                persistent-hint
                density="compact"
              />
              <v-btn variant="text" size="small" prepend-icon="mdi-refresh" @click="fetchModels(ep)">
                拉取模型
              </v-btn>
              <v-btn variant="text" size="small" prepend-icon="mdi-lan" :loading="testing" @click="testEp(ep)">
                测试
              </v-btn>
            </div>
            <div v-if="fetchedModels[ep.slot]?.length" class="d-flex flex-wrap ga-1 mt-1">
              <v-chip
                v-for="m in fetchedModels[ep.slot]" :key="m"
                size="small"
                :variant="ep.model === m ? 'tonal' : 'outlined'"
                :color="ep.model === m ? 'primary' : undefined"
                @click="ep.model = m"
              >
                {{ m }}
              </v-chip>
            </div>
            <v-text-field
              v-model="apiKeyInputs[ep.slot]" label="API Key（留空不变）"
              density="compact" type="password"
              :placeholder="ep.has_api_key ? '已设置' : '未设置'"
            />
            <div class="d-flex ga-2">
              <v-text-field v-model="ep.kind" label="类型（local/online）" density="compact" />
              <v-text-field v-model="ep.concurrency" label="并发" density="compact" />
              <v-text-field v-model="ep.timeout" label="超时(秒)" density="compact" />
            </div>
            <v-alert v-if="testResult" :type="testResult.ok ? 'success' : 'error'" density="compact" class="mt-2">
              {{ testResult.ok ? '连通正常' : (testResult.error ?? '测试失败') }}
            </v-alert>
          </v-card>
          <div class="text-subtitle-2 mb-2 mt-4">角色绑定矩阵</div>
          <v-table density="compact">
            <thead><tr><th>角色</th><th>端点槽</th><th>模型覆盖</th><th>温度</th></tr></thead>
            <tbody>
              <tr v-for="r in roles" :key="r.role">
                <td>{{ r.role }}</td>
                <td>
                  <v-select v-model="r.endpoint" :items="['none', ...endpoints.map(e => e.slot)]"
                            density="compact" hide-details />
                </td>
                <td><v-text-field v-model="r.model" density="compact" hide-details /></td>
                <td><v-text-field v-model="r.temperature" density="compact" hide-details /></td>
              </tr>
            </tbody>
          </v-table>
          <div class="text-caption text-medium-emphasis mt-2">
            端点槽选 none = 该角色不启用（视觉默认不启用，属可选增强）。
            <v-alert type="warning" density="compact" variant="tonal" class="mt-2">
              保存写入 .env，重启后生效。
            </v-alert>
          </div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="editing = false">取消</v-btn>
          <v-btn color="primary" @click="saveConfig">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
