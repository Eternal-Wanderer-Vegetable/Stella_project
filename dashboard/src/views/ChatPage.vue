<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { sseStream } from '@/api/sse';
import { toastApiError, useToast } from '@/stores/toast';
import { useSystemStore } from '@/stores/system';

// 聊天页（M4 WebChat）：与 Stella 私聊，记忆按 webchat 空间隔离
interface Message {
  id: number | string;
  role: 'user' | 'bot';
  content: string;
  ts?: string;
}

const messages = ref<Message[]>([]);
const input = ref('');
const busy = ref(false);
const listEl = ref<HTMLElement | null>(null);
const historyStale = ref(false);
const historyGeneration = ref<string | null>(null);
const toast = useToast();
const system = useSystemStore();
const cacheStale = computed(() =>
  historyStale.value
  || (system.managed && (
    system.coreUnavailable
    || Boolean(historyGeneration.value && system.coreGeneration !== historyGeneration.value)
  )),
);
const webChatSettingsDialog = ref(false);
const webChatPrompt = ref('');
const webChatSettingsLoading = ref(false);
const webChatSettingsLoaded = ref(false);
const webChatSettingsSaving = ref(false);
const webChatSpaceReady = ref(false);
const webChatSettingsMessage = ref('');

interface SpaceItem {
  name: string;
}

const FAILBACK = '……？';

function scrollBottom(): void {
  void nextTick(() => listEl.value?.scrollTo({ top: listEl.value.scrollHeight }));
}

async function loadHistory(): Promise<void> {
  try {
    await system.refreshStatus();
    const data = await unwrap<{ items: { id: number; content: string; source_kind: string; timestamp: string }[] }>(
      api.get('/chat/messages', { params: { limit: 100 } }),
    );
    messages.value = data.items.map((m) => ({
      id: m.id,
      role: m.source_kind === 'BOT_SELF' ? 'bot' : 'user',
      content: m.content,
      ts: m.timestamp,
    }));
    historyGeneration.value = system.coreGeneration;
    historyStale.value = false;
    scrollBottom();
  } catch {
    // Keep the local cache visible and mark it stale; never replay a failed chat request.
    historyStale.value = true;
  }
}

async function send(): Promise<void> {
  const text = input.value.trim();
  if (!text || busy.value) return;
  input.value = '';
  busy.value = true;
  messages.value.push({ id: `local-${Date.now()}`, role: 'user', content: text });
  scrollBottom();

  let stopWatch: ReturnType<typeof setTimeout> | null = null;
  try {
    await sseStream(
      '/api/v1/chat',
      (id, data) => {
      try {
        const frame = JSON.parse(data);
        if (frame.type === 'complete') {
          const reply = (frame.data.lines ?? []).join('\n') || FAILBACK;
          messages.value.push({ id: `bot-${Date.now()}`, role: 'bot', content: reply });
          if (frame.data.thought) {
            // thought 不进主时间轴，控制台可查（M5 移到推理侧栏）
          }
        } else if (frame.type === 'error') {
          messages.value.push({
            id: `err-${Date.now()}`, role: 'bot',
            content: `（出错了：${frame.data.message}）`,
          });
        }
        scrollBottom();
      } catch {
        // 非 JSON 帧忽略
      }
      if (stopWatch !== null) clearTimeout(stopWatch);
      stopWatch = setTimeout(() => { busy.value = false; }, 500);
    },
    { method: 'POST', body: JSON.stringify({ message: text }) },
    );
  } catch (err) {
    historyStale.value = true;
    toastApiError(toast, err);
  } finally {
    busy.value = false;
  }
  scrollBottom();
}

async function reset(): Promise<void> {
  try {
    await unwrap(api.post('/chat/reset'));
    messages.value = [];
    await loadHistory();
    toast.success('会话已清空（长期记忆不受影响）');
  } catch (err) {
    toastApiError(toast, err);
  }
}

function closeWebChatSettings(): void {
  webChatSettingsDialog.value = false;
  webChatSettingsLoaded.value = false;
  webChatSettingsMessage.value = '';
}

async function openWebChatSettings(): Promise<void> {
  webChatSettingsDialog.value = true;
  webChatSettingsLoading.value = true;
  webChatSettingsLoaded.value = false;
  webChatSpaceReady.value = false;
  webChatSettingsMessage.value = '';
  try {
    const data = await unwrap<{ spaces: SpaceItem[] }>(api.get('/spaces'));
    webChatSpaceReady.value = data.spaces.some((space) => space.name === 'webchat');
    if (!webChatSpaceReady.value) {
      webChatSettingsMessage.value = '首次发送一条 WebChat 消息后，系统会创建专属空间；之后即可在这里设置人格。';
      return;
    }
    const prompt = await unwrap<{ text: string }>(api.get('/spaces/webchat/prompt'));
    webChatPrompt.value = prompt.text;
    webChatSettingsLoaded.value = true;
  } catch (err) {
    webChatSettingsDialog.value = false;
    toastApiError(toast, err);
  } finally {
    webChatSettingsLoading.value = false;
  }
}

