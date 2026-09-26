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
// doctor 报告的结构化渲染：items 逐条（级别图标 + 标题 + 详情 + 建议），
// 原始 JSON 收进折叠块——整屏 JSON 用户读不了（2026-09-25 用户安装失败反馈）。
interface DoctorItem {
  level: string;
  title: string;
  detail?: string;
  fix_hint?: string;
}
const doctorItems = ref<DoctorItem[]>([]);
const inShell = computed(() => isTauri());

// ---------- 启动中加载视图（2026-09-25 用户要求） ----------
// 首次启动要经历「下载运行时 → 装依赖 → 下载 embedding 模型 → 起 Bot」，
// 全程数分钟。过去这一程只显示「后端未运行」的错误卡，用户以为程序坏了。
// 现在启动期间整页切换为加载视图：星标动画 + 阶段轮播提示 + 已用时计时。
const elapsedSecs = ref(0);
const hintIndex = ref(0);
const BOOT_HINTS = [
  '正在准备嵌入式运行环境…',
  '正在下载运行时与依赖（首次启动需要几分钟）…',
  '正在下载 embedding 模型…',
  '正在启动 Stella Bot…',
  '一切正常，没有阻塞性错误——首次启动请耐心等待。',
];
let hintTimer: number | null = null;
let elapsedTimer: number | null = null;
let progressTimer: number | null = null;
let botProbeTimer: number | null = null;

// 真实进度（2026-09-25 用户要求）：bootstrap 组件安装（NapCat / embedding
// 模型逐个推进，失败时 state=failed + error）与 prepare_runtime 的文本进度
// （运行时下载 / pip / 依赖安装）。都读不到时才回落轮播提示。
interface BootProgress {
  state?: string;
  current?: string;
  completed?: string[];
  error?: string;
}
const liveProgress = ref<{ bootstrap: BootProgress | null; prepare: string | null } | null>(null);
const bootstrapFailed = computed(
  () => liveProgress.value?.bootstrap?.state === 'failed',
);
const liveLine = computed(() => {
  const lp = liveProgress.value;
  if (!lp) return '';
  if (lp.bootstrap?.state === 'failed') {
    return `组件安装失败：${lp.bootstrap.error || lp.bootstrap.current || '未知原因'}`;
  }
  if (lp.bootstrap?.current) {
    const done = lp.bootstrap.completed?.length ?? 0;
    return `正在安装组件：${lp.bootstrap.current}（已完成 ${done} 项）`;
  }
  return lp.prepare || '';
});

async function pollStartProgress(): Promise<void> {
  if (!isTauri()) return;
  try {
    liveProgress.value = await tauriBridge.invoke<{ bootstrap: BootProgress | null; prepare: string | null }>(
      'read_start_progress',
    );
  } catch {
    // 进度读不到不影响启动；轮播提示继续兜底
  }
}

// 直连 Bot 状态接口的事实探针：进程起没起、接口通没通，亮在加载视图上。
// bot 起来后立即导航进面板（不等 Tauri 侧的等待命令返回）。
const botProbe = ref<{ pid: number | null; online: boolean }>({ pid: null, online: false });

async function pollBotStatus(): Promise<void> {
  const port = cfg.value?.port || 8080;
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/stella/status`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!resp.ok) throw new Error(String(resp.status));
    const data = (await resp.json()) as { pid?: number };
    botProbe.value = { pid: data.pid ?? null, online: true };
    if (starting.value && step.value.startsWith('等待服务就绪')) {
      step.value = 'Bot 已就绪，正在打开面板…';
      window.location.href = `http://127.0.0.1:${port}/`;
    }
  } catch {
    botProbe.value = { pid: null, online: false };
  }
}

function startLoadingUi(): void {
  elapsedSecs.value = 0;
  hintIndex.value = 0;
  liveProgress.value = null;
  void pollStartProgress();
  void pollBotStatus();
  if (progressTimer === null) {
    progressTimer = window.setInterval(() => void pollStartProgress(), 1500);
  }
  if (botProbeTimer === null) {
    botProbeTimer = window.setInterval(() => void pollBotStatus(), 2000);
  }
  if (hintTimer === null) {
    hintTimer = window.setInterval(() => {
      hintIndex.value = (hintIndex.value + 1) % BOOT_HINTS.length;
    }, 4000);
  }
  if (elapsedTimer === null) {
    elapsedTimer = window.setInterval(() => {
      elapsedSecs.value += 1;
    }, 1000);
  }
}

