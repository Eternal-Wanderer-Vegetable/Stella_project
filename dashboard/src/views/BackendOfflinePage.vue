<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { isTauri, tauriBridge } from '@/api/tauri';
import { useAuthStore } from '@/stores/auth';

// 离线页（方案 §11）：
// - 浏览器：纯重试；
// - 壳内：读取现有 .env（get_config）——已配置过 → 直接「启动 Bot」
//   （旧配置原样生效，绝不走会覆盖配置的保存）；未配置 → 首启向导
//   （save_config，v1 向导同一条 deploy init --answers 通路）→ 启动 →
//   轮询就绪 → 导航到 Bot 托管的在线面板。
const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();

const starting = ref(false);
const startError = ref('');
const step = ref('');
const doctorText = ref('');
const inShell = computed(() => isTauri());

interface ShellConfig {
  configured: boolean;
  allowed_groups: string;
  onebot_mode: string;
  host: string;
  port: number;
  ws_urls: string;
  access_token: string;
  lm_base_url: string;
  chat_model: string;
  consolidation_model: string;
  embedding_model: string;
  spaces: string;
}

const cfg = ref<ShellConfig | null>(null);
const cfgLoaded = ref(false);

async function retry(): Promise<void> {
  const state = await auth.probe();
  if (state === 'online') {
    router.go(0);
  }
}

async function startBot(): Promise<void> {
  starting.value = true;
  startError.value = '';
  step.value = '启动 Bot…';
  try {
    await tauriBridge.startBot(false);
    step.value = '等待服务就绪（首次启动需安装依赖，最长 20 分钟）…';
    const base = await tauriBridge.waitBotReady(1200);
    step.value = '就绪，正在打开面板…';
    window.location.href = base;
  } catch (err) {
    startError.value = (err as Error).message;
    step.value = '';
    starting.value = false;
  }
}

async function runShellDoctor(): Promise<void> {
  doctorText.value = '运行中…';
  try {
    doctorText.value = await tauriBridge.runDoctor();
  } catch (err) {
    doctorText.value = `自检失败：${(err as Error).message}`;
  }
}

// ---------- 首启向导（仅 configured=false 时出现） ----------
const wizardOpen = ref(false);
const wizardBusy = ref(false);
const wizardStep = ref('');
const wizardError = ref('');
const form = ref({
  groups: '',
  spaceName: '默认空间',
  lmUrl: 'http://127.0.0.1:1234',
  chatModel: '',
  accessToken: '',
  onebotMode: 'reverse',
  host: '0.0.0.0',
  port: 8080,
});

function parseGroups(): number[] {
  return form.value.groups
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n));
}

function openWizard(): void {
  // 用现有 .env 回填（读旧配置的入口）：群号/地址/模型/token 全部沿用旧值
  if (cfg.value) {
    form.value.groups = cfg.value.allowed_groups || form.value.groups;
    form.value.lmUrl = cfg.value.lm_base_url || form.value.lmUrl;
    form.value.chatModel = cfg.value.chat_model || form.value.chatModel;
    form.value.accessToken = cfg.value.access_token || '';
    form.value.onebotMode = cfg.value.onebot_mode || 'reverse';
    form.value.host = cfg.value.host || '0.0.0.0';
    form.value.port = cfg.value.port || 8080;
  }
  wizardError.value = '';
  wizardOpen.value = true;
}

async function saveAndStart(): Promise<void> {
  const groups = parseGroups();
  if (!groups.length) {
    wizardError.value = '请至少填写一个 QQ 群号';
    return;
  }
  wizardBusy.value = true;
  wizardError.value = '';
  try {
    wizardStep.value = '写入初始配置…';
    await tauriBridge.invoke('save_config', {
      config: {
        allowed_groups: groups.join(','),
        onebot_mode: form.value.onebotMode,
        host: form.value.host,
        port: Number(form.value.port) || 8080,
        ws_urls: '',
        access_token: form.value.accessToken,
        lm_base_url: form.value.lmUrl,
        chat_model: form.value.chatModel,
        consolidation_model: '',
        embedding_model: '',
        spaces: `${form.value.spaceName}|default.md|${groups.join(',')}`,
        advanced_env: '',
      },
    });

    wizardStep.value = '启动 Bot（首次需下载嵌入式运行时并安装依赖，5–15 分钟）…';
    await tauriBridge.startBot(false);

    wizardStep.value = '等待服务就绪（最长 20 分钟）…';
    const base = await tauriBridge.waitBotReady(1200);
    wizardStep.value = '就绪，正在打开面板…';
    window.location.href = base;
  } catch (err) {
    wizardError.value = (err as Error).message;
    wizardBusy.value = false;
  }
}

