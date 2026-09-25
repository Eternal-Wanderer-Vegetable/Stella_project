<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { marked } from 'marked';
import DOMPurify from 'dompurify';

import { api, unwrap } from '@/api/http';
import ConfigForm, { type FormField } from '@/components/ConfigForm.vue';
import { toastApiError, useToast } from '@/stores/toast';

// 扩展页（方案 §6.5）：插件（已装/市场/源）/ MCP / Skills 四个功能面
type Tab = 'plugins' | 'market' | 'mcp' | 'skills';
const tab = ref<Tab>('plugins');
const toast = useToast();
const busy = ref(false);

interface PluginItem {
  plugin_id: string; name: string; display_name: string | null; author: string;
  desc: string; version: string; repo: string | null; root_dir_name: string;
  reserved: boolean; activated: boolean; handlers: number;
}
interface PluginsPayload {
  plugins: PluginItem[]; failed: Record<string, string>;
  capabilities: { items?: { id: string; routable: boolean; domain: string }[] } | null;
}
const plugins = ref<PluginsPayload | null>(null);
const disabled = ref<string[]>([]);
const readme = ref('');
const readmeName = ref('');
const configDialog = ref(false);
const configPlugin = ref('');
const configSchema = ref<Record<string, unknown>>({});
const configValues = ref<Record<string, unknown>>({});
const installDialog = ref(false);
const installSource = ref<'github' | 'url'>('github');
const installRepo = ref('');
const installUrl = ref('');
const installResult = ref<string>('');

// 市场多源
interface MarketSource { id: string; name: string; url: string; enabled: boolean }
interface MarketPlugin { name: string; desc: string; author: string; version: string; repo: string; source_id: string }
const sources = ref<MarketSource[]>([]);
const market = ref<{ plugins: MarketPlugin[]; source_errors: Record<string, string> } | null>(null);
const newSource = ref({ id: '', name: '', url: '' });

async function loadPlugins(): Promise<void> {
  try {
    plugins.value = await unwrap<PluginsPayload>(api.get('/plugins'));
    const s = await unwrap<{ sources: MarketSource[] }>(api.get('/plugin-sources'));
    sources.value = s.sources;
  } catch (err) {
    toastApiError(toast, err);
  }
}

function toAstrbotFields(schema: Record<string, unknown>): FormField[] {
  const fields: FormField[] = [];
  for (const [key, meta] of Object.entries(schema)) {
    if (key.startsWith('_')) continue;
    const m = (meta ?? {}) as Record<string, unknown>;
    const type = String(m.type ?? 'string');
    const base = { key, label: key, hint: String(m.description ?? '') };
    if (type === 'bool') fields.push({ ...base, type: 'bool' });
    else if (type === 'int') fields.push({ ...base, type: 'int' });
    else if (type === 'float') fields.push({ ...base, type: 'float' });
    else if (type === 'string' && String(m.hint ?? '').includes('password'))
      fields.push({ ...base, type: 'secret' });
    else fields.push({ ...base, type: 'string' });
  }
  return fields;
}

async function openConfig(plugin: PluginItem): Promise<void> {
  try {
    const data = await unwrap<{ schema: Record<string, unknown>; config: Record<string, unknown> }>(
      api.get('/plugins/config', { params: { plugin_id: plugin.plugin_id } }),
    );
    configPlugin.value = plugin.plugin_id;
    configSchema.value = data.schema;
    configValues.value = data.config;
    configDialog.value = true;
  } catch (err) {
    toastApiError(toast, err);
  }
}

const configFields = computed(() => toAstrbotFields(configSchema.value));