function stopLoadingUi(): void {
  if (hintTimer !== null) {
    window.clearInterval(hintTimer);
    hintTimer = null;
  }
  if (elapsedTimer !== null) {
    window.clearInterval(elapsedTimer);
    elapsedTimer = null;
  }
  if (progressTimer !== null) {
    window.clearInterval(progressTimer);
    progressTimer = null;
  }
  if (botProbeTimer !== null) {
    window.clearInterval(botProbeTimer);
    botProbeTimer = null;
  }
}

const elapsedText = computed(() => {
  const s = elapsedSecs.value;
  return s >= 60 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${s} 秒`;
});

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

/** 轮询等待 Bot 就绪并跳转到在线面板（面板由 Bot 同端口托管）。 */
async function enterPanel(timeoutSecs: number): Promise<void> {
  const base = await tauriBridge.waitBotReady(timeoutSecs);
  step.value = '就绪，正在打开面板…';
  window.location.href = base;
}

async function startBot(): Promise<void> {
  starting.value = true;
  startError.value = '';
  step.value = '正在启动 Bot…';
  startLoadingUi();
  try {
    await tauriBridge.startBot(false);
  } catch (err) {
    const msg = (err as Error).message;
    // Bot 已在运行（deploy 拒绝重复启动）不算失败——目标本来就是进面板
    if (!msg.includes('已在运行') && !msg.includes('already running')) {
      startError.value = msg;
      step.value = '';
      starting.value = false;
      stopLoadingUi();
      return;
    }
  }
  step.value = '等待服务就绪（首次启动需安装依赖，最长 20 分钟）…';
  try {
    const base = await tauriBridge.waitBotReady(1200);
    stopLoadingUi();
    step.value = '就绪，正在打开面板…';
    window.location.href = base;
  } catch (err) {
    startError.value = (err as Error).message;
    step.value = '';
    starting.value = false;
    stopLoadingUi();
  }
}

async function runShellDoctor(): Promise<void> {
  doctorText.value = '运行中…';
  try {
    const text = await tauriBridge.runDoctor();
    doctorText.value = text;
    try {
      const parsed = JSON.parse(text) as { items?: DoctorItem[] };
      doctorItems.value = Array.isArray(parsed?.items) ? parsed.items : [];
    } catch {
      doctorItems.value = [];
    }
  } catch (err) {
    doctorText.value = `自检失败：${(err as Error).message}`;
    doctorItems.value = [];
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
  spacesText: '',
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
  // 用现有 .env 回填（读旧配置的入口）：群号/地址/模型/token 全部沿用旧值；
  // 空间绑定逐行回填并原样保留——write_spaces 会删除「managed 且未列出」的
  // 空间 toml，回填缺失 = 用户的生产空间被清空（生产空间有 5 个，不可重忘）。
  if (cfg.value) {
    form.value.groups = cfg.value.allowed_groups || form.value.groups;
    form.value.lmUrl = cfg.value.lm_base_url || form.value.lmUrl;
    form.value.chatModel = cfg.value.chat_model || form.value.chatModel;
    form.value.accessToken = cfg.value.access_token || '';
    form.value.onebotMode = cfg.value.onebot_mode || 'reverse';
    form.value.host = cfg.value.host || '0.0.0.0';
    form.value.port = cfg.value.port || 8080;
    form.value.spacesText = spacesToLines(cfg.value.spaces);
  }
  wizardError.value = '';
  wizardOpen.value = true;
}

/** get_config.spaces（JSON [[name,prompt,groups],...]）→ parse_spaces 行格式 */
function spacesToLines(spacesJson: string): string {
  try {
    const parsed = JSON.parse(spacesJson || '[]') as [string, string, (number | string)[]][];
    return parsed
      .map(([name, prompt, groups]) =>
        `${name} | ${prompt || `${name}.md`} | ${(groups ?? []).join(',')}`,
      )
      .join('\\n');
  } catch {
    return '';
  }
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
        spaces: form.value.spacesText,
        advanced_env: '',
      },
    });

    wizardStep.value = '启动 Bot（首次需下载嵌入式运行时并安装依赖，5–15 分钟）…';
    try {
      await tauriBridge.startBot(false);
    } catch (err) {
      const msg = (err as Error).message;
      if (!msg.includes('已在运行') && !msg.includes('already running')) throw err;
    }
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
  // 已配置过的安装：打开壳即自动启动（2026-09-25 用户要求——首启不该让用户
  // 面对「后端未运行」的错误卡，而是看到「正在启动」的加载过程）。
  // deploy start 遇「已在运行」会原样返回，重复打开壳是安全的。
  if (cfg.value?.configured) {
    void startBot();
  }
  // Bot 已在运行（比如壳重启而 Bot 未关）→ 自动进面板；
  // 就绪探测带重试循环——单次探测失败不该把用户困在离线页
  void (async () => {
    for (let i = 0; i < 36; i++) {
      if (!starting.value) {
        try {
          await enterPanel(2);
          return;
        } catch {
          // 未就绪，继续轮询
        }
      }
      await new Promise((r) => setTimeout(r, 2500));
    }
  })();
});
</script>

<template>
  <div class="offline-wrap">
    <!-- 启动中：动画 + 阶段提示（首启全流程反馈，替代吓人的错误卡） -->
    <div v-if="starting" class="offline-card text-center">
      <v-icon
        icon="mdi-star-four-points"
        color="secondary"
        size="64"
        class="mb-4 stella-boot-star"
      />
      <div class="text-h6 mb-1">正在启动 Stella</div>
      <div class="text-body-2 text-medium-emphasis mb-3">{{ step || '准备中…' }}</div>
      <v-progress-linear indeterminate color="secondary" class="mb-4 rounded" />
      <div v-if="liveLine" class="text-body-2 font-weight-medium mb-1">{{ liveLine }}</div>
      <div v-if="bootstrapFailed" class="text-error text-body-2 mb-1">
        组件安装失败不影响程序运行——点「重试」可重新安装组件。
      </div>
      <div class="text-body-2 mb-1">{{ BOOT_HINTS[hintIndex] }}</div>
      <div class="text-caption text-disabled">
        已运行 {{ elapsedText }} · 首次启动需要下载运行时与依赖，可能需要数分钟，请勿关闭窗口
      </div>
      <div class="d-flex ga-2 justify-center mt-4">
        <v-btn size="small" variant="text" @click="runShellDoctor">环境自检</v-btn>
      </div>
      <div v-if="doctorItems.length" class="text-left mt-4" style="max-width: 36rem">
        <div v-for="(item, i) in doctorItems" :key="i" class="d-flex ga-2 mb-2">
          <v-icon
            size="small"
            :color="item.level === 'error' ? 'error' : item.level === 'warn' ? 'warning' : 'success'"
            :icon="item.level === 'error' ? 'mdi-close-circle' : item.level === 'warn' ? 'mdi-alert' : 'mdi-check-circle'"
          />
          <div>
            <div class="text-body-2">{{ item.title }}</div>
            <div v-if="item.detail" class="text-caption text-medium-emphasis">{{ item.detail }}</div>
            <div v-if="item.fix_hint" class="text-caption text-medium-emphasis">建议：{{ item.fix_hint }}</div>
          </div>
        </div>
      </div>
      <details v-if="doctorText" class="mt-2 text-left" style="max-width: 36rem">
        <summary class="text-caption text-medium-emphasis">原始报告</summary>
        <pre class="text-caption" style="max-height: 200px; overflow-y: auto; white-space: pre-wrap">{{ doctorText }}</pre>
      </details>
      <div v-if="startError" class="text-error text-caption mt-2 pre-wrap">{{ startError }}</div>
    </div>

    <div v-else class="offline-card">
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
      <div v-if="doctorItems.length" class="text-left mt-4" style="max-width: 36rem">
        <div v-for="(item, i) in doctorItems" :key="i" class="d-flex ga-2 mb-2">
          <v-icon
            size="small"
            :color="item.level === 'error' ? 'error' : item.level === 'warn' ? 'warning' : 'success'"
            :icon="item.level === 'error' ? 'mdi-close-circle' : item.level === 'warn' ? 'mdi-alert' : 'mdi-check-circle'"
          />
          <div>
            <div class="text-body-2">{{ item.title }}</div>
            <div v-if="item.detail" class="text-caption text-medium-emphasis">{{ item.detail }}</div>
            <div v-if="item.fix_hint" class="text-caption text-medium-emphasis">建议：{{ item.fix_hint }}</div>
          </div>
        </div>
      </div>
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
          <v-textarea
            v-model="form.spacesText"
            label="空间绑定（每行：空间名 | 人格文件 | 群号）"
            rows="3"
            density="compact"
            hint="已有空间原样保留；修改群号请编辑对应行"
            persistent-hint
          />
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
/* 启动动画：星标旋转 + 呼吸缩放（logo 同款四角星） */
.stella-boot-star {
  animation: stella-boot-spin 2.4s ease-in-out infinite;
}
@keyframes stella-boot-spin {
  0% {
    transform: rotate(0deg) scale(1);
    opacity: 0.75;
  }
  50% {
    transform: rotate(180deg) scale(1.12);
    opacity: 1;
  }
  100% {
    transform: rotate(360deg) scale(1);
    opacity: 0.75;
  }
}
</style>