async function saveWebChatSettings(): Promise<void> {
  if (!webChatSettingsLoaded.value || webChatSettingsSaving.value) return;
  webChatSettingsSaving.value = true;
  try {
    await unwrap(api.put('/spaces/webchat/prompt', { text: webChatPrompt.value }));
    toast.success('WebChat 设置已保存');
    closeWebChatSettings();
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    webChatSettingsSaving.value = false;
  }
}

onMounted(loadHistory);
</script>

<template>
  <v-layout class="chat-layout">
    <v-main class="chat-main">
      <v-alert v-if="cacheStale" type="warning" variant="tonal" density="compact" class="mx-4 mt-3">
        当前聊天记录可能来自旧核心缓存；失败的消息不会自动重试。
        <v-btn size="small" variant="text" :disabled="busy" @click="loadHistory">刷新记录</v-btn>
      </v-alert>
      <div class="chat-header d-flex align-center ga-3 px-4 pt-4">
        <div>
          <h1 class="text-h5 font-weight-bold">聊天</h1>
          <div class="text-caption text-medium-emphasis">WebChat 私聊 · 独立记忆空间</div>
        </div>
        <v-spacer />
        <v-btn variant="tonal" prepend-icon="mdi-cog-outline" @click="openWebChatSettings">
          WebChat 设置
        </v-btn>
      </div>
      <div ref="listEl" class="chat-scroll">
        <div class="pa-4">
          <div
            v-for="(m, i) in messages"
            :key="m.id"
            class="d-flex mb-2"
            :class="m.role === 'user' ? 'justify-end' : 'justify-start'"
          >
            <div class="bubble" :class="m.role">
              <div class="text-body-2" style="white-space: pre-wrap">{{ m.content }}</div>
              <div v-if="m.ts" class="text-caption text-disabled">{{ m.ts }}</div>
            </div>
          </div>
          <div v-if="!messages.length" class="text-body-2 text-medium-emphasis text-center pa-8">
            开始和 Stella 聊天吧。这里的对话与群聊记忆相互隔离（专属 webchat 空间）。
          </div>
        </div>
      </div>
      <div class="pa-4">
        <div class="d-flex ga-2">
          <v-text-field
            v-model="input"
            placeholder="输入消息…"
            density="comfortable"
            hide-details
            :disabled="busy || (system.managed && system.coreUnavailable)"
            @keydown.enter="send"
          />
          <v-btn color="primary" :loading="busy" :disabled="system.managed && system.coreUnavailable" @click="send">发送</v-btn>
          <v-btn icon="mdi-delete-outline" variant="text" @click="reset" />
        </div>
      </div>
    </v-main>
    <v-dialog
      :model-value="webChatSettingsDialog"
      max-width="760"
      @update:model-value="(open: boolean) => { if (!open) closeWebChatSettings(); }"
    >
      <v-card>
        <v-card-title>WebChat 设置</v-card-title>
        <v-card-text>
          <p class="text-body-2 text-medium-emphasis mb-4">
            这里设置聊天界面 WebChat 使用的人格。WebChat 的专属空间和虚拟会话身份由系统固定管理。
          </p>
          <v-progress-linear v-if="webChatSettingsLoading" indeterminate color="primary" class="mb-4" />
          <v-alert v-if="webChatSettingsMessage" type="info" variant="tonal">
            {{ webChatSettingsMessage }}
          </v-alert>
          <v-textarea
            v-if="webChatSpaceReady"
            v-model="webChatPrompt"
            label="WebChat 人格提示词"
            rows="12"
            auto-grow
            :disabled="webChatSettingsLoading || webChatSettingsSaving || !webChatSettingsLoaded"
          />
          <div class="text-caption text-medium-emphasis mt-2">专属空间：webchat · 虚拟会话：-1</div>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn :disabled="webChatSettingsSaving" @click="closeWebChatSettings">关闭</v-btn>
          <v-btn
            v-if="webChatSpaceReady"
            color="primary"
            :loading="webChatSettingsSaving"
            :disabled="webChatSettingsLoading || !webChatSettingsLoaded"
            @click="saveWebChatSettings"
          >
            保存 WebChat 设置
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-layout>
</template>

<style scoped>
.chat-layout { height: calc(100vh - 64px); }
.chat-main {
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.chat-header { flex: 0 0 auto; }
.chat-scroll {
  flex: 1;
  overflow-y: auto;
}
.bubble {
  max-width: 70%;
  padding: 8px 12px;
  border-radius: 12px;
  background: rgba(var(--v-theme-primary), 0.12);
}
.bubble.user {
  background: rgba(var(--v-theme-secondary), 0.2);
}
</style>
