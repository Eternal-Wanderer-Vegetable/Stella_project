<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

interface ConnectionStatus {
  adapter: string;
  instance_ref: string;
  connected: boolean;
  health: boolean | null;
}

interface LinkStatus {
  enabled: boolean;
  applicable?: boolean;
  connected: boolean | null;
  connected_seconds?: number | null;
  last_event_seconds_ago?: number | null;
  last_probe_ok?: boolean | null;
  healthy?: boolean | null;
  unavailable?: boolean;
  connections?: ConnectionStatus[];
}

const ONEBOT_V11_MODULE = 'nonebot.adapters.onebot.v11';
const link = ref<LinkStatus | null>(null);
const adapterModulesText = ref('');
const effectiveModules = ref<string[]>([]);
const processOverride = ref(false);
const error = ref('');
let timer: number | null = null;

const editingOneBot = ref(false);
const wsUrlsText = ref('');
const accessToken = ref('');
const host = ref('');
const port = ref('');
const toast = useToast();
const { t } = useI18n();

const configuredModules = computed(() =>
  adapterModulesText.value.split(/[\s,]+/).map((value) => value.trim()).filter(Boolean),
);
const oneBotEnabled = computed(
  () =>
    configuredModules.value.includes(ONEBOT_V11_MODULE)
    || effectiveModules.value.includes(ONEBOT_V11_MODULE),
);
const monitorApplicable = computed(() => link.value?.applicable !== false);
const healthy = computed<boolean | null>(() => {
  if (!link.value || link.value.unavailable || !monitorApplicable.value) return null;
  return link.value.healthy === true;
});
const linkColor = computed(() =>
  healthy.value === true ? 'success' : healthy.value === false ? 'warning' : 'secondary',
);

