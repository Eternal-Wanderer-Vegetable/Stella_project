<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import ConversationPolicyEditor from '@/components/ConversationPolicyEditor.vue';
import { toastApiError, useToast } from '@/stores/toast';
import { useSystemStore } from '@/stores/system';

interface SpaceItem {
  name: string;
  qq_groups: number[];
}
interface GroupItem {
  group_id: number;
  space: string;
  messages: number;
  proactive_muted: boolean;
}
interface ConfigField {
  key: string;
  current_value: string | null;
  default: string | number | null;
}

const WEBCHAT_SPACE = 'webchat';
const spaces = ref<SpaceItem[]>([]);
const groups = ref<GroupItem[]>([]);
const editing = ref<SpaceItem | null>(null);
const editingText = ref('');
const boundGroupIds = ref<number[]>([]);
const spaceSettingsDialog = ref(false);
const spaceSettingsLoading = ref(false);
const spaceSettingsLoaded = ref(false);
const spaceSettingsSaving = ref(false);
const boundGroupsError = ref('');

const createDialog = ref(false);
const newName = ref('');
const newPrompt = ref('');

const allowedGroupsDialog = ref(false);
const allowedGroupIds = ref<number[]>([]);
const allowedGroupInput = ref('');
const allowedGroupsLoading = ref(false);
const allowedGroupsLoaded = ref(false);
const allowedGroupsSaving = ref(false);
const allowedGroupsError = ref('');

const toast = useToast();
const system = useSystemStore();
const loadError = ref(false);
const loadedGeneration = ref<string | null>(null);
const cacheStale = computed(() =>
  loadError.value
  || (system.managed && (
    system.coreUnavailable
    || Boolean(loadedGeneration.value && system.coreGeneration !== loadedGeneration.value)
  )),
);

const availableBindingGroupIds = computed(() => {
  const ids = new Set(groups.value.map((group) => group.group_id));
  // Keep legacy bindings visible so they can be deliberately removed or retained.
  editing.value?.qq_groups.forEach((groupId) => ids.add(groupId));
  return [...ids].sort((left, right) => left - right);
});

function parseConfiguredGroupIds(text: string): { ids: number[]; invalidCount: number } {
  const values = text.split(/[,，\s]+/).filter(Boolean);
  const ids = new Set<number>();
  let invalidCount = 0;
  for (const value of values) {
    if (!/^\d+$/.test(value)) {
      invalidCount += 1;
      continue;
    }
    const id = Number(value);
    if (!Number.isSafeInteger(id) || id <= 0) {
      invalidCount += 1;
      continue;
    }
    ids.add(id);
  }
  return { ids: [...ids].sort((left, right) => left - right), invalidCount };
}

async function loadPage(): Promise<void> {
  try {
    await system.refreshStatus();
    const [spaceData, groupData] = await Promise.all([
      unwrap<{ spaces: SpaceItem[] }>(api.get('/spaces')),
      unwrap<{ groups: GroupItem[] }>(api.get('/groups')),
    ]);
    spaces.value = spaceData.spaces.filter((space) => space.name.toLowerCase() !== WEBCHAT_SPACE);
    groups.value = groupData.groups;
    loadedGeneration.value = system.coreGeneration;
    loadError.value = false;
  } catch (err) {
    loadError.value = true;
    toastApiError(toast, err);
  }
}

