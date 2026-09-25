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
const busy = ref(false);
const openSections = ref<string[]>([]);
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
    // 折叠面板的展开状态必须是受控的：之前绑定静态 :model-value="[0]"，
    // 每敲一个字触发重渲染就把面板打回「只开第一项」（2026-09-25 用户报告）。
    // 默认全部折叠（2026-09-25 用户要求）。
    openSections.value = [];
  } catch (err) {
    toastApiError(toast, err);
  }
}

function resetToDefaults(): void {
  const byKey = new Map(rawFields.value.map((f) => [f.key, f]));
  const out: Record<string, unknown> = {};
  for (const [key, current] of Object.entries(values.value)) {
    const f = byKey.get(key);
    if (!f) {
      out[key] = current; // JSON 源码等方式加进来的自定义键，原样保留
      continue;
    }
    if (f.sensitive) {
      out[key] = ''; // 敏感键空串 = 保存时不修改，不会真的清掉已设密钥
      continue;
    }
    if (f.type === 'bool') {
      // schema 的 default 是 _env_bool 的字面量参数（"true"/"false" 字符串）
      out[key] = String(f.default ?? '').toLowerCase() === 'true';
    } else {
      out[key] = f.default ?? '';
    }
  }
  values.value = out;
  toast.info('已恢复为默认值；确认后点击保存（保存后自动重启生效）');
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
  let needRestart = false;
  try {
    const data = await unwrap<{ restart_required: boolean }>(api.put('/config', changed));
    saved.value = { ...values.value };
    needRestart = data.restart_required;
    toast.success(needRestart ? '已保存，正在重启生效…' : '已保存');
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    busy.value = false;
  }
  // 保存即自动重启（2026-09-25 用户要求）：端点三槽化之后重启已由接任进程
  // 机制兜底，无壳直启也不会失联，不再让用户手动二选一。
  if (needRestart) await restartNow();
}

async function restartNow(): Promise<void> {
  try {
    // ok=false = 派生接任进程失败、Bot 刻意未停止（manual 兜底），必须如实提示，
    // 不能像成功那样只说「等待恢复」——站点不会自己回来（2026-09-24 实测）。
    const data = await unwrap<{ ok: boolean; error?: string }>(
      api.post('/system/restart'),
    );
    if (data.ok) {
      toast.success('已请求重启，等待服务恢复…');
    } else {
      toast.error(
        `无法自动重启（${data.error ?? '未知原因'}）。Bot 未停止，可继续使用；如需重启请在启动它的终端手动操作。`,
      );
    }
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
      <v-spacer />
      <v-text-field
        v-model="search"
        label="搜索配置键"
        density="compact"
        hide-details
        clearable
        style="max-width: 16rem"
      />
      <v-btn variant="text" prepend-icon="mdi-restore" @click="resetToDefaults">
        恢复默认值
      </v-btn>
      <v-btn variant="text" prepend-icon="mdi-code-json" @click="openJson">
        JSON 源码
      </v-btn>
      <v-btn color="primary" :loading="busy" :disabled="!dirty" @click="save">保存</v-btn>
    </div>

    <div v-if="dirty" class="unsaved-pill mb-3">
      有未保存的修改
      <v-btn size="x-small" variant="text" @click="values = { ...saved }">放弃</v-btn>
    </div>

    <v-expansion-panels v-model="openSections" multiple>
      <v-expansion-panel
        v-for="[stem, fields] in groups"
        :key="stem"
        :value="stem"
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
