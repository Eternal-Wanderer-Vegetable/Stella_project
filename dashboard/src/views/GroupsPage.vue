<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

// 群组页（方案 §6.11）：白名单群 + 空间绑定 + 运行期静音
interface GroupItem {
  group_id: number;
  space: string;
  messages: number;
  proactive_muted: boolean;
}
interface SpaceItem {
  name: string;
}

const groups = ref<GroupItem[]>([]);
const spaces = ref<string[]>([]);
const toast = useToast();

async function load(): Promise<void> {
  try {
    const [g, s] = await Promise.all([
      unwrap<{ groups: GroupItem[] }>(api.get('/groups')),
      unwrap<{ spaces: SpaceItem[] }>(api.get('/spaces')),
    ]);
    groups.value = g.groups;
    spaces.value = s.spaces.map((x) => x.name);
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function changeSpace(group: GroupItem, space: string): Promise<void> {
  try {
    await unwrap(
      api.put('/groups/bindings', [
        ...groups.value.filter((g) => g.group_id !== group.group_id).map((g) => ({ group_id: g.group_id, space: g.space })),
        { group_id: group.group_id, space },
      ]),
    );
    toast.success('绑定已更新');
    await load();
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

onMounted(load);
</script>

<template>
  <v-container fluid class="pa-6">
    <h1 class="text-h5 font-weight-bold mb-1">群组与绑定</h1>
    <p class="text-body-2 text-medium-emphasis mb-4">
      群绑定写入空间（立即生效）；白名单变更写入 .env（需重启）。
    </p>
    <v-card class="pa-2">
      <v-table v-if="groups.length">
        <thead>
          <tr><th>群号</th><th>空间</th><th>消息数</th><th>主动发言</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="g in groups" :key="g.group_id">
            <td>{{ g.group_id }}</td>
            <td>
              <v-select
                :model-value="g.space"
                :items="spaces"
                density="compact"
                hide-details
                style="max-width: 12rem"
                @update:model-value="(v: string) => changeSpace(g, v)"
              />
            </td>
            <td>{{ g.messages }}</td>
            <td>
              <v-chip :color="g.proactive_muted ? 'error' : 'success'" size="x-small" variant="tonal">
                {{ g.proactive_muted ? '已静音' : '正常' }}
              </v-chip>
            </td>
            <td>
              <v-btn
                size="small"
                variant="text"
                :color="g.proactive_muted ? 'success' : 'error'"
                @click="toggleMute(g)"
              >
                {{ g.proactive_muted ? '取消静音' : '静音' }}
              </v-btn>
            </td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis pa-4">
        还没有绑定群。在配置页设置 ALLOWED_GROUPS，或在这里通过绑定向导添加。
      </div>
    </v-card>
  </v-container>
</template>