async function loadAdapterModules(): Promise<void> {
  try {
    const result = await unwrap<{
      modules: string[];
      effective_modules: string[];
      process_override: boolean;
    }>(api.get('/platform/adapters'));
    adapterModulesText.value = result.modules.join('\n');
    effectiveModules.value = result.effective_modules;
    processOverride.value = result.process_override;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function saveAdapterModules(): Promise<void> {
  try {
    const result = await unwrap<{
      modules: string[];
      restart_required: boolean;
    }>(
      api.put('/platform/adapters', { modules: configuredModules.value }),
    );
    adapterModulesText.value = result.modules.join('\n');
    toast.success(t('features.platforms.modulesSaved'));
    await loadAdapterModules();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function loadConfig(): Promise<void> {
  try {
    const cfg = await unwrap<{
      host: string;
      port: string;
      ws_urls: string[];
      has_token: boolean;
    }>(api.get('/platform/onebot'));
    host.value = cfg.host;
    port.value = String(cfg.port);
    wsUrlsText.value = cfg.ws_urls.join(', ');
    accessToken.value = '';
  } catch (err) {
    toastApiError(toast, err);
  }
}

function openEditor(): void {
  void loadConfig();
  editingOneBot.value = true;
}

async function saveOneBotConfig(): Promise<void> {
  try {
    await unwrap(
      api.put('/platform/onebot', {
        ws_urls: wsUrlsText.value.split(/[\s,]+/).filter(Boolean),
        access_token: accessToken.value,
        host: host.value,
        port: port.value,
      }),
    );
    toast.success(t('features.platforms.onebotSaved'));
    editingOneBot.value = false;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function load(): Promise<void> {
  try {
    link.value = await unwrap<LinkStatus>(api.get('/platform/link'));
    error.value = '';
  } catch (err) {
    error.value = (err as Error).message;
  }
}

const fmtSeconds = (value: number | null | undefined): string =>
  value === null || value === undefined ? '—' : `${Math.floor(value)}s`;

function healthLabel(value: boolean | null): string {
  if (value === null) return t('features.platforms.healthUnknown');
  return value ? t('features.platforms.healthy') : t('features.platforms.unhealthy');
}

onMounted(() => {
  void load();
  void loadAdapterModules();
  timer = window.setInterval(load, 5000);
});
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer);
});
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-1">
      <h1 class="text-h5 font-weight-bold">{{ t('features.platforms.title') }}</h1>
      <v-chip size="small" variant="tonal" color="secondary" class="ml-3">
        {{ t('features.platforms.subtitle') }}
      </v-chip>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">
      {{ t('features.platforms.intro') }}
    </p>
    <v-alert v-if="error" type="error" variant="tonal" class="mb-3">{{ error }}</v-alert>

    <v-card class="pa-4 mb-4">
      <div class="text-subtitle-1 font-weight-medium mb-2">
        {{ t('features.platforms.modulesTitle') }}
      </div>
      <v-textarea
        v-model="adapterModulesText"
        :label="t('features.platforms.modulesLabel')"
        :hint="t('features.platforms.modulesHint')"
        persistent-hint
        rows="2"
        auto-grow
        class="mt-2"
      />
      <div v-if="effectiveModules.length" class="text-caption text-medium-emphasis mt-2">
        {{ t('features.platforms.effectiveModules') }}: {{ effectiveModules.join(', ') }}
      </div>
      <v-alert v-if="processOverride" type="info" variant="tonal" density="compact" class="mt-3">
        {{ t('features.platforms.processOverride') }}
      </v-alert>
      <div class="d-flex justify-end mt-3">
        <v-btn color="primary" @click="saveAdapterModules">
          {{ t('features.platforms.saveModules') }}
        </v-btn>
      </div>
    </v-card>

    <v-card v-if="oneBotEnabled" class="pa-4 mb-4">
      <div class="d-flex align-center">
        <div class="text-subtitle-1 font-weight-medium">
          {{ t('features.platforms.onebotConfig') }}
        </div>
        <v-spacer />
        <v-btn color="primary" prepend-icon="mdi-pencil" @click="openEditor">
          {{ t('core.common.edit') }}
        </v-btn>
      </div>
      <p class="text-body-2 text-medium-emphasis mt-2 mb-0">
        {{ t('features.platforms.onebotConfigHint') }}
      </p>
    </v-card>

    <v-card class="pa-4" :loading="!link">
      <div class="d-flex align-center ga-3 mb-3">
        <v-icon
          :icon="healthy === true ? 'mdi-lan-connect' : 'mdi-lan-disconnect'"
          :color="linkColor"
          size="28"
        />
        <div class="text-subtitle-1 font-weight-medium">
          {{ t('features.platforms.connectionsTitle') }}
        </div>
        <v-chip :color="linkColor" size="small" variant="tonal">
          {{ healthy === null
            ? (link?.unavailable ? t('features.platforms.healthUnknown') : t('features.platforms.notApplicable'))
            : healthLabel(healthy) }}
        </v-chip>
      </div>

      <v-alert v-if="link && link.applicable === false" type="info" variant="tonal" class="mb-3">
        {{ t('features.platforms.noOnebotNeeded') }}
      </v-alert>
      <v-alert v-else-if="link && healthy === false" type="warning" variant="tonal" class="mb-3">
        {{ t('features.platforms.onebotNotReady') }}
      </v-alert>

      <v-table v-if="link?.connections?.length" density="comfortable">
        <thead>
          <tr>
            <th>{{ t('features.platforms.adapter') }}</th>
            <th>{{ t('features.platforms.instance') }}</th>
            <th>{{ t('features.platforms.connected') }}</th>
            <th>{{ t('features.platforms.health') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="connection in link.connections" :key="connection.instance_ref">
            <td>{{ connection.adapter }}</td>
            <td><code>{{ connection.instance_ref }}</code></td>
            <td>{{ connection.connected ? t('features.platforms.yes') : t('features.platforms.no') }}</td>
            <td>{{ healthLabel(connection.health) }}</td>
          </tr>
        </tbody>
      </v-table>
      <div v-else-if="link" class="text-body-2 text-medium-emphasis">
        {{ t('features.platforms.noConnections') }}
      </div>

      <v-row v-if="link && link.applicable !== false" class="mt-2">
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">{{ t('features.platforms.connected') }}</div>
          <div>{{ link.connected === null ? '—' : link.connected ? t('features.platforms.yes') : t('features.platforms.no') }}</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">{{ t('features.platforms.connectionDuration') }}</div>
          <div>{{ fmtSeconds(link.connected_seconds) }}</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">{{ t('features.platforms.lastEvent') }}</div>
          <div>{{ fmtSeconds(link.last_event_seconds_ago) }}</div>
        </v-col>
        <v-col cols="6" md="3">
          <div class="text-caption text-medium-emphasis">{{ t('features.platforms.lastProbe') }}</div>
          <div>{{ link.last_probe_ok == null ? '—' : healthLabel(link.last_probe_ok) }}</div>
        </v-col>
      </v-row>
    </v-card>

    <v-dialog v-model="editingOneBot" width="560">
      <v-card>
        <v-card-title>{{ t('features.platforms.onebotConfig') }}</v-card-title>
        <v-card-text>
          <v-text-field
            v-model="host"
            :label="t('features.platforms.host')"
          />
          <v-text-field v-model="port" :label="t('features.platforms.port')" />
          <v-textarea
            v-model="wsUrlsText"
            :label="t('features.platforms.wsUrls')"
            :hint="t('features.platforms.wsUrlsHint')"
            persistent-hint
          />
          <v-text-field
            v-model="accessToken"
            :label="t('features.platforms.accessToken')"
            type="password"
            :hint="t('features.platforms.accessTokenHint')"
            persistent-hint
          />
          <v-alert type="info" density="compact" variant="tonal" class="mt-2">
            {{ t('features.platforms.restartHint') }}
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="editingOneBot = false">{{ t('core.common.cancel') }}</v-btn>
          <v-btn color="primary" @click="saveOneBotConfig">{{ t('core.common.save') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
