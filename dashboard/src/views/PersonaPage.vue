<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

// 人格与空间页（方案 §6.8）：空间卡片网格 + prompt 编辑 + 群绑定；出厂默认只读
interface SpaceItem {
  name: string;
  qq_groups: number[];
  prompt_chars: number;
  prompt_preview: string;
  prompt_file: string;
}

const spaces = ref<SpaceItem[]>([]);
const defaultPrompt = ref('');
const editing = ref<SpaceItem | null>(null);
const editingText = ref('');
const createDialog = ref(false);
const newName = ref('');
const newPrompt = ref('');
const bindingDialog = ref(false);
const bindingText = ref('');
const toast = useToast();

async function load(): Promise<void> {
  try {
    const [s, d] = await Promise.all([
      unwrap<{ spaces: SpaceItem[] }>(api.get('/spaces')),
      unwrap<{ text: string }>(api.get('/spaces/default')),
    ]);
    spaces.value = s.spaces;
    defaultPrompt.value = d.text;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function openEdit(space: SpaceItem): Promise<void> {
  editing.value = space;
  editingText.value = '';
  try {
    const data = await unwrap<{ text: string }>(api.get(`/spaces/${space.name}/prompt`));
    editingText.value = data.text;
  } catch {
    editingText.value = '';
  }
}

async function saveEdit(): Promise<void> {
  if (!editing.value) return;
  try {
    const r = await api.put(`/spaces/${editing.value.name}/prompt`, { text: editingText.value });
    if (r.data.status !== 'ok') throw new Error(r.data.message);
    toast.success('人格已保存（无需重启）');
    editing.value = null;
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function create(): Promise<void> {
  try {
    await unwrap(api.post('/spaces', { name: newName.value, system_prompt: newPrompt.value }));
    toast.success('空间已创建');
    createDialog.value = false;
    newName.value = '';
    newPrompt.value = '';
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function remove(space: SpaceItem): Promise<void> {
  try {
    await unwrap(api.delete(`/spaces/${space.name}`));
    toast.success('已删除');
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openBindings(space: SpaceItem): void {
  editing.value = space;
  bindingText.value = space.qq_groups.join(', ');
  bindingDialog.value = true;
}

async function saveBindings(): Promise<void> {
  if (!editing.value) return;
  const groups = bindingText.value
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n));
  try {
    await unwrap(api.put(`/spaces/${editing.value.name}/bindings`, { qq_groups: groups }));
    toast.success('绑定已保存');
    bindingDialog.value = false;
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

onMounted(load);
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">人格与空间</h1>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="createDialog = true">新建空间</v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      空间 = 人格的载体：同一空间内的群共享长期记忆与画像。一个群只属于一个空间。
    </p>

    <v-row>
      <v-col v-for="space in spaces" :key="space.name" cols="12" sm="6" md="4">
        <v-card class="pa-4 fill-height d-flex flex-column">
          <div class="text-subtitle-1 font-weight-medium">{{ space.name }}</div>
          <div class="text-caption text-medium-emphasis mb-2">
            绑定群：{{ space.qq_groups.length ? space.qq_groups.join('、') : '（无）' }} ·
            {{ space.prompt_chars }} 字
          </div>
          <div class="text-body-2 text-medium-emphasis flex-grow-1">
            {{ space.prompt_preview || '（空）' }}
          </div>
          <div class="d-flex ga-1 mt-3">
            <v-btn size="small" variant="tonal" @click="openEdit(space)">编辑人格</v-btn>
            <v-btn size="small" variant="text" @click="openBindings(space)">群绑定</v-btn>
            <v-spacer />
            <v-btn size="small" icon="mdi-delete" variant="text" color="error" @click="remove(space)" />
          </div>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="pa-4 mt-2">
      <div class="text-subtitle-1 font-weight-medium mb-2">出厂默认人格（只读）</div>
      <div class="text-body-2 text-medium-emphasis default-prompt">
        {{ defaultPrompt.slice(0, 300) }}…
      </div>
    </v-card>

    <!-- 人格编辑对话框 -->
    <v-dialog
      :model-value="editing !== null"
      width="760"
      @update:model-value="editing = null"
    >
      <v-card v-if="editing">
        <v-card-title>编辑 {{ editing.name }} 的人格</v-card-title>
        <v-card-text>
          <v-textarea v-model="editingText" rows="16" density="compact" hide-details />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="editing = null">取消</v-btn>
          <v-btn color="primary" @click="saveEdit">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 群绑定对话框 -->
    <v-dialog v-model="bindingDialog" width="460">
      <v-card>
        <v-card-title>绑定群到 {{ editing?.name }}</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="bindingText"
            label="QQ 群号（逗号分隔）"
            hint="群号会自动从其它空间摘除（一个群只属于一个空间）"
            persistent-hint
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="bindingDialog = false">取消</v-btn>
          <v-btn color="primary" @click="saveBindings">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 新建空间 -->
    <v-dialog v-model="createDialog" width="560">
      <v-card>
        <v-card-title>新建空间</v-card-title>
        <v-card-text>
          <v-text-field v-model="newName" label="空间名（字母/数字/-/_）" />
          <v-textarea v-model="newPrompt" label="初始人格（可留空，稍后编辑）" rows="6" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDialog = false">取消</v-btn>
          <v-btn color="primary" @click="create">创建</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
.default-prompt {
  max-height: 140px;
  overflow: hidden;
}
</style>