async function changeGroupSpace(group: GroupItem, space: string): Promise<void> {
  try {
    await unwrap(
      api.put('/groups/bindings', [
        ...groups.value
          .filter((item) => item.group_id !== group.group_id)
          .map((item) => ({ group_id: item.group_id, space: item.space })),
        { group_id: group.group_id, space },
      ]),
    );
    toast.success('群组空间已更新');
    await loadPage();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function toggleMute(group: GroupItem): Promise<void> {
  try {
    await unwrap(api.post(`/groups/${group.group_id}/${group.proactive_muted ? 'unmute' : 'mute'}`));
    group.proactive_muted = !group.proactive_muted;
    toast.success(group.proactive_muted ? '已静音（立即生效）' : '已取消静音');
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function openSpaceSettings(space: SpaceItem): Promise<void> {
  if (space.name.toLowerCase() === WEBCHAT_SPACE) return;
  editing.value = space;
  editingText.value = '';
  boundGroupIds.value = [...space.qq_groups];
  boundGroupsError.value = '';
  spaceSettingsLoaded.value = false;
  spaceSettingsDialog.value = true;
  spaceSettingsLoading.value = true;
  try {
    const data = await unwrap<{ text: string }>(api.get(`/spaces/${space.name}/prompt`));
    if (editing.value?.name === space.name) {
      editingText.value = data.text;
      spaceSettingsLoaded.value = true;
    }
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    if (editing.value?.name === space.name) spaceSettingsLoading.value = false;
  }
}

function closeSpaceSettings(): void {
  spaceSettingsDialog.value = false;
  editing.value = null;
  spaceSettingsLoaded.value = false;
}

async function saveSpaceSettings(): Promise<void> {
  if (!editing.value || !spaceSettingsLoaded.value) return;
  const groups = [...new Set(boundGroupIds.value)];
  if (groups.some((groupId) => !Number.isSafeInteger(groupId) || groupId <= 0)) {
    boundGroupsError.value = '请选择有效的 QQ 群号。';
    return;
  }

  const name = editing.value.name;
  spaceSettingsSaving.value = true;
  let promptSaved = false;
  try {
    await unwrap(api.put(`/spaces/${name}/prompt`, { text: editingText.value }));
    promptSaved = true;
    await unwrap(api.put(`/spaces/${name}/bindings`, { qq_groups: groups }));
    toast.success('空间设置已保存');
    closeSpaceSettings();
    await loadPage();
  } catch (err) {
    if (promptSaved) {
      toast.warning('人格已保存，但群绑定保存失败。请检查后重试。');
    } else {
      toastApiError(toast, err);
    }
  } finally {
    spaceSettingsSaving.value = false;
  }
}

async function create(): Promise<void> {
  const name = newName.value.trim();
  if (name.toLowerCase() === WEBCHAT_SPACE) {
    toast.warning('WebChat 专属空间请在“聊天”界面设置。');
    return;
  }
  try {
    await unwrap(api.post('/spaces', { name, system_prompt: newPrompt.value }));
    toast.success('空间已创建');
    createDialog.value = false;
    newName.value = '';
    newPrompt.value = '';
    await loadPage();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function remove(space: SpaceItem): Promise<void> {
  if (space.name.toLowerCase() === WEBCHAT_SPACE) return;
  try {
    await unwrap(api.delete(`/spaces/${space.name}`));
    toast.success('已删除');
    await loadPage();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function openAllowedGroups(): Promise<void> {
  allowedGroupsDialog.value = true;
  allowedGroupsLoaded.value = false;
  allowedGroupsError.value = '';
  allowedGroupsLoading.value = true;
  try {
    const config = await unwrap<{ fields: ConfigField[] }>(api.get('/config'));
    const field = config.fields.find((item) => item.key === 'ALLOWED_GROUPS');
    if (!field) throw new Error('当前配置中未找到 ALLOWED_GROUPS');
    const configuredGroups = parseConfiguredGroupIds(field.current_value ?? String(field.default ?? ''));
    allowedGroupIds.value = configuredGroups.ids;
    allowedGroupInput.value = '';
    if (configuredGroups.invalidCount) {
      allowedGroupsError.value = `原配置中有 ${configuredGroups.invalidCount} 个无效条目，已跳过；保存时将按下方标签重写。`;
    }
    allowedGroupsLoaded.value = true;
  } catch (err) {
    allowedGroupsDialog.value = false;
    toastApiError(toast, err);
  } finally {
    allowedGroupsLoading.value = false;
  }
}

function addAllowedGroup(): void {
  const value = allowedGroupInput.value.trim();
  if (!value) return;
  if (!/^\d+$/.test(value)) {
    allowedGroupsError.value = '每次请输入一个正整数群号，再按 Enter 添加。';
    return;
  }
  const groupId = Number(value);
  if (!Number.isSafeInteger(groupId) || groupId <= 0) {
    allowedGroupsError.value = '群号必须是正整数。';
    return;
  }
  if (allowedGroupIds.value.includes(groupId)) {
    toast.warning(`群号 ${groupId} 已添加`);
  } else {
    allowedGroupIds.value = [...allowedGroupIds.value, groupId].sort((left, right) => left - right);
  }
  allowedGroupInput.value = '';
  allowedGroupsError.value = '';
}

function removeAllowedGroup(groupId: number): void {
  allowedGroupIds.value = allowedGroupIds.value.filter((value) => value !== groupId);
}

async function restartNow(): Promise<void> {
  try {
    const data = await unwrap<{ ok: boolean; error?: string }>(api.post('/system/restart'));
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

async function saveAllowedGroups(): Promise<void> {
  if (!allowedGroupsLoaded.value) return;
  if (allowedGroupInput.value.trim()) {
    allowedGroupsError.value = '请先按 Enter 或点击加号，将群号添加为标签。';
    return;
  }

  allowedGroupsSaving.value = true;
  let needRestart = false;
  try {
    const data = await unwrap<{ restart_required: boolean }>(
      api.put('/config', { ALLOWED_GROUPS: allowedGroupIds.value.join(',') }),
    );
    allowedGroupsDialog.value = false;
    needRestart = data.restart_required;
    toast.success(needRestart ? '允许群组已保存，正在重启生效…' : '允许群组已保存');
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    allowedGroupsSaving.value = false;
  }
  if (needRestart) await restartNow();
}

onMounted(loadPage);
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4 flex-wrap ga-2">
      <h1 class="text-h5 font-weight-bold">群组与人格</h1>
      <v-spacer />
      <v-btn variant="tonal" prepend-icon="mdi-account-group-outline" @click="openAllowedGroups">
        编辑 ALLOWED_GROUPS
      </v-btn>
      <v-btn color="primary" prepend-icon="mdi-plus" @click="createDialog = true">新建空间</v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      在同一处管理群组所属空间、主动发言状态，以及空间的人格和群绑定。ALLOWED_GROUPS 控制 Stella 可响应的 QQ 群。
    </p>
    <v-alert v-if="cacheStale" type="warning" variant="tonal" class="mb-3">
      群组与空间列表可能来自旧核心缓存。核心恢复后可重新载入。
      <v-btn size="small" variant="text" @click="loadPage">重新载入</v-btn>
    </v-alert>
    <ConversationPolicyEditor :space-names="spaces.map((space) => space.name)" />

    <v-card class="mb-6">
      <v-card-title class="d-flex align-center ga-2">
        <span>群组</span>
        <v-chip size="small" variant="tonal">{{ groups.length }}</v-chip>
      </v-card-title>
      <v-card-subtitle>调整群组所属空间；主动发言静音状态会立即生效。</v-card-subtitle>
      <v-table v-if="groups.length">
        <thead>
          <tr><th>群号</th><th>所属空间</th><th>消息数</th><th>主动发言</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="group in groups" :key="group.group_id">
            <td>{{ group.group_id }}</td>
            <td>
              <v-select
                v-if="spaces.length"
                :model-value="group.space"
                :items="[...new Set([...spaces.map((space) => space.name), group.space])]"
                density="compact"
                hide-details
                style="max-width: 14rem"
                @update:model-value="(value: string) => changeGroupSpace(group, value)"
              />
              <span v-else class="text-caption text-medium-emphasis">请先新建空间</span>
            </td>
            <td>{{ group.messages }}</td>
            <td>
              <v-chip :color="group.proactive_muted ? 'error' : 'success'" size="x-small" variant="tonal">
                {{ group.proactive_muted ? '已静音' : '正常' }}
              </v-chip>
            </td>
            <td>
              <v-btn
                size="small"
                variant="text"
                :color="group.proactive_muted ? 'success' : 'error'"
                @click="toggleMute(group)"
              >
                {{ group.proactive_muted ? '取消静音' : '静音' }}
              </v-btn>
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis pa-4">
        当前没有已允许的群组。可使用上方“编辑 ALLOWED_GROUPS”添加群号。
      </div>
    </v-card>

    <div class="d-flex align-center ga-2 mb-3">
      <h2 class="text-h6 font-weight-medium">空间人格</h2>
      <v-chip size="small" variant="tonal">{{ spaces.length }}</v-chip>
    </div>

    <v-row>
      <v-col v-for="space in spaces" :key="space.name" cols="12" sm="6" md="4">
        <v-card class="pa-4 fill-height d-flex flex-column">
          <div class="text-subtitle-1 font-weight-medium">{{ space.name }}</div>
          <div class="text-caption text-medium-emphasis mb-2">绑定群</div>
          <div v-if="space.qq_groups.length" class="d-flex flex-wrap ga-1 mb-3">
            <v-chip v-for="group in space.qq_groups" :key="group" size="small" variant="tonal">
              {{ group }}
            </v-chip>
          </div>
          <div v-else class="text-body-2 text-medium-emphasis mb-3">尚未绑定群</div>
          <v-spacer />
          <div class="d-flex align-center ga-1 mt-2">
            <v-btn
              size="small"
              variant="tonal"
              prepend-icon="mdi-cog-outline"
              @click="openSpaceSettings(space)"
            >
              空间设置
            </v-btn>
            <v-spacer />
            <v-btn size="small" icon="mdi-delete" variant="text" color="error" @click="remove(space)" />
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- 空间设置：人格与群绑定在同一处编辑、保存。 -->
    <v-dialog
      :model-value="spaceSettingsDialog"
      max-width="880"
      @update:model-value="(open: boolean) => { if (!open) closeSpaceSettings(); }"
    >
      <v-card v-if="editing">
        <v-card-title>空间设置 · {{ editing.name }}</v-card-title>
        <v-card-text>
          <v-progress-linear v-if="spaceSettingsLoading" indeterminate color="primary" class="mb-4" />
          <div class="text-subtitle-2 font-weight-medium mb-2">人格</div>
          <v-textarea
            v-model="editingText"
            label="人格提示词"
            rows="12"
            auto-grow
            :disabled="spaceSettingsLoading || spaceSettingsSaving"
          />
          <v-divider class="my-4" />
          <div class="text-subtitle-2 font-weight-medium mb-2">群绑定</div>
          <v-select
            v-model="boundGroupIds"
            :items="availableBindingGroupIds"
            label="选择 QQ 群"
            hint="从已允许的群组中选择；当前空间已有但不在允许列表中的绑定仍可保留或移除。每个群号只能绑定到一个空间。"
            persistent-hint
            multiple
            chips
            closable-chips
            clearable
            :no-data-text="'暂无可选群组，请先在群组列表中添加允许群号。'"
            :error-messages="boundGroupsError ? [boundGroupsError] : []"
            :disabled="spaceSettingsLoading || spaceSettingsSaving"
            @update:model-value="boundGroupsError = ''"
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn :disabled="spaceSettingsSaving" @click="closeSpaceSettings">取消</v-btn>
          <v-btn
            color="primary"
            :loading="spaceSettingsSaving"
            :disabled="!spaceSettingsLoaded || spaceSettingsLoading"
            @click="saveSpaceSettings"
          >
            保存空间设置
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- ALLOWED_GROUPS 是启动期配置，保存后按配置页惯例自动请求重启。 -->
    <v-dialog v-model="allowedGroupsDialog" width="560">
      <v-card>
        <v-card-title>编辑 ALLOWED_GROUPS</v-card-title>
        <v-card-text>
          <v-progress-linear v-if="allowedGroupsLoading" indeterminate color="primary" class="mb-4" />
          <div class="d-flex align-start ga-2">
            <v-text-field
              v-model="allowedGroupInput"
              label="QQ 群号"
              hint="每次输入一个正整数，按 Enter 添加。留空列表表示不允许任何群；保存后重启生效。"
              persistent-hint
              inputmode="numeric"
              :error-messages="allowedGroupsError ? [allowedGroupsError] : []"
              :disabled="allowedGroupsLoading || allowedGroupsSaving || !allowedGroupsLoaded"
              @keydown.enter.prevent="addAllowedGroup"
              @update:model-value="allowedGroupsError = ''"
            />
            <v-btn
              class="mt-2"
              icon="mdi-plus"
              aria-label="添加群号"
              variant="tonal"
              :disabled="allowedGroupsLoading || allowedGroupsSaving || !allowedGroupsLoaded || !allowedGroupInput.trim()"
              @click="addAllowedGroup"
            />
          </div>
          <div v-if="allowedGroupIds.length" class="d-flex flex-wrap ga-2 mt-2">
            <v-chip
              v-for="groupId in allowedGroupIds"
              :key="groupId"
              closable
              :disabled="allowedGroupsSaving"
              @click:close="removeAllowedGroup(groupId)"
            >
              {{ groupId }}
            </v-chip>
          </div>
          <div v-else class="text-body-2 text-medium-emphasis mt-2">尚未添加群号。</div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn :disabled="allowedGroupsSaving" @click="allowedGroupsDialog = false">取消</v-btn>
          <v-btn
            color="primary"
            :loading="allowedGroupsSaving"
            :disabled="allowedGroupsLoading || !allowedGroupsLoaded || !!allowedGroupInput.trim()"
            @click="saveAllowedGroups"
          >
            保存
          </v-btn>
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