async function saveConfig(): Promise<void> {
  try {
    await unwrap(api.put('/plugins/config', { plugin_id: configPlugin.value, config: configValues.value }));
    toast.success('插件配置已保存');
    configDialog.value = false;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function toggle(plugin: PluginItem): Promise<void> {
  const dirName = plugin.root_dir_name;
  const isEnabled = !disabled.value.includes(dirName);
  try {
    await unwrap(api.patch('/plugins/enabled', { plugin_id: dirName, enabled: !isEnabled }));
    if (!isEnabled) disabled.value = disabled.value.filter((d) => d !== dirName);
    else disabled.value = [...disabled.value, dirName];
    toast.success(isEnabled ? '已禁用（重启后卸载；重载可即时）' : '已启用（重启后生效）');
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function reload(plugin: PluginItem): Promise<void> {
  try {
    await unwrap(api.post('/plugins/reload', { plugin_id: plugin.plugin_id }));
    toast.success('已重载');
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function uninstall(plugin: PluginItem): Promise<void> {
  try {
    await unwrap(api.delete(`/plugins/${plugin.plugin_id}`));
    toast.success('已卸载');
    await loadPlugins();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function showReadme(plugin: PluginItem): Promise<void> {
  try {
    const data = await unwrap<{ readme: string }>(
      api.get('/plugins/readme', { params: { plugin_id: plugin.plugin_id } }),
    );
    readme.value = data.readme;
    readmeName.value = plugin.plugin_id;
  } catch (err) {
    toastApiError(toast, err);
  }
}

// README 渲染成 GitHub 风格的 HTML（2026-09-25 用户要求，替代原始文档）。
// README 是第三方内容：marked 转换后必须过 DOMPurify 消毒再 v-html，
// 否则一个恶意插件的 README 就能在管理面里执行脚本。
const readmeHtml = computed(() => {
  if (!readme.value) return '';
  const html = marked.parse(readme.value, { async: false });
  return DOMPurify.sanitize(typeof html === 'string' ? html : '');
});

async function install(): Promise<void> {
  busy.value = true;
  installResult.value = '';
  try {
    const data = await unwrap<{ ok: boolean; name?: string; blocking?: unknown[] }>(
      api.post('/plugins/install', {
        source: installSource.value,
        repo: installRepo.value,
        url: installUrl.value,
      }),
    );
    if (data.ok) {
      toast.success(`安装完成：${data.name}`);
      installDialog.value = false;
      await loadPlugins();
    } else {
      installResult.value = '规范校验未通过：' + JSON.stringify(data.blocking ?? [], null, 1);
    }
  } catch (err) {
    installResult.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

async function loadMarket(): Promise<void> {
  try {
    market.value = await unwrap<{ plugins: MarketPlugin[]; source_errors: Record<string, string> }>(
      api.get('/plugins/market'),
    );
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function addSource(): Promise<void> {
  try {
    await unwrap(api.post('/plugin-sources', newSource.value));
    newSource.value = { id: '', name: '', url: '' };
    const s = await unwrap<{ sources: MarketSource[] }>(api.get('/plugin-sources'));
    sources.value = s.sources;
    toast.success('市场源已添加');
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function removeSource(id: string): Promise<void> {
  await unwrap(api.delete(`/plugin-sources/${id}`));
  const s = await unwrap<{ sources: MarketSource[] }>(api.get('/plugin-sources'));
  sources.value = s.sources;
}

async function installFromMarket(plugin: MarketPlugin): Promise<void> {
  installSource.value = 'github';
  installRepo.value = plugin.repo;
  installDialog.value = true;
  installResult.value = '';
}

function switchTab(value: Tab): void {
  tab.value = value;
  if (value === 'market') void loadMarket();
}

// ---------- MCP ----------
interface McpServer {
  server_id: string; enabled: boolean; transport: string;
  command: string; url: string; allowed_tools: string[]; live: Record<string, unknown>;
}
const mcpServers = ref<McpServer[]>([]);
const mcpDialog = ref(false);
const mcpForm = ref({ server_id: '', enabled: true, transport: 'stdio', command: '', args: '', url: '', auth_env: '' });
const mcpTestResult = ref('');

async function loadMcp(): Promise<void> {
  try {
    mcpServers.value = (await unwrap<{ servers: McpServer[] }>(api.get('/mcp/servers'))).servers;
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openMcpEditor(server?: McpServer): void {
  mcpForm.value = server
    ? { server_id: server.server_id, enabled: server.enabled, transport: server.transport,
        command: server.command, args: '', url: server.url, auth_env: '' }
    : { server_id: '', enabled: true, transport: 'stdio', command: '', args: '', url: '', auth_env: '' };
  mcpTestResult.value = '';
  mcpDialog.value = true;
}

async function saveMcp(): Promise<void> {
  try {
    const body = {
      server_id: mcpForm.value.server_id,
      enabled: mcpForm.value.enabled,
      transport: mcpForm.value.transport,
      command: mcpForm.value.command,
      args: mcpForm.value.args.split(/\s+/).filter(Boolean),
      url: mcpForm.value.url,
      auth_env: mcpForm.value.auth_env,
    };
    await unwrap(api.post('/mcp/servers', body));
    toast.success('已保存');
    mcpDialog.value = false;
    await loadMcp();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function deleteMcp(server: McpServer): Promise<void> {
  await unwrap(api.delete(`/mcp/servers/${server.server_id}`));
  await loadMcp();
}

async function testMcp(server: McpServer): Promise<void> {
  try {
    const data = await unwrap<{ ok: boolean; tools: { name: string }[] }>(
      api.post(`/mcp/servers/${server.server_id}/test`),
    );
    mcpTestResult.value = data.ok
      ? `连接成功，发现 ${data.tools.length} 个工具`
      : '连接失败';
  } catch (err) {
    mcpTestResult.value = (err as Error).message;
  }
}

// ---------- Skills ----------
interface SkillItem { name: string; description: string; source: string; trust?: string }
const skills = ref<SkillItem[]>([]);
const skillBody = ref('');
const skillName = ref('');
const skillEditable = ref(false);

async function loadSkills(): Promise<void> {
  try {
    skills.value = (await unwrap<{ skills: SkillItem[] }>(api.get('/skills'))).skills;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function openSkill(skill: SkillItem): Promise<void> {
  try {
    const data = await unwrap<{ body: string; editable: boolean }>(
      api.get(`/skills/${skill.name}`),
    );
    skillName.value = skill.name;
    skillBody.value = data.body;
    skillEditable.value = data.editable;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function saveSkill(): Promise<void> {
  try {
    await unwrap(api.put(`/skills/${skillName.value}`, { body: skillBody.value }));
    toast.success('已保存');
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function deleteSkill(skill: SkillItem): Promise<void> {
  try {
    await unwrap(api.delete(`/skills/${skill.name}`));
    toast.success('已删除');
    await loadSkills();
  } catch (err) {
    toastApiError(toast, err);
  }
}

onMounted(() => {
  void loadPlugins();
  void loadMcp();
  void loadSkills();
});
</script>

<template>
  <v-container fluid class="pa-6">
    <h1 class="text-h5 font-weight-bold mb-1">扩展</h1>
    <p class="text-body-2 text-medium-emphasis mb-4">
      AstrBot 兼容插件 · MCP Servers · Skills
    </p>

    <div class="d-flex ga-2 mb-4">
      <v-btn :variant="tab === 'plugins' ? 'tonal' : 'text'" @click="switchTab('plugins')">插件</v-btn>
      <v-btn :variant="tab === 'market' ? 'tonal' : 'text'" @click="switchTab('market')">市场</v-btn>
      <v-btn :variant="tab === 'mcp' ? 'tonal' : 'text'" @click="switchTab('mcp')">MCP</v-btn>
      <v-btn :variant="tab === 'skills' ? 'tonal' : 'text'" @click="switchTab('skills')">Skills</v-btn>
    </div>

    <!-- 已装插件 -->
    <div v-if="tab === 'plugins'">
      <v-alert
        v-for="(reason, dir) in plugins?.failed ?? {}"
        :key="dir"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-2"
      >
        <b>{{ dir }}</b> 加载失败：{{ reason }}
      </v-alert>
      <v-card class="pa-2">
        <v-table v-if="plugins?.plugins.length">
          <thead>
            <tr><th>插件</th><th>版本</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in plugins.plugins" :key="p.plugin_id">
              <td>
                <div class="text-body-2">{{ p.display_name || p.name }}</div>
                <div class="text-caption text-medium-emphasis">{{ p.desc }}</div>
              </td>
              <td>{{ p.version || '—' }}</td>
              <td>
                <v-chip :color="disabled.includes(p.root_dir_name) ? 'default' : (p.activated ? 'success' : 'warning')"
                        size="x-small" variant="tonal">
                  {{ disabled.includes(p.root_dir_name) ? '已禁用' : (p.activated ? '激活' : '未激活') }}
                </v-chip>
              </td>
              <td>
                <div class="d-flex ga-1 flex-nowrap action-cell">
                  <v-btn size="x-small" variant="text" @click="openConfig(p)">配置</v-btn>
                  <v-btn size="x-small" variant="text" @click="showReadme(p)">README</v-btn>
                  <v-btn size="x-small" variant="text" @click="toggle(p)">
                    {{ disabled.includes(p.root_dir_name) ? '启用' : '禁用' }}
                  </v-btn>
                  <v-btn size="x-small" variant="text" @click="reload(p)">重载</v-btn>
                  <v-btn v-if="!p.reserved" size="x-small" variant="text" color="error" @click="uninstall(p)">卸载</v-btn>
                </div>
              </td>
            </tr>
          </tbody>
        </v-table>
        <div v-else class="text-body-2 text-medium-emphasis pa-4">
          没有插件。安装入口在「市场」标签，或从 GitHub/URL/zip 安装。
          <v-btn size="x-small" variant="tonal" class="ml-2" @click="switchTab('market'); installDialog = true">
            从 GitHub 安装
          </v-btn>
        </div>
      </v-card>
    </div>

    <!-- 市场（多源） -->
    <div v-if="tab === 'market'">
      <v-card class="pa-4 mb-3">
        <div class="text-subtitle-1 font-weight-medium mb-2">市场源（自建源为一等公民）</div>
        <v-chip
          v-for="src in sources" :key="src.id"
          closable :color="src.enabled ? 'primary' : 'default'" size="small"
          class="mr-1 mb-1" variant="tonal"
          @click:close="removeSource(src.id)"
        >
          {{ src.name }}
        </v-chip>
        <div class="d-flex ga-2 mt-2 flex-wrap">
          <v-text-field v-model="newSource.id" label="源 id" density="compact" style="max-width: 10rem" />
          <v-text-field v-model="newSource.name" label="名称" density="compact" style="max-width: 12rem" />
          <v-text-field v-model="newSource.url" label="市场 JSON URL" density="compact" style="max-width: 24rem" />
          <v-btn color="primary" @click="addSource">添加源</v-btn>
          <v-btn variant="tonal" @click="loadMarket">刷新市场</v-btn>
          <v-btn variant="text" prepend-icon="mdi-github" @click="installDialog = true">从 GitHub 安装</v-btn>
        </div>
      </v-card>
      <v-alert
        v-if="market && Object.keys(market.source_errors).length"
        type="warning" variant="tonal" density="compact" class="mb-2"
      >
        部分源拉取失败：{{ JSON.stringify(market.source_errors) }}
      </v-alert>
      <v-row>
        <v-col v-for="p in market?.plugins ?? []" :key="p.name + p.repo" cols="12" sm="6" md="4">
          <v-card class="pa-3 fill-height d-flex flex-column">
            <div class="text-subtitle-2 font-weight-medium">{{ p.name }} <span class="text-caption">{{ p.version }}</span></div>
            <div class="text-caption text-medium-emphasis mb-1">by {{ p.author }} · {{ p.source_id }}</div>
            <div class="text-body-2 flex-grow-1">{{ p.desc }}</div>
            <v-btn
              size="small" color="primary" variant="tonal" class="mt-2"
              :disabled="!p.repo" @click="installFromMarket(p)"
            >
              安装
            </v-btn>
          </v-card>
        </v-col>
      </v-row>
      <div v-if="market && !market.plugins.length" class="text-body-2 text-medium-emphasis pa-4">
        市场为空或全部源不可达。
      </div>
    </div>

    <!-- MCP -->
    <div v-if="tab === 'mcp'">
      <v-card class="pa-2">
        <!-- 空状态：提示与新增按钮同一行（2026-09-25 用户要求对齐） -->
        <div v-if="!mcpServers.length" class="d-flex align-center flex-wrap ga-2 pa-3">
          <span class="text-body-2 text-medium-emphasis">
            没有 MCP Server。MCP_ENABLED=false 时服务只写配置不热生效。
          </span>
          <v-spacer />
          <v-btn color="primary" size="small" prepend-icon="mdi-plus" @click="openMcpEditor()">新增 Server</v-btn>
        </div>
        <template v-else>
          <div class="d-flex align-center pa-2">
            <v-spacer />
            <v-btn color="primary" size="small" prepend-icon="mdi-plus" @click="openMcpEditor()">新增 Server</v-btn>
          </div>
          <v-list>
            <v-list-item v-for="s in mcpServers" :key="s.server_id">
              <template #prepend>
                <v-chip :color="s.enabled ? 'success' : 'default'" size="x-small" variant="tonal">
                  {{ s.enabled ? '启用' : '停用' }}
                </v-chip>
              </template>
              <v-list-item-title class="text-body-2">{{ s.server_id }}</v-list-item-title>
              <v-list-item-subtitle>
                {{ s.transport === 'stdio' ? s.command : s.url }}
              </v-list-item-subtitle>
              <template #append>
                <v-btn size="x-small" variant="text" @click="testMcp(s)">测试</v-btn>
                <v-btn size="x-small" variant="text" @click="openMcpEditor(s)">编辑</v-btn>
                <v-btn size="x-small" variant="text" color="error" @click="deleteMcp(s)">删除</v-btn>
              </template>
            </v-list-item>
          </v-list>
          <div v-if="mcpTestResult" class="text-caption pa-2">{{ mcpTestResult }}</div>
        </template>
      </v-card>
    </div>

    <!-- Skills -->
    <div v-if="tab === 'skills'">
      <v-card class="pa-2">
        <v-list>
          <v-list-item v-for="s in skills" :key="s.name">
            <v-list-item-title class="text-body-2">{{ s.name }}</v-list-item-title>
            <v-list-item-subtitle>{{ s.description }} · {{ s.source }}</v-list-item-subtitle>
            <template #append>
              <v-btn size="x-small" variant="text" @click="openSkill(s)">查看/编辑</v-btn>
              <v-btn size="x-small" variant="text" color="error" @click="deleteSkill(s)">删除</v-btn>
            </template>
          </v-list-item>
        </v-list>
        <div v-if="!skills.length" class="text-body-2 text-medium-emphasis pa-4">
          没有技能。用户技能放 data/skills/&lt;name&gt;/SKILL.md。
        </div>
      </v-card>
      <v-card v-if="skillName" class="pa-4 mt-3">
        <div class="d-flex align-center mb-2">
          <div class="text-subtitle-2">{{ skillName }} {{ skillEditable ? '' : '（只读）' }}</div>
          <v-spacer />
          <v-btn v-if="skillEditable" size="small" color="primary" @click="saveSkill">保存</v-btn>
        </div>
        <v-textarea v-model="skillBody" rows="14" density="compact" hide-details :disabled="!skillEditable" />
      </v-card>
    </div>

    <!-- 插件配置对话框 -->
    <v-dialog v-model="configDialog" width="720" scrollable>
      <v-card>
        <v-card-title>插件配置 · {{ configPlugin }}</v-card-title>
        <v-card-text style="max-height: 60vh">
          <ConfigForm v-model="configValues" :fields="configFields" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="configDialog = false">取消</v-btn>
          <v-btn color="primary" @click="saveConfig">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- README 对话框（marked 渲染 + DOMPurify 消毒，GitHub 风格） -->
    <v-dialog
      :model-value="readmeName !== ''"
      width="860"
      @update:model-value="readmeName = ''"
    >
      <v-card>
        <v-card-title>README · {{ readmeName }}</v-card-title>
        <v-divider />
        <v-card-text class="md-body" style="max-height: 65vh; overflow-y: auto" v-html="readmeHtml" />
        <v-card-actions><v-spacer /><v-btn @click="readmeName = ''">关闭</v-btn></v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 安装对话框 -->
    <v-dialog v-model="installDialog" width="520">
      <v-card>
        <v-card-title>安装插件</v-card-title>
        <v-card-text>
          <v-btn-toggle v-model="installSource" mandatory density="compact" class="mb-3">
            <v-btn value="github">GitHub</v-btn>
            <v-btn value="url">URL zip</v-btn>
          </v-btn-toggle>
          <v-text-field
            v-if="installSource === 'github'"
            v-model="installRepo" label="owner/name" placeholder="AstrBotDevs/astrbot_plugin_xxx"
          />
          <v-text-field v-else v-model="installUrl" label="zip 直链 URL" />
          <div class="text-caption text-medium-emphasis">
            安装会经过 Stella 插件规范校验（plugin-check），不合规将被拒绝并清理。
          </div>
          <pre v-if="installResult" class="text-caption text-error mt-2">{{ installResult }}</pre>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="installDialog = false">取消</v-btn>
          <v-btn color="primary" :loading="busy" @click="install">安装</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- MCP 编辑对话框 -->
    <v-dialog v-model="mcpDialog" width="560">
      <v-card>
        <v-card-title>MCP Server</v-card-title>
        <v-card-text>
          <v-text-field v-model="mcpForm.server_id" label="Server ID" :disabled="mcpForm.server_id !== '' && mcpServers.some(s => s.server_id === mcpForm.server_id)" />
          <v-switch v-model="mcpForm.enabled" label="启用" color="primary" density="compact" />
          <v-select v-model="mcpForm.transport" :items="['stdio', 'streamable_http']" label="传输" density="compact" />
          <v-text-field v-if="mcpForm.transport === 'stdio'" v-model="mcpForm.command" label="命令（禁 shell 元字符）" />
          <v-text-field v-if="mcpForm.transport === 'stdio'" v-model="mcpForm.args" label="参数（空格分隔）" />
          <v-text-field v-if="mcpForm.transport !== 'stdio'" v-model="mcpForm.url" label="URL" />
          <v-text-field v-if="mcpForm.transport !== 'stdio'" v-model="mcpForm.auth_env" label="token 环境变量名" />
          <div v-if="mcpTestResult" class="text-caption">{{ mcpTestResult }}</div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="mcpDialog = false">取消</v-btn>
          <v-btn color="primary" @click="saveMcp">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
/* 操作按钮组：td 内层 flex（td 本身不能变 flex，会破坏表格布局） */
.action-cell {
  white-space: nowrap;
}

/* README 的 GitHub 风格渲染。v-html 注入的内容不带 scoped 属性，
   必须用 :deep() 才能命中（字面样式写在 :deep 内的元素上）。 */
.md-body {
  line-height: 1.65;
  font-size: 0.9rem;
  word-break: break-word;
}
.md-body :deep(h1),
.md-body :deep(h2) {
  border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  padding-bottom: 0.3em;
  margin: 1.2em 0 0.6em;
}
.md-body :deep(h1) {
  font-size: 1.5rem;
}
.md-body :deep(h2) {
  font-size: 1.25rem;
}
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 1em 0 0.5em;
}
.md-body :deep(p) {
  margin: 0.6em 0;
}
.md-body :deep(code) {
  background: rgba(var(--v-theme-primary), 0.12);
  padding: 0.15em 0.35em;
  border-radius: 4px;
  font-size: 0.85em;
}
.md-body :deep(pre) {
  background: rgba(var(--v-theme-primary), 0.08);
  padding: 0.8em;
  border-radius: 8px;
  overflow-x: auto;
}
.md-body :deep(pre code) {
  background: transparent;
  padding: 0;
}
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 0.8em 0;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid rgba(var(--v-border-color), 0.25);
  padding: 0.4em 0.7em;
}
.md-body :deep(img) {
  max-width: 100%;
}
.md-body :deep(a) {
  color: rgb(var(--v-theme-primary));
}
.md-body :deep(blockquote) {
  border-left: 3px solid rgba(var(--v-theme-primary), 0.5);
  margin: 0.6em 0;
  padding: 0.1em 1em;
  opacity: 0.85;
}
.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: 1.4em;
}
</style>
