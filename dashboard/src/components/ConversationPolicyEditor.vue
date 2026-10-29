<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import { api, unwrap } from '@/api/http';
import { idempotencyKey, revisionWriteOptions } from '@/api/system';
import { transportEvidence } from '@/data/transportEvidence';
import { toastApiError, useToast } from '@/stores/toast';
import { useSystemStore } from '@/stores/system';

type JsonObject = Record<string, unknown>;
interface SceneItem {
  conversation_key: string;
  connection_id: string;
  adapter: string;
  platform_scope: string;
  self_id: string;
  kind: string;
  scene_id: string;
  parent_path: string[];
  thread_id: string | null;
  memory_space: string;
  messages: number;
  last_ts: string | null;
}
interface Bundle {
  version: number;
  connections: Array<JsonObject & { connection_id: string; adapter: string; policy?: JsonObject }>;
  profiles: Array<JsonObject & { policy_profile_id: string; policy?: JsonObject }>;
  bindings: Array<JsonObject & {
    connection_id: string;
    scene: { kind: string; scene_id: string; parent_path?: string[]; thread_id?: string | null };
    policy_profile_id: string;
    policy?: JsonObject;
  }>;
  defaults?: JsonObject;
  platform_templates?: Record<string, JsonObject>;
}
interface SettingsSnapshot {
  settings: Bundle | null;
  effective_settings?: Bundle | null;
  applied_settings?: Bundle | null;
  valid: boolean;
  error_code?: string;
  desired_revision: string;
  applied_revision?: string | null;
  source?: string;
  effective_source?: string;
  applied_source?: string;
  restart_required?: boolean;
}
type Override = 'inherit' | 'true' | 'false';

const props = defineProps<{ spaceNames?: string[] }>();
const { t } = useI18n();
const toast = useToast();
const system = useSystemStore();
const scenes = ref<SceneItem[]>([]);
const snapshot = ref<SettingsSnapshot | null>(null);
const draft = ref<Bundle | null>(null);
const spaces = ref<string[]>([]);
const loadError = ref('');
const scenesError = ref('');
const revisionTag = ref('');
const loading = ref(true);
const saving = ref(false);
const selectedAdapter = ref('');
const selectedConnection = ref('');
const selectedKey = ref('');
const memorySpaceBlocked = ref(false);

const form = reactive({
  captureEnabled: 'inherit' as Override,
  llmEnabled: 'inherit' as Override,
  proactiveEnabled: 'inherit' as Override,
  replyMention: 'inherit' as Override,
  replyQuote: 'inherit' as Override,
  wakeMode: 'inherit',
  formatMode: 'inherit',
  segmentation: 'inherit',
  wakePrefixesMode: 'inherit' as 'inherit' | 'set',
  wakePrefixes: '',
  policyProfileId: '',
  personaRef: '',
  memorySpace: '',
});

const sceneOptions = computed(() => scenes.value.filter((scene) =>
  scene.adapter === selectedAdapter.value && scene.connection_id === selectedConnection.value));
const adapterOptions = computed(() => [...new Set(scenes.value.map((scene) => scene.adapter))]
  .map((value) => ({ title: value, value })));
const connectionOptions = computed(() => [...new Set(scenes.value
  .filter((scene) => scene.adapter === selectedAdapter.value)
  .map((scene) => scene.connection_id))]
  .map((value) => ({ title: value, value })));
const selectedScene = computed(() =>
  scenes.value.find((scene) => scene.conversation_key === selectedKey.value) ?? null);
const draftBundle = computed(() => draft.value);
const appliedBundle = computed(() => snapshot.value?.applied_settings ?? null);
const hasConnectionSettings = computed(() => Boolean(selectedScene.value && draft.value?.connections
  .some((connection) => connection.connection_id === selectedScene.value?.connection_id)));
const personaOptions = computed(() => [...new Set([
  ...spaces.value,
  ...(selectedScene.value?.memory_space ? [selectedScene.value.memory_space] : []),
])].map((value) => ({ title: value, value })));
const memorySpaceOptions = computed(() => [...new Map([
  { title: t('features.conversationPolicy.keepCurrentSpace'), value: selectedScene.value?.memory_space ?? '' },
  { title: t('features.conversationPolicy.unbound'), value: '' },
  ...personaOptions.value,
].map((item) => [item.value, item])).values()]);
const profileOptions = computed(() => (draft.value?.profiles ?? [])
  .map((profile) => ({ title: profile.policy_profile_id, value: profile.policy_profile_id })));
