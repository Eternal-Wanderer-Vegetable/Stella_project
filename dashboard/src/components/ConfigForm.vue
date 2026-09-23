<script setup lang="ts">
import { computed } from 'vue';

// Schema 驱动表单渲染器（方案 §10.3）：/config、插件配置、KB/调度对话框共用。
// 输入 = 归一化字段列表，输出 = 受控 values dict（v-model）。
export interface FormField {
  key: string;
  label: string;
  type: 'string' | 'int' | 'float' | 'bool' | 'choice' | 'secret' | 'text' | 'list';
  choices?: string[];
  default?: string | number | boolean | null;
  hint?: string;
  /** 敏感键：读端只给 has_value；提交空串 = 不修改 */
  hasValue?: boolean;
}

const props = defineProps<{ fields: FormField[]; modelValue: Record<string, unknown> }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: Record<string, unknown>): void }>();

const values = computed(() => props.modelValue);

function setValue(key: string, v: unknown): void {
  emit('update:modelValue', { ...values.value, [key]: v });
}

function getList(key: string): string[] {
  const v = values.value[key];
  return Array.isArray(v) ? v.map(String) : [];
}
function setList(key: string, items: string[]): void {
  setValue(key, items);
}
function addListItem(key: string): void {
  setList(key, [...getList(key), '']);
}
function removeListItem(key: string, index: number): void {
  setList(key, getList(key).filter((_, i) => i !== index));
}
function setListItem(key: string, index: number, value: string): void {
  const items = [...getList(key)];
  items[index] = value;
  setList(key, items);
}
</script>

<template>
  <div class="config-form">
    <template v-for="field in fields" :key="field.key">
      <!-- bool -->
      <v-switch
        v-if="field.type === 'bool'"
        :model-value="Boolean(values[field.key])"
        :label="field.label"
        :hint="field.hint"
        persistent-hint
        density="compact"
        color="primary"
        @update:model-value="(v: boolean | null) => setValue(field.key, Boolean(v ?? false))"
      />
      <!-- choice -->
      <v-select
        v-else-if="field.type === 'choice'"
        :model-value="String(values[field.key] ?? '')"
        :items="field.choices ?? []"
        :label="field.label"
        :hint="field.hint"
        persistent-hint
        density="compact"
        @update:model-value="(v: string) => setValue(field.key, v)"
      />
      <!-- secret -->
      <v-text-field
        v-else-if="field.type === 'secret'"
        :model-value="String(values[field.key] ?? '')"
        :label="field.label"
        :hint="field.hint ?? (field.hasValue ? '已设置；留空保持不变' : undefined)"
        persistent-hint
        density="compact"
        type="password"
        autocomplete="new-password"
        prepend-inner-icon="mdi-key-outline"
        @update:model-value="(v: string) => setValue(field.key, v)"
      />
      <!-- int / float -->
      <v-text-field
        v-else-if="field.type === 'int' || field.type === 'float'"
        :model-value="String(values[field.key] ?? '')"
        :label="field.label"
        :hint="field.hint"
        persistent-hint
        density="compact"
        @update:model-value="(v: string) => setValue(field.key, v)"
      />
      <!-- text 多行 -->
      <v-textarea
        v-else-if="field.type === 'text'"
        :model-value="String(values[field.key] ?? '')"
        :label="field.label"
        :hint="field.hint"
        persistent-hint
        density="compact"
        rows="3"
        @update:model-value="(v: string) => setValue(field.key, v)"
      />
      <!-- list -->
      <div v-else-if="field.type === 'list'" class="mb-3">
        <div class="text-caption text-medium-emphasis mb-1">{{ field.label }}</div>
        <div v-for="(_, i) in getList(field.key)" :key="i" class="d-flex ga-2 mb-1">
          <v-text-field
            :model-value="getList(field.key)[i]"
            density="compact"
            hide-details
            @update:model-value="(v: string) => setListItem(field.key, i, v)"
          />
          <v-btn icon="mdi-close" size="x-small" variant="text" @click="removeListItem(field.key, i)" />
        </div>
        <v-btn size="x-small" variant="tonal" prepend-icon="mdi-plus" @click="addListItem(field.key)">
          添加
        </v-btn>
      </div>
      <!-- 默认 string -->
      <v-text-field
        v-else
        :model-value="String(values[field.key] ?? '')"
        :label="field.label"
        :hint="field.hint"
        persistent-hint
        density="compact"
        @update:model-value="(v: string) => setValue(field.key, v)"
      />
    </template>
  </div>
</template>
