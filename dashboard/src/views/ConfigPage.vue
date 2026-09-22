<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';
import ConfigForm, { type FormField } from '@/components/ConfigForm.vue';

// 配置页（方案 §6.6）：schema 驱动 + 前缀分组折叠 + 搜索 + 未保存守卫 +
// JSON 源码视图 + 保存→重启提示。settings import 期冻结：保存后必须重启。
interface EnvField {
  key: string;
  type: string | null;
  default: string | number | null;
  choices?: string[];
  comment?: string | null;
  inherits?: string | null;
  sensitive: boolean;
  present: boolean;
  current_value: string | null;
  has_value: boolean;
}

function toFormFields(fields: EnvField[]): FormField[] {
  return fields.map((f) => ({
    key: f.key,
    label: f.key,
    type: f.sensitive
      ? 'secret'
      : f.type === 'bool'
        ? 'bool'
        : f.type === 'int' || f.type === 'float'
          ? (f.type as 'int' | 'float')
          : f.choices?.length
            ? 'choice'
            : 'string',
    choices: f.choices,
    default: f.default,
    hint: f.comment || (f.inherits ? `留空继承 ${f.inherits}` : undefined),
    hasValue: f.has_value,
  }));
}

const rawFields = ref<EnvField[]>([]);
const values = ref<Record<string, unknown>>({});
const saved = ref<Record<string, unknown>>({});
const search = ref('');
const showJson = ref(false);
const jsonText = ref('');
const jsonError = ref('');
const saveDialog = ref(false);
const busy = ref(false);
const restartDialog = ref(false);
const toast = useToast();

const filtered = computed(() => {
  if (!search.value) return rawFields.value;
  const kw = search.value.toLowerCase();
  return rawFields.value.filter((f) => f.key.toLowerCase().includes(kw));
});

const groups = computed(() => {
  // 按 key 首段词干分组（如 LLM/PROACTIVE/SCHEDULING），形成可扫读的折叠结构
  const map = new Map<string, EnvField[]>();
  for (const f of filtered.value) {
    const stem = f.key.split('_')[0] || '其他';
    if (!map.has(stem)) map.set(stem, []);
    map.get(stem)!.push(f);
  }
  return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
});

const dirty = computed(() => JSON.stringify(values.value) !== JSON.stringify(saved.value));

function seedValues(fields: EnvField[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) out[f.key] = f.sensitive ? '' : (f.current_value ?? '');
  return out;
}

async function load(): Promise<void> {
  try {
    const data = await unwrap<{ fields: EnvField[] }>(api.get('/config'));
    rawFields.value = data.fields;
    values.value = seedValues(data.fields);
    saved.value = { ...values.value };
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openJson(): void {
  jsonText.value = JSON.stringify(values.value, null, 2);
  jsonError.value = '';
  showJson.value = true;
}

function applyJson(): void {
  try {
    const parsed = JSON.parse(jsonText.value) as Record<string, unknown>;
    values.value = { ...values.value, ...parsed };
    jsonError.value = '';
    showJson.value = false;
  } catch (err) {
    jsonError.value = (err as Error).message;
  }
}

async function save(): Promise<void> {
  const changed: Record<string, unknown> = {};
  for (const key of Object.keys(values.value)) {
    if (values.value[key] !== saved.value[key]) changed[key] = values.value[key];
  }
  if (!Object.keys(changed).length) {
    toast.info('没有修改');
    return;
  }
  busy.value = true;
  try {
    const data = await unwrap<{ restart_required: boolean }>(api.put('/config', changed));
    saved.value = { ...values.value };
    toast.success('已保存');
    if (data.restart_required) saveDialog.value = true;
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    busy.value = false;
  }
}

async function restartNow(): Promise<void> {
  saveDialog.value = false;
  try {
    await unwrap(api.post('/system/restart'));
    toast.success('已请求重启，等待服务恢复…');
  } catch (err) {
    toastApiError(toast, err);
  }
}

onMounted(load);
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center ga-3 mb-4 flex-wrap">
      <h1 class="text-h5 font-weight-bold">配置</h1>
      <v-chip size="small" variant="tonal" color="warning">修改后需重启生效</v-chip>
      <v-spacer />
      <v-text-field
        v-model="search"
        label="搜索配置键"
        density="compact"
        hide-details
        clearable
        style="max-width: 16rem"
      />
      <v-btn variant="text" prepend-icon="mdi-code-json" @click="openJson">
        JSON 源码
      </v-btn>
      <v-btn color="primary" :loading="busy" :disabled="!dirty" @click="save">保存</v-btn>
    </div>

    <div v-if="dirty" class="unsaved-pill mb-3">
      有未保存的修改
      <v-btn size="x-small" variant="text" @click="values = { ...saved }">放弃</v-btn>
    </div>

    <v-expansion-panels multiple :model-value="[0]">
      <v-expansion-panel
        v-for="[stem, fields] in groups"
        :key="stem"
        :title="`${stem}（${fields.length}）`"
      >
        <v-expansion-panel-text>
          <ConfigForm v-model="values" :fields="toFormFields(fields)" />
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>

    <v-dialog v-model="showJson" width="720">
      <v-card>
        <v-card-title>JSON 源码（当前表单值）</v-card-title>
        <v-card-text>
          <v-textarea v-model="jsonText" rows="16" density="compact" hide-details />
          <div v-if="jsonError" class="text-error text-caption mt-1">{{ jsonError }}</div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="showJson = false">关闭</v-btn>
          <v-btn color="primary" @click="applyJson">应用到表单</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="saveDialog" width="420">
      <v-card>
        <v-card-title>保存成功</v-card-title>
        <v-card-text>
          配置已写入 .env。settings 在启动时读取，需要重启 Bot 才能生效。现在重启吗？
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="saveDialog = false">稍后手动重启</v-btn>
          <v-btn color="primary" @click="restartNow">立即重启</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
.unsaved-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(var(--v-theme-warning), 0.15);
  color: rgba(var(--v-theme-warning), 1);
  padding: 4px 14px;
  border-radius: 999px;
  font-size: 0.85rem;
}
</style>