const overrideOptions = computed(() => [
  { title: t('features.conversationPolicy.inherit'), value: 'inherit' },
  { title: t('features.conversationPolicy.on'), value: 'true' },
  { title: t('features.conversationPolicy.off'), value: 'false' },
]);
const wakeModeOptions = computed(() => [
  { title: t('features.conversationPolicy.inherit'), value: 'inherit' },
  ...['mention', 'reply', 'prefix', 'all', 'private_direct'].map((value) => ({ title: value, value })),
]);
const formatOptions = computed(() => [
  { title: t('features.conversationPolicy.inherit'), value: 'inherit' },
  ...['native', 'plain', 'markdown'].map((value) => ({ title: value, value })),
]);
const segmentationOptions = computed(() => [
  { title: t('features.conversationPolicy.inherit'), value: 'inherit' },
  ...['auto', 'none', 'safe'].map((value) => ({ title: value, value })),
]);

const policyDefaults: Record<string, unknown> = {
  capture_enabled: false,
  llm_enabled: false,
  wake_mode: 'mention',
  wake_prefixes: [],
  reply_mention: false,
  reply_quote: false,
  format_mode: 'native',
  segmentation: 'auto',
  proactive_enabled: false,
  quiet_hours: null,
  requests_per_window: null,
  rate_window_seconds: null,
};
const policyFields = [
  'capture_enabled', 'llm_enabled', 'wake_mode', 'wake_prefixes', 'reply_mention',
  'reply_quote', 'format_mode', 'segmentation', 'proactive_enabled', 'quiet_hours',
  'requests_per_window', 'rate_window_seconds',
];

function cloneBundle(bundle: Bundle): Bundle {
  return JSON.parse(JSON.stringify(bundle)) as Bundle;
}

function bindingFor(bundle: Bundle | null, scene: SceneItem | null) {
  if (!bundle || !scene) return undefined;
  return bundle.bindings.find((binding) => binding.connection_id === scene.connection_id
    && binding.scene.kind === scene.kind
    && binding.scene.scene_id === scene.scene_id
    && JSON.stringify(binding.scene.parent_path ?? []) === JSON.stringify(scene.parent_path)
    && (binding.scene.thread_id ?? null) === scene.thread_id);
}

function resolvedPolicy(bundle: Bundle | null, scene: SceneItem | null) {
  const values = { ...policyDefaults };
  const sources: Record<string, string> = Object.fromEntries(
    policyFields.map((field) => [field, 'system_default']),
  );
  if (!bundle || !scene) return { values, sources };
  const apply = (source: string, layer?: JsonObject) => {
    if (!layer) return;
    for (const field of policyFields) {
      if (Object.hasOwn(layer, field)) {
        values[field] = layer[field];
        sources[field] = source;
      }
    }
  };
  const connection = bundle.connections.find((item) => item.connection_id === scene.connection_id);
  apply('global_defaults', bundle.defaults);
  apply('platform_template', bundle.platform_templates?.[scene.adapter]);
  apply('connection_default', connection?.policy);
  const binding = bindingFor(bundle, scene);
  const profile = bundle.profiles.find((item) => item.policy_profile_id === binding?.policy_profile_id);
  apply('profile', profile?.policy);
  apply('scene', binding?.policy);
  return { values, sources };
}

