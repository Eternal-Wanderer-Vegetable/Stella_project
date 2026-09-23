<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { isTauri, tauriBridge } from '@/api/tauri';
import { useAuthStore } from '@/stores/auth';

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();

const starting = ref(false);
const startError = ref('');
const doctorText = ref('');
const inShell = computed(() => isTauri());

async function retry(): Promise<void> {
  const state = await auth.probe();
  if (state === 'online') {
    router.go(0); // 整页重载，让路由守卫按在线状态重走
  }
}

/** 壳内启动：start_bot → 轮询就绪（首启含运行时下载，放宽到 20 分钟）→ 导航在线面板。 */
async function startFromShell(): Promise<void> {
  starting.value = true;
  startError.value = '';
  try {
    await tauriBridge.startBot(false);
    const base = await tauriBridge.waitBotReady(1200);
    window.location.href = base; // 导航到 Bot 托管的在线面板
  } catch (err) {
    startError.value = (err as Error).message;
    starting.value = false;
  }
}

/** 壳内自检：deploy doctor 的文本报告。 */
async function runShellDoctor(): Promise<void> {
  doctorText.value = '运行中…';
  try {
    doctorText.value = await tauriBridge.runDoctor();
  } catch (err) {
    doctorText.value = `自检失败：${(err as Error).message}`;
  }
}

// ---------- 首启配置向导（壳内；走 v1 同一条 deploy init --answers 通路） ----------
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
});

function parseGroups(): number[] {
  return form.value.groups
    .split(/[,，\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number)
    .filter((n) => !Number.isNaN(n));
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
        host: '0.0.0.0',
        port: 8080,
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
        <v-btn v-if="inShell" color="warning" @click="wizardOpen = true">初始化并启动</v-btn>
        <v-btn v-if="inShell" variant="text" @click="runShellDoctor">环境自检</v-btn>
      </div>
      <pre
        v-if="doctorText"
        class="text-caption text-left mt-4"
        style="max-height: 200px; overflow-y: auto; white-space: pre-wrap"
      >{{ doctorText }}</pre>
    </div>

    <!-- 首启配置向导（壳内；save_config 与 v1 向导同一条 deploy init 通路） -->
    <v-dialog v-model="wizardOpen" width="560" persistent>
      <v-card>
        <v-card-title>初始化配置</v-card-title>
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
          <div v-if="wizardError" class="text-error text-caption mt-2">{{ wizardError }}</div>
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
</style>