onMounted(async () => {
  if (!inShell.value) return;
  try {
    cfg.value = await tauriBridge.invoke<ShellConfig>('get_config');
  } catch {
    cfg.value = null;
  } finally {
    cfgLoaded.value = true;
  }
});
</script>

<template>
  <div class="offline-wrap">
    <div class="offline-card">
      <v-icon icon="mdi-lan-disconnect" color="warning" size="44" class="mb-3" />
      <div class="text-h6 mb-2">{{ $t('features.offline.title') }}</div>
      <p class="text-body-2 text-medium-emphasis mb-4">
        {{ $t('features.offline.hint') }}
      </p>
      <div class="d-flex ga-2 justify-center flex-wrap">
        <v-btn color="primary" variant="tonal" @click="retry">
          {{ $t('features.offline.retry') }}
        </v-btn>
        <!-- 壳内主按钮：已配置 → 直接启动（旧配置生效）；未配置 → 向导 -->
        <v-btn
          v-if="inShell && cfgLoaded"
          color="warning"
          :loading="starting"
          @click="startBot"
        >
          {{ cfg?.configured ? '启动 Bot' : '初始化并启动' }}
        </v-btn>
        <v-btn v-if="inShell" variant="text" @click="runShellDoctor">环境自检</v-btn>
      </div>
      <div v-if="inShell && cfgLoaded && !cfg?.configured" class="text-caption text-medium-emphasis mt-2">
        检测到尚未完成初始配置——点「初始化并启动」填写基本信息。
      </div>
      <v-btn
        v-if="inShell && cfgLoaded && cfg?.configured"
        variant="text"
        size="small"
        class="mt-2"
        @click="openWizard"
      >
        修改基础配置（群号 / 模型 / 连接）
      </v-btn>
      <pre
        v-if="doctorText"
        class="text-caption text-left mt-4"
        style="max-height: 200px; overflow-y: auto; white-space: pre-wrap"
      >{{ doctorText }}</pre>
      <div v-if="step" class="text-caption text-medium-emphasis mt-2">{{ step }}</div>
      <div v-if="startError" class="text-error text-caption mt-2 pre-wrap">{{ startError }}</div>
    </div>

    <!-- 基础配置向导（首启 / 修改） -->
    <v-dialog v-model="wizardOpen" width="560" persistent>
      <v-card>
        <v-card-title>{{ cfg?.configured ? '修改基础配置' : '初始化配置' }}</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="form.groups"
            label="QQ 群号（逗号分隔，Bot 只在这些群里响应）"
            density="compact"
          />
          <v-text-field v-model="form.spaceName" label="空间名" density="compact" />
          <v-text-field v-model="form.lmUrl" label="LM Studio / OpenAI 兼容地址" density="compact" />
          <v-text-field
            v-model="form.chatModel"
            label="对话模型 ID（如 google/gemma-4-e4b）"
            density="compact"
            hint="与 LM Studio 已加载的模型一致"
            persistent-hint
          />
          <v-text-field
            v-model="form.accessToken"
            label="OneBot 访问 token（可留空）"
            density="compact"
            type="password"
          />
          <div class="d-flex ga-2">
            <v-text-field v-model="form.host" label="监听地址" density="compact" />
            <v-text-field v-model="form.port" label="端口" density="compact" />
          </div>
          <v-select
            v-model="form.onebotMode"
            :items="[
              { title: '反向 WS（NapCat 连到 Bot，推荐）', value: 'reverse' },
              { title: '正向 WS（Bot 连到 NapCat）', value: 'forward' },
            ]"
            label="连接方式"
            density="compact"
          />
          <div v-if="wizardStep" class="text-caption text-medium-emphasis mt-2">
            {{ wizardStep }}
          </div>
          <div v-if="wizardError" class="text-error text-caption mt-2 pre-wrap">{{ wizardError }}</div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn :disabled="wizardBusy" @click="wizardOpen = false">取消</v-btn>
          <v-btn color="primary" :loading="wizardBusy" @click="saveAndStart">
            保存并启动
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.offline-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pre-wrap {
  white-space: pre-wrap;
}
</style>