function displayValue(value: unknown): string {
  if (value === undefined || value === null) return '—';
  if (typeof value === 'boolean') return value ? t('features.conversationPolicy.on') : t('features.conversationPolicy.off');
  if (Array.isArray(value)) return value.length ? value.join(', ') : '[]';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

const desiredPolicy = computed(() => resolvedPolicy(draftBundle.value, selectedScene.value));
const appliedPolicy = computed(() => resolvedPolicy(appliedBundle.value, selectedScene.value));
const policyRows = computed(() => policyFields.map((field) => ({
  field,
  desired: displayValue(desiredPolicy.value.values[field]),
  source: desiredPolicy.value.sources[field],
  applied: displayValue(appliedPolicy.value.values[field]),
})));
const evidence = computed(() => {
  const adapterName = selectedScene.value?.adapter ?? '';
  return transportEvidence[adapterName] ?? null;
});
const evidenceRows = computed(() => Object.entries(evidence.value?.levels ?? {})
  .map(([level, result]) => ({ level, fixture: result.fixture, live: result.live })));

function resetForm(): void {
  const scene = selectedScene.value;
  const bundle = draft.value;
  const binding = bindingFor(bundle, scene);
  const scenePolicy = binding?.policy ?? {};
  const profiles = bundle?.profiles ?? [];
  const asOverride = (field: string): Override => !Object.hasOwn(scenePolicy, field)
    ? 'inherit'
    : scenePolicy[field] ? 'true' : 'false';
  form.captureEnabled = asOverride('capture_enabled');
  form.llmEnabled = asOverride('llm_enabled');
  form.proactiveEnabled = asOverride('proactive_enabled');
  form.replyMention = asOverride('reply_mention');
  form.replyQuote = asOverride('reply_quote');
  form.wakeMode = typeof scenePolicy.wake_mode === 'string' ? scenePolicy.wake_mode : 'inherit';
  form.formatMode = typeof scenePolicy.format_mode === 'string' ? scenePolicy.format_mode : 'inherit';
  form.segmentation = typeof scenePolicy.segmentation === 'string' ? scenePolicy.segmentation : 'inherit';
  form.wakePrefixesMode = Object.hasOwn(scenePolicy, 'wake_prefixes') ? 'set' : 'inherit';
  form.wakePrefixes = Array.isArray(scenePolicy.wake_prefixes)
    ? scenePolicy.wake_prefixes.map(String).join('\n')
    : '';
  form.policyProfileId = binding?.policy_profile_id ?? profiles[0]?.policy_profile_id ?? '';
  form.personaRef = String(binding?.persona_ref ?? '');
  form.memorySpace = String(binding?.memory_space ?? scene?.memory_space ?? '');
  memorySpaceBlocked.value = Boolean(scene?.messages && form.memorySpace !== scene.memory_space);
}

function chooseAdapter(value: string | null): void {
  selectedAdapter.value = value ?? '';
  selectedConnection.value = connectionOptions.value[0]?.value ?? '';
  selectedKey.value = sceneOptions.value[0]?.conversation_key ?? '';
  resetForm();
}

function chooseConnection(value: string | null): void {
  selectedConnection.value = value ?? '';
  selectedKey.value = sceneOptions.value[0]?.conversation_key ?? '';
  resetForm();
}

function chooseScene(value: string | null): void {
  selectedKey.value = value ?? '';
  resetForm();
}

function setOverride(policy: JsonObject, key: string, value: Override): void {
  if (value === 'inherit') delete policy[key];
  else policy[key] = value === 'true';
}

function applyForm(bundle: Bundle, scene: SceneItem): Bundle {
  const next = cloneBundle(bundle);
  if (!next.connections.some((connection) => connection.connection_id === scene.connection_id)) {
    throw new Error(t('features.conversationPolicy.connectionNotConfigured'));
  }
  let profileId = form.policyProfileId;
  if (!profileId) {
    profileId = `scene-${scene.connection_id.slice(0, 8)}`;
    if (!next.profiles.some((profile) => profile.policy_profile_id === profileId)) {
      next.profiles.push({ policy_profile_id: profileId, policy: {} });
    }
  }
  if (!next.profiles.some((profile) => profile.policy_profile_id === profileId)) {
    throw new Error(t('features.conversationPolicy.profileMissing'));
  }
  const existing = bindingFor(next, scene);
  const binding = existing ?? {
    connection_id: scene.connection_id,
    scene: {
      kind: scene.kind,
      scene_id: scene.scene_id,
      parent_path: [...scene.parent_path],
      ...(scene.thread_id ? { thread_id: scene.thread_id } : {}),
    },
    policy_profile_id: profileId,
    context_mode: 'scene',
    policy: {},
  };
  const policy: JsonObject = { ...(binding.policy ?? {}) };
  setOverride(policy, 'capture_enabled', form.captureEnabled);
  setOverride(policy, 'llm_enabled', form.llmEnabled);
  setOverride(policy, 'proactive_enabled', form.proactiveEnabled);
  setOverride(policy, 'reply_mention', form.replyMention);
  setOverride(policy, 'reply_quote', form.replyQuote);
  for (const [key, value] of [
    ['wake_mode', form.wakeMode],
    ['format_mode', form.formatMode],
    ['segmentation', form.segmentation],
  ] as const) {
    if (value === 'inherit') delete policy[key];
    else policy[key] = value;
  }
  if (form.wakePrefixesMode === 'set') {
    policy.wake_prefixes = form.wakePrefixes.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  } else {
    delete policy.wake_prefixes;
  }
  binding.policy_profile_id = profileId;
  binding.policy = policy;
  binding.persona_ref = form.personaRef || null;
  binding.memory_space = form.memorySpace || null;
  if (!existing) next.bindings.push(binding);
  return next;
}

async function loadScenes(): Promise<void> {
  scenesError.value = '';
  try {
    const data = await unwrap<{ scenes: SceneItem[] }>(api.get('/conversations/scenes'));
    scenes.value = data.scenes;
    if (!selectedScene.value && data.scenes.length) {
      selectedAdapter.value = data.scenes[0].adapter;
      selectedConnection.value = data.scenes[0].connection_id;
      selectedKey.value = data.scenes[0].conversation_key;
    }
  } catch (error) {
    scenesError.value = (error as Error).message;
  }
}

async function loadSettings(): Promise<void> {
  const response = await api.get('/platform/conversation-settings');
  const data = await unwrap(Promise.resolve(response)) as SettingsSnapshot;
  snapshot.value = data;
  revisionTag.value = String(response.headers.etag ?? '');
  if (!data.valid || !data.settings) {
    draft.value = null;
    loadError.value = data.error_code ?? 'transport_settings_invalid';
    return;
  }
  draft.value = cloneBundle(data.settings);
  loadError.value = '';
  resetForm();
}

async function load(): Promise<void> {
  loading.value = true;
  await system.refreshStatus();
  const [, settingsResult, spaceResult] = await Promise.allSettled([
    loadScenes(),
    loadSettings(),
    props.spaceNames?.length
      ? Promise.resolve({ spaces: props.spaceNames })
      : unwrap<{ spaces: Array<{ name: string }> }>(api.get('/spaces')),
  ]);
  if (spaceResult.status === 'fulfilled') {
    spaces.value = spaceResult.value.spaces.map((space) =>
      typeof space === 'string' ? space : space.name);
  }
  if (settingsResult.status === 'rejected') {
    loadError.value = (settingsResult.reason as Error).message;
  }
  resetForm();
  loading.value = false;
}

async function save(): Promise<void> {
  const scene = selectedScene.value;
  const current = draft.value;
  if (!scene || !current || !snapshot.value?.valid || saving.value || system.operationPending) return;
  if (scene.messages > 0 && form.memorySpace !== scene.memory_space) {
    memorySpaceBlocked.value = true;
    return;
  }
  saving.value = true;
  try {
    const next = applyForm(current, scene);
    await system.refreshStatus();
    const managed = system.managed;
    const options = managed
      ? revisionWriteOptions(snapshot.value.desired_revision, idempotencyKey('conversation-settings'))
      : { headers: { 'If-Match': revisionTag.value } };
    if (!managed && !revisionTag.value) throw new Error(t('features.conversationPolicy.revisionMissing'));
    const response = await api.put('/platform/conversation-settings', next, options);
    const result = await unwrap(Promise.resolve(response)) as SettingsSnapshot;
    snapshot.value = result;
    revisionTag.value = String(response.headers.etag ?? revisionTag.value);
    draft.value = cloneBundle(result.settings ?? next);
    if (managed) {
      system.noteDesiredRevision(result.desired_revision);
      if (system.coreReady) {
        try {
          await system.applyRevision(result.desired_revision);
          toast.success(t('features.conversationPolicy.saved'));
        } catch (error) {
          toast.warning(t('features.conversationPolicy.savedApplyFailed', {
            reason: (error as Error).message,
          }));
        }
      } else {
        toast.warning(t('features.conversationPolicy.savedPendingCore'));
      }
    } else if (result.restart_required) {
      toast.warning(t('features.conversationPolicy.savedRestartRequired'));
    } else {
      toast.success(t('features.conversationPolicy.saved'));
    }
    await loadSettings();
    resetForm();
  } catch (error) {
    toastApiError(toast, error);
  } finally {
    saving.value = false;
  }
}

watch(() => [form.memorySpace, selectedScene.value?.memory_space, selectedScene.value?.messages], () => {
  memorySpaceBlocked.value = Boolean(
    selectedScene.value?.messages && form.memorySpace !== selectedScene.value.memory_space,
  );
});

onMounted(() => { void load(); });
</script>

<template>
  <v-card class="pa-4 mb-6" :loading="loading">
    <div class="d-flex align-center flex-wrap ga-2 mb-2">
      <div class="text-h6">{{ t('features.conversationPolicy.title') }}</div>
      <v-spacer />
      <v-chip size="small" variant="tonal">{{ t('features.conversationPolicy.desired') }}: {{ snapshot?.desired_revision || '—' }}</v-chip>
      <v-chip size="small" variant="tonal" color="secondary">{{ t('features.conversationPolicy.applied') }}: {{ snapshot?.applied_revision || '—' }}</v-chip>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-3">{{ t('features.conversationPolicy.intro') }}</p>
    <v-alert v-if="loadError" type="error" variant="tonal" class="mb-3">
      {{ t('features.conversationPolicy.settingsUnavailable', { reason: loadError }) }}
    </v-alert>
    <v-alert v-if="scenesError" type="warning" variant="tonal" class="mb-3">
      {{ t('features.conversationPolicy.scenesUnavailable', { reason: scenesError }) }}
    </v-alert>
    <v-alert v-if="snapshot && snapshot.source !== snapshot.effective_source" type="info" variant="tonal" class="mb-3">
      {{ t('features.conversationPolicy.overlaySource', { source: snapshot.effective_source || snapshot.source || 'default' }) }}
    </v-alert>
    <v-row dense>
      <v-col cols="12" md="4">
        <v-select
          :model-value="selectedAdapter"
          :items="adapterOptions"
          :label="t('features.conversationPolicy.platform')"
          density="compact" hide-details="auto" :disabled="loading || !scenes.length"
          @update:model-value="chooseAdapter"
        />
      </v-col>
      <v-col cols="12" md="4">
        <v-select
          :model-value="selectedConnection"
          :items="connectionOptions"
          :label="t('features.conversationPolicy.connection')"
          density="compact" hide-details="auto" :disabled="loading || !connectionOptions.length"
          @update:model-value="chooseConnection"
        />
      </v-col>
      <v-col cols="12" md="4">
        <v-select
          :model-value="selectedKey"
          :items="sceneOptions"
          item-title="scene_id" item-value="conversation_key"
          :label="t('features.conversationPolicy.scene')"
          density="compact" hide-details="auto" :disabled="loading || !sceneOptions.length"
          @update:model-value="chooseScene"
        >
          <template #item="{ props: itemProps, item }">
            <v-list-item v-bind="itemProps" :subtitle="`${item.raw.kind} · ${item.raw.parent_path.join(' / ') || '—'}${item.raw.thread_id ? ` · ${item.raw.thread_id}` : ''}`" />
          </template>
        </v-select>
      </v-col>
    </v-row>

    <template v-if="selectedScene">
      <v-alert v-if="!hasConnectionSettings" type="warning" variant="tonal" class="my-3">
        {{ t('features.conversationPolicy.connectionNotConfigured') }}
      </v-alert>
      <v-alert v-if="memorySpaceBlocked" type="warning" variant="tonal" class="my-3">
        {{ t('features.conversationPolicy.historySpaceBlocked', { count: selectedScene.messages }) }}
      </v-alert>
      <div class="text-caption text-medium-emphasis mt-2 mb-3">
        {{ selectedScene.adapter }} · {{ selectedScene.self_id }} · {{ selectedScene.kind }}:{{ selectedScene.scene_id }}
        <span v-if="selectedScene.parent_path.length"> · {{ selectedScene.parent_path.join(' / ') }}</span>
        <span v-if="selectedScene.thread_id"> · {{ selectedScene.thread_id }}</span>
      </div>

      <v-row dense>
        <v-col cols="12" md="6">
          <v-select v-model="form.policyProfileId" :items="profileOptions" :label="t('features.conversationPolicy.profile')" density="compact" />
        </v-col>
        <v-col cols="12" md="6">
          <v-select v-model="form.personaRef" :items="[{ title: t('features.conversationPolicy.noPersona'), value: '' }, ...personaOptions]" :label="t('features.conversationPolicy.persona')" density="compact" />
        </v-col>
        <v-col cols="12" md="6">
          <v-select v-model="form.memorySpace" :items="memorySpaceOptions" :label="t('features.conversationPolicy.memorySpace')" density="compact" />
        </v-col>
        <v-col cols="12" md="6">
          <v-select v-model="form.wakeMode" :items="wakeModeOptions" :label="t('features.conversationPolicy.wakeMode')" density="compact" />
        </v-col>
        <v-col cols="12" md="6"><v-select v-model="form.captureEnabled" :items="overrideOptions" :label="t('features.conversationPolicy.capture')" density="compact" /></v-col>
        <v-col cols="12" md="6"><v-select v-model="form.llmEnabled" :items="overrideOptions" :label="t('features.conversationPolicy.llm')" density="compact" /></v-col>
        <v-col cols="12" md="6"><v-select v-model="form.proactiveEnabled" :items="overrideOptions" :label="t('features.conversationPolicy.proactive')" density="compact" /></v-col>
        <v-col cols="12" md="6"><v-select v-model="form.replyMention" :items="overrideOptions" :label="t('features.conversationPolicy.replyMention')" density="compact" /></v-col>
        <v-col cols="12" md="6"><v-select v-model="form.replyQuote" :items="overrideOptions" :label="t('features.conversationPolicy.replyQuote')" density="compact" /></v-col>
        <v-col cols="12" md="6"><v-select v-model="form.formatMode" :items="formatOptions" :label="t('features.conversationPolicy.formatMode')" density="compact" /></v-col>
        <v-col cols="12" md="6"><v-select v-model="form.segmentation" :items="segmentationOptions" :label="t('features.conversationPolicy.segmentation')" density="compact" /></v-col>
        <v-col cols="12" md="3">
          <v-select v-model="form.wakePrefixesMode" :items="[{ title: t('features.conversationPolicy.inherit'), value: 'inherit' }, { title: t('features.conversationPolicy.override'), value: 'set' }]" :label="t('features.conversationPolicy.prefixes')" density="compact" />
        </v-col>
        <v-col cols="12" md="9">
          <v-textarea v-model="form.wakePrefixes" :label="t('features.conversationPolicy.prefixesHint')" rows="2" auto-grow density="compact" :disabled="form.wakePrefixesMode === 'inherit'" />
        </v-col>
      </v-row>

      <v-table density="compact" class="mb-3">
        <thead><tr><th>{{ t('features.conversationPolicy.field') }}</th><th>{{ t('features.conversationPolicy.effective') }}</th><th>{{ t('features.conversationPolicy.source') }}</th><th>{{ t('features.conversationPolicy.appliedValue') }}</th></tr></thead>
        <tbody><tr v-for="row in policyRows" :key="row.field"><td>{{ row.field }}</td><td>{{ row.desired }}</td><td>{{ row.source }}</td><td>{{ row.applied }}</td></tr></tbody>
      </v-table>

      <v-card variant="tonal" class="pa-3 mb-3">
        <div class="text-subtitle-2">{{ t('features.conversationPolicy.capabilities') }}</div>
        <div class="text-body-2">{{ evidence?.capabilityProvider || t('features.conversationPolicy.capabilityUnknown') }}</div>
        <div class="text-caption text-medium-emphasis">{{ t('features.conversationPolicy.certification') }}: {{ evidence?.finalStatus || 'not_assessed' }}</div>
        <v-table v-if="evidenceRows.length" density="compact">
          <thead><tr><th>Level</th><th>{{ t('features.conversationPolicy.fixture') }}</th><th>{{ t('features.conversationPolicy.live') }}</th></tr></thead>
          <tbody><tr v-for="row in evidenceRows" :key="row.level"><td>{{ row.level }}</td><td>{{ row.fixture }}</td><td>{{ row.live }}</td></tr></tbody>
        </v-table>
      </v-card>
      <div class="d-flex justify-end">
        <v-btn color="primary" :loading="saving" :disabled="loading || !snapshot?.valid || !hasConnectionSettings || memorySpaceBlocked || system.operationPending" @click="save">
          {{ t('features.conversationPolicy.save') }}
        </v-btn>
      </div>
    </template>
    <v-alert v-else-if="!loading && !scenes.length" type="info" variant="tonal" class="mt-3">
      {{ t('features.conversationPolicy.noScenes') }}
    </v-alert>
  </v-card>
</template>
