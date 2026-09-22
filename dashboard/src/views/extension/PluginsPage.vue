<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';

// 插件页（M1 只读）：清单 + 失败插件 + 能力声明快照；启停/配置/安装属 M3。
// 信息量对齐 v1 GUI 插件页（状态 / 工具 / 可路由 / 退避），并补失败清单。
interface PluginItem {
  plugin_id: string;
  name: string;
  display_name: string | null;
  author: string;
  desc: string;
  version: string;
  repo: string | null;
  root_dir_name: string;
  reserved: boolean;
  activated: boolean;
  handlers: number;
}
interface ProviderItem {
  tool: string;
  kind: string;
  tool_state?: string;
  healthy?: boolean;
}
interface CapabilityItem {
  id: string;
  domain: string;
  source: string;
  route_enabled: boolean;
  routable: boolean;
  auto: boolean;
  examples: number;
  providers: ProviderItem[];
}
interface PluginsPayload {
  plugins: PluginItem[];
  failed: Record<string, string>;
  capabilities: { items?: CapabilityItem[]; missing_tools?: string[] } | null;
}

const data = ref<PluginsPayload | null>(null);
const error = ref('');

async function load(): Promise<void> {
  try {
    data.value = await unwrap<PluginsPayload>(api.get('/plugins'));
    error.value = '';
  } catch (err) {
    error.value = (err as Error).message;
  }
}

onMounted(load);

const failedEntries = computed(() => Object.entries(data.value?.failed ?? {}));
const capabilities = computed<CapabilityItem[]>(() => data.value?.capabilities?.items ?? []);
const missingTools = computed<string[]>(() => data.value?.capabilities?.missing_tools ?? []);

function toolSummary(cap: CapabilityItem): string {
  const tools = cap.providers.map((p) => p.tool).filter(Boolean);
  return tools.length ? tools.join('、') : '（无工具）';
}
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-1">
      <h1 class="text-h5 font-weight-bold">扩展 · 插件</h1>
      <v-chip size="small" variant="tonal" color="secondary" class="ml-3">M1 · 只读清单</v-chip>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      AstrBot 兼容插件（data/plugins/）的加载状态与能力声明。启停 / 重载 / 配置 / 安装在 M3 上线。
    </p>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <v-alert
      v-if="failedEntries.length"
      type="error"
      variant="tonal"
      class="mb-3"
    >
      <div v-for="[dir, reason] in failedEntries" :key="dir">
        <b>{{ dir }}</b> 加载失败：{{ reason }}
      </div>
    </v-alert>

    <v-card class="pa-2 mb-4">
      <v-table density="compact" v-if="data?.plugins.length">
        <thead>
          <tr>
            <th>插件</th><th>版本</th><th>作者</th><th>处理器</th>
            <th>激活</th><th>内置</th><th>目录</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in data.plugins" :key="p.plugin_id">
            <td>
              <div class="text-body-2">{{ p.display_name || p.name }}</div>
              <div class="text-caption text-medium-emphasis">{{ p.desc }}</div>
            </td>
            <td>{{ p.version || '—' }}</td>
            <td>{{ p.author || '—' }}</td>
            <td>{{ p.handlers }}</td>
            <td>
              <v-chip :color="p.activated ? 'success' : 'error'" size="x-small" variant="tonal">
                {{ p.activated ? '已激活' : '未激活' }}
              </v-chip>
            </td>
            <td>{{ p.reserved ? '是' : '否' }}</td>
            <td class="text-caption">{{ p.root_dir_name }}</td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis pa-4">
        没有已加载的插件。把 AstrBot 插件放进数据目录的 data/plugins/ 后重启即可。
      </div>
    </v-card>

    <v-card class="pa-4">
      <div class="text-subtitle-1 font-weight-medium mb-2">能力声明（Router 路由视角）</div>
      <v-alert
        v-if="missingTools.length"
        type="warning"
        variant="tonal"
        density="compact"
        class="mb-2"
      >
        声明指向了不存在的工具（静默失效的头号原因）：{{ missingTools.join('、') }}
      </v-alert>
      <v-table density="compact" v-if="capabilities.length">
        <thead>
          <tr>
            <th>能力</th><th>域</th><th>来源</th><th>可路由</th><th>工具</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="cap in capabilities" :key="cap.id">
            <td>
              {{ cap.id }}
              <v-chip v-if="cap.auto" size="x-small" variant="outlined" class="ml-1">自动派生</v-chip>
            </td>
            <td>{{ cap.domain }}</td>
            <td>{{ cap.source }}</td>
            <td>
              <v-chip
                :color="cap.routable ? 'success' : 'default'"
                size="x-small"
                variant="tonal"
              >
                {{ cap.routable ? '可路由' : '否' }}
              </v-chip>
            </td>
            <td class="text-caption">{{ toolSummary(cap) }}</td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis">
        没有能力声明（config/capabilities/ 或插件自带 capability.toml）。
      </div>
    </v-card>
  </v-container>
</template>
