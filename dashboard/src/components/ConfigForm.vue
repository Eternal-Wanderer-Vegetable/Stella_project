<script setup lang="ts">
import { computed } from 'vue';

// Schema 驱动表单渲染器（方案 §10.3）：/config、插件配置、KB/调度对话框共用。
// 输入 = 归一化字段列表，输出 = 受控 values dict（v-model）。
// 字段说明以「问号图标 + 悬停 tooltip」呈现，不再用常驻小字（2026-09-25
// 用户要求：小字可读性太低）。
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
      <!-- bool：单行开关 + 标签 + 说明 tooltip -->
      <div v-if="field.type === 'bool'" class="d-flex align-center ga-2 mb-2">
        <v-switch
          :model-value="Boolean(values[field.key])"
          density="compact"
          color="primary"
          hide-details
          @update:model-value="(v: boolean | null) => setValue(field.key, Boolean(v ?? false))"
        />
        <span class="text-body-2">{{ field.label }}</span>
        <v-tooltip v-if="field.hint" location="top" max-width="30rem">
          <template #activator="{ props: tip }">
            <v-icon
              v-bind="tip"
              icon="mdi-help-circle-outline"
              size="x-small"
              class="text-medium-emphasis stella-tip-icon"
            />
          </template>
          <span class="text-body-2">{{ field.hint }}</span>
        </v-tooltip>
      </div>

      <!-- list：标签行 + 多行输入 -->
      <div v-else-if="field.type === 'list'" class="config-field">
        <div class="config-field-label">
          <span>{{ field.label }}</span>
          <v-tooltip v-if="field.hint" location="top" max-width="30rem">
            <template #activator="{ props: tip }">
              <v-icon
                v-bind="tip"
                icon="mdi-help-circle-outline"
                size="x-small"
                class="text-medium-emphasis stella-tip-icon"
              />
            </template>
            <span class="text-body-2">{{ field.hint }}</span>
          </v-tooltip>
        </div>
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

      <!-- 其余类型：标签行 + 控件（choice/secret/int/float/text/string） -->
      <div v-else class="config-field">
        <div class="config-field-label">
          <span>{{ field.label }}</span>
          <v-tooltip v-if="field.hint" location="top" max-width="30rem">
            <template #activator="{ props: tip }">
              <v-icon
                v-bind="tip"
                icon="mdi-help-circle-outline"
                size="x-small"
                class="text-medium-emphasis stella-tip-icon"
              />
            </template>
            <span class="text-body-2">{{ field.hint }}</span>
          </v-tooltip>
        </div>
        <v-select
          v-if="field.type === 'choice'"
          :model-value="String(values[field.key] ?? '')"
          :items="field.choices ?? []"
          density="compact"
          hide-details
          @update:model-value="(v: string) => setValue(field.key, v)"
        />
        <v-text-field
          v-else-if="field.type === 'secret'"
          :model-value="String(values[field.key] ?? '')"
          type="password"
          autocomplete="new-password"
          prepend-inner-icon="mdi-key-outline"
          density="compact"
          hide-details
          :placeholder="field.hasValue ? '已设置；留空保持不变' : undefined"
          @update:model-value="(v: string) => setValue(field.key, v)"
        />
        <v-text-field
          v-else-if="field.type === 'int' || field.type === 'float'"
          :model-value="String(values[field.key] ?? '')"
          density="compact"
          hide-details
          @update:model-value="(v: string) => setValue(field.key, v)"
        />
        <v-textarea
          v-else-if="field.type === 'text'"
          :model-value="String(values[field.key] ?? '')"
          density="compact"
          rows="3"
          hide-details
          @update:model-value="(v: string) => setValue(field.key, v)"
        />
        <v-text-field
          v-else
          :model-value="String(values[field.key] ?? '')"
          density="compact"
          hide-details
          @update:model-value="(v: string) => setValue(field.key, v)"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.config-field {
  margin-bottom: 0.9rem;
}

.config-field-label {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 4px;
  font-size: 0.85rem;
}

.stella-tip-icon {
  cursor: help;
}
</style>
