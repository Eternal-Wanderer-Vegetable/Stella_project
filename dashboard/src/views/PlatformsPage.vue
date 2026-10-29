<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import { api, unwrap } from '@/api/http';
import ConversationPolicyEditor from '@/components/ConversationPolicyEditor.vue';
import { idempotencyKey, revisionWriteOptions } from '@/api/system';
import { toastApiError, useToast } from '@/stores/toast';
import { useSystemStore } from '@/stores/system';
import { nonebotAdapterPresets } from '@/data/nonebotAdapterPresets';
import type { AdapterPresetField, AdapterPresetSection } from '@/data/nonebotAdapterPresets';
import adapterCatalogSnapshot from '../../../webui/services/nonebot_adapter_catalog.json';

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

interface AdapterCatalogEntry {
  name: string;
  module: string;
  package: string;
  description: string;
  homepage: string;
  official: boolean;
  tags: string[];
  available?: boolean;
  unavailable_reason?: string;
  requires_python?: string;
}

interface AdapterEnvEntry {
  key: string;
  module: string;
  value: string;
  has_value: boolean;
  sensitive: boolean;
  sensitive_paths?: string[];
  process_override: boolean;
}

const bundledCatalog = adapterCatalogSnapshot as {
  adapters: AdapterCatalogEntry[];
};

type PlatformKey = 'onebot' | 'qq' | 'telegram' | 'discord';
type PlatformSnapshot = {
  onebot: { host: string; port: string; ws_urls: string[]; has_token: boolean };
  qq: { app_id: string; has_secret: boolean; use_websocket: boolean; intent: Record<string, boolean>; additional_bots: number };
  telegram: { has_token: boolean; is_webhook: boolean; api_server: string; has_proxy: boolean; webhook_url: string; additional_bots: number };
  discord: { has_token: boolean; intent: Record<string, boolean>; has_proxy: boolean; register_all_commands: boolean; additional_bots: number };
};

const presets: Array<{
  key: PlatformKey;
  module: string;
}> = [
  { key: 'onebot', module: 'nonebot.adapters.onebot.v11' },
  { key: 'qq', module: 'nonebot.adapters.qq' },
  { key: 'telegram', module: 'nonebot.adapters.telegram' },
  { key: 'discord', module: 'nonebot.adapters.discord' },
];

const qqIntentNames = [
  'guilds', 'guild_members', 'guild_messages', 'guild_message_reactions', 'direct_message',
  'open_forum_event', 'audio_live_member', 'group_members', 'c2c_group_at_messages',
  'interaction', 'message_audit', 'forum_event', 'audio_action', 'at_messages',
];
const discordIntentNames = ['guild_messages', 'direct_messages', 'message_content'];
const moduleToPreset = new Map(presets.map((preset) => [preset.module, preset.key]));
const bundledUnavailable = new Map(
  bundledCatalog.adapters
    .filter((adapter) => adapter.available === false)
    .map((adapter) => [adapter.module, adapter]),
);

const link = ref<LinkStatus | null>(null);
const connectionStatusDialog = ref(false);
const adapterCatalog = ref<AdapterCatalogEntry[]>(bundledCatalog.adapters);
const catalogSearch = ref('');
const catalogDialog = ref(false);
const customAdapterDialog = ref(false);
const customModuleDraft = ref('');
const customModuleError = ref('');
const adapterConfigDialog = ref(false);
const configuringModule = ref('');
const selected = reactive<Record<PlatformKey, boolean>>({
  onebot: false, qq: false, telegram: false, discord: false,
});
const selectedGenericModules = ref<string[]>([]);
const installedPackages = ref<Record<string, string | null>>({});
const adapterEnv = ref<AdapterEnvEntry[]>([]);
const processOverride = ref(false);
const driverProcessOverride = ref(false);
const saveSupported = ref(false);
const savedDraftSnapshot = ref('');
const packageStatusSupported = ref(true);
const customModulesText = ref('');
const driver = ref('');
const error = ref('');
const desiredRevision = ref('');
const savingModules = ref(false);
const savingOneBot = ref(false);
const adapterLoadFailed = ref(false);
const loadingAdapters = ref(true);
const saving = ref(false);
let timer: number | null = null;

const onebot = reactive({
  mode: 'reverse' as 'reverse' | 'forward',
  host: '0.0.0.0',
  port: '8080',
  wsUrlsText: '',
  accessToken: '',
  hasToken: false,
});
const qq = reactive({
  appId: '',
  appSecret: '',
  hasSecret: false,
  useWebsocket: true,
  intent: Object.fromEntries(qqIntentNames.map((key) => [key, false])) as Record<string, boolean>,
});
const telegram = reactive({
  token: '',
  hasToken: false,
  isWebhook: false,
  apiServer: 'https://api.telegram.org/',
  webhookUrl: '',
  proxy: '',
  hasProxy: false,
});
const discord = reactive({
  token: '',
  hasToken: false,
  proxy: '',
  hasProxy: false,
  registerAllCommands: false,
  intent: { guild_messages: true, direct_messages: true, message_content: false } as Record<string, boolean>,
});

const toast = useToast();
const system = useSystemStore();
const { t } = useI18n();
const customModules = computed(() =>
  [...new Set(customModulesText.value
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter((value) => value && !adapterCatalog.value.some((adapter) => adapter.module === value)))],
);
const enabledModules = computed(() => {
  const known = presets.filter((preset) => selected[preset.key]).map((preset) => preset.module);
  return [...new Set([...known, ...selectedGenericModules.value, ...customModules.value])];
});
const filteredCatalog = computed(() => {
  const query = catalogSearch.value.trim().toLocaleLowerCase();
  const available = adapterCatalog.value.filter(isAdapterAvailable);
  if (!query) return available;
  return available.filter((adapter) =>
    [adapter.name, adapter.module, adapter.package, adapter.description, ...adapter.tags]
      .some((value) => value.toLocaleLowerCase().includes(query)),
  );
});
const selectedCatalog = computed(() => adapterCatalog.value.filter((adapter) => isAdapterSelected(adapter.module)));
const selectedAdapterCards = computed<AdapterCatalogEntry[]>(() => [
  ...selectedCatalog.value,
  ...customModules.value.map((module) => ({
    name: module,
    module,
    package: '',
    description: '',
    homepage: '',
    official: false,
    tags: [],
    available: true,
  })),
]);
const configuringAdapter = computed(() =>
  selectedAdapterCards.value.find((adapter) => adapter.module === configuringModule.value) ?? null,
);
const configuringPreset = computed(() => moduleToPreset.get(configuringModule.value) ?? null);
const configuringSchema = computed(() => nonebotAdapterPresets[configuringModule.value] ?? null);
const currentAdapterEnv = computed(() => adapterEnv.value
  .map((entry, index) => ({ entry, index }))
  .filter(({ entry }) => entry.module === configuringModule.value));
const presetEnvKeys = computed(() => new Set(
  (configuringSchema.value?.sections ?? []).flatMap((section) => [
    ...(section.envKey ? [section.envKey] : []),
    ...section.fields.flatMap((field) => field.envKey ? [field.envKey] : []),
  ]),
));
const advancedAdapterEnv = computed(() => currentAdapterEnv.value
  .filter(({ entry }) => !presetEnvKeys.value.has(entry.key)));
const unassignedAdapterEnv = computed(() => adapterEnv.value
  .map((entry, index) => ({ entry, index }))
  .filter(({ entry }) => !entry.module));
const adapterEnvModuleItems = computed(() => [
  { title: t('features.platforms.adapterEnvKeepUnassigned'), value: '' },
  ...selectedAdapterCards.value.map((adapter) => ({
    title: moduleToPreset.has(adapter.module)
      ? t(`features.platforms.cards.${moduleToPreset.get(adapter.module)}`)
      : adapter.name,
    value: adapter.module,
  })),
  ...customModules.value.map((module) => ({ title: module, value: module })),
]);
const dialogProcessOverrideKeys = computed(() => adapterEnv.value
  .filter((entry) => entry.process_override
    && (!entry.module || entry.module === configuringModule.value))
  .map((entry) => entry.key));
const unavailableSelected = computed(() => selectedCatalog.value.filter((adapter) => !isAdapterAvailable(adapter)));
const addableCatalogCount = computed(() => adapterCatalog.value.filter(isAdapterAvailable).length);
const monitorApplicable = computed(() => link.value?.applicable !== false);
const healthy = computed<boolean | null>(() => {
  if (!link.value || link.value.unavailable || !monitorApplicable.value) return null;
  return link.value.healthy === true;
});
const linkColor = computed(() =>
  healthy.value === true ? 'success' : healthy.value === false ? 'warning' : 'secondary',
);
const hasUnsavedChanges = computed(() =>
  saveSupported.value
    && !loadingAdapters.value
    && !adapterLoadFailed.value
    && Boolean(savedDraftSnapshot.value)
    && savedDraftSnapshot.value !== currentDraftSnapshot(),
);
const configuringRemotePlatform = computed(() =>
  configuringModule.value !== 'nonebot.adapters.onebot.v11'
    && configuringModule.value !== 'nonebot.adapters.console'
    && isModuleAvailable(configuringModule.value),
);

function isAdapterSelected(module: string): boolean {
  const presetKey = moduleToPreset.get(module);
  return presetKey
    ? selected[presetKey]
    : selectedGenericModules.value.includes(module);
}

function isAdapterAvailable(adapter: AdapterCatalogEntry): boolean {
  return adapter.available !== false;
}

function isModuleAvailable(module: string): boolean {
  const adapter = adapterCatalog.value.find((item) => item.module === module);
  return !adapter || isAdapterAvailable(adapter);
}

function adapterUnavailableReason(adapter: AdapterCatalogEntry): string {
  return adapter.unavailable_reason
    ? t(`features.platforms.unavailableReasons.${adapter.unavailable_reason}`)
    : t('features.platforms.unavailableGeneric');
}

function adapterDisplayName(module: string): string {
  const presetKey = moduleToPreset.get(module);
  if (presetKey) return t(`features.platforms.cards.${presetKey}`);
  return adapterCatalog.value.find((adapter) => adapter.module === module)?.name ?? module;
}

function setAdapterSelected(module: string, enabled: boolean): void {
  const catalogEntry = adapterCatalog.value.find((adapter) => adapter.module === module);
  if (enabled && catalogEntry && !isAdapterAvailable(catalogEntry)) return;
  const presetKey = moduleToPreset.get(module);
  if (presetKey) {
    selected[presetKey] = enabled;
    return;
  }
  selectedGenericModules.value = enabled
    ? [...new Set([...selectedGenericModules.value, module])]
    : selectedGenericModules.value.filter((item) => item !== module);
}

function toggleCatalogAdapter(adapter: AdapterCatalogEntry): void {
  if (!isAdapterAvailable(adapter)) return;
  setAdapterSelected(adapter.module, !isAdapterSelected(adapter.module));
}

function addCustomAdapterModule(): void {
  const module = customModuleDraft.value.trim();
  customModuleError.value = '';
  if (!module) return;
  if (!/^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$/.test(module)) {
    customModuleError.value = t('features.platforms.customModuleInvalid');
    return;
  }
  const catalogEntry = adapterCatalog.value.find((adapter) => adapter.module === module);
  if (catalogEntry) {
    if (!isAdapterAvailable(catalogEntry)) {
      customModuleError.value = t('features.platforms.customModuleBlocked');
      return;
    }
    setAdapterSelected(module, true);
    customModuleDraft.value = '';
    customAdapterDialog.value = false;
    return;
  }
  if (customModules.value.includes(module)) {
    customModuleError.value = t('features.platforms.customModuleDuplicate');
    return;
  }
  customModulesText.value = [...customModules.value, module].join('\n');
  customModuleDraft.value = '';
  customAdapterDialog.value = false;
}

function openCustomAdapterDialog(): void {
  customModuleDraft.value = '';
  customModuleError.value = '';
  customAdapterDialog.value = true;
}

function openAdapterConfig(module: string): void {
  if (!isModuleAvailable(module)) return;
  configuringModule.value = module;
  adapterConfigDialog.value = true;
}

function removeAdapterCard(module: string): void {
  if (adapterCatalog.value.some((adapter) => adapter.module === module)) {
    setAdapterSelected(module, false);
    return;
  }
  customModulesText.value = customModules.value.filter((item) => item !== module).join('\n');
}

function addAdapterEnvEntry(): void {
  adapterEnv.value.push({
    key: '', module: configuringModule.value, value: '', has_value: false,
    sensitive: false, process_override: false,
  });
}

function findAdapterEnvEntry(envKey: string): AdapterEnvEntry | undefined {
  return adapterEnv.value.find((entry) =>
    entry.key === envKey && entry.module === configuringModule.value,
  );
}

function ensureAdapterEnvEntry(envKey: string): AdapterEnvEntry {
  const existing = findAdapterEnvEntry(envKey);
  if (existing) return existing;
  const entry: AdapterEnvEntry = {
    key: envKey,
    module: configuringModule.value,
    value: '',
    has_value: false,
    sensitive: isSensitiveAdapterEnv(envKey),
    sensitive_paths: [],
    process_override: false,
  };
  adapterEnv.value.push(entry);
  return entry;
}

function presetFieldValue(field: AdapterPresetField): string | boolean {
  const entry = field.envKey ? findAdapterEnvEntry(field.envKey) : undefined;
  const fallback = field.defaultValue ?? (field.type === 'boolean' ? false : '');
  if (!entry) return fallback;
  if (field.type === 'boolean') return /^(1|true|yes|on)$/i.test(entry.value.trim());
  if (field.type === 'string-list') {
    try {
      const parsed = JSON.parse(entry.value);
      if (Array.isArray(parsed)) return parsed.join('\n');
    } catch {
      // Keep malformed legacy values editable as plain text.
    }
  }
  return entry.value;
}

function setPresetFieldValue(field: AdapterPresetField, value: unknown): void {
  if (!field.envKey) return;
  const entry = ensureAdapterEnvEntry(field.envKey);
  if (field.type === 'boolean') {
    entry.value = value ? 'true' : 'false';
  } else if (field.type === 'string-list') {
    const items = String(value ?? '').split(/[\r\n,;]+/).map((item) => item.trim()).filter(Boolean);
    entry.value = JSON.stringify(items);
  } else {
    entry.value = String(value ?? '');
  }
  entry.has_value = Boolean(entry.value);
}

function parsePresetBotList(section: AdapterPresetSection): Record<string, unknown>[] {
  if (!section.envKey) return [];
  const value = findAdapterEnvEntry(section.envKey)?.value;
  if (!value) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is Record<string, unknown> =>
        Boolean(item) && typeof item === 'object' && !Array.isArray(item),
      )
      : [];
  } catch {
    return [];
  }
}

function nestedValue(record: Record<string, unknown>, path: string): unknown {
  return path.split('.').reduce<unknown>((current, part) => {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return undefined;
    return (current as Record<string, unknown>)[part];
  }, record);
}

function presetBotFieldValue(
  section: AdapterPresetSection,
  index: number,
  field: AdapterPresetField,
): string | boolean {
  const bot = parsePresetBotList(section)[index];
  const value = bot && field.path ? nestedValue(bot, field.path) : undefined;
  if (field.type === 'boolean') {
    return typeof value === 'boolean' ? value : Boolean(field.defaultValue ?? false);
  }
  if (field.type === 'string-list') {
    return Array.isArray(value) ? value.map(String).join('\n') : '';
  }
  if (field.type === 'json') {
    return value === undefined ? '' : JSON.stringify(value, null, 2);
  }
  return value === undefined || value === null ? String(field.defaultValue ?? '') : String(value);
}

function setNestedValue(record: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split('.');
  let current = record;
  for (const part of parts.slice(0, -1)) {
    if (!current[part] || typeof current[part] !== 'object' || Array.isArray(current[part])) {
      current[part] = {};
    }
    current = current[part] as Record<string, unknown>;
  }
  current[parts.at(-1) ?? path] = value;
}

function removeNestedValue(record: Record<string, unknown>, path: string): void {
  const parts = path.split('.');
  let current: Record<string, unknown> = record;
  for (const part of parts.slice(0, -1)) {
    const child = current[part];
    if (!child || typeof child !== 'object' || Array.isArray(child)) return;
    current = child as Record<string, unknown>;
  }
  delete current[parts.at(-1) ?? path];
}

function toPresetBotValue(field: AdapterPresetField, value: unknown): unknown {
  if (field.type === 'boolean') return Boolean(value);
  if (field.type === 'number') {
    const text = String(value ?? '').trim();
    if (!text) return '';
    const number = Number(text);
    return Number.isFinite(number) ? number : text;
  }
  if (field.type === 'string-list') {
    return String(value ?? '').split(/[\r\n,;]+/).map((item) => item.trim()).filter(Boolean);
  }
  if (field.type === 'json') {
    const text = String(value ?? '').trim();
    if (!text) return undefined;
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  }
  return String(value ?? '');
}

function setPresetBotFieldValue(
  section: AdapterPresetSection,
  index: number,
  field: AdapterPresetField,
  value: unknown,
): void {
  if (!section.envKey || !field.path) return;
  const entry = ensureAdapterEnvEntry(section.envKey);
  const bots = parsePresetBotList(section);
  const bot = bots[index];
  if (!bot) return;
  const nextValue = toPresetBotValue(field, value);
  if (nextValue === undefined) removeNestedValue(bot, field.path);
  else setNestedValue(bot, field.path, nextValue);
  entry.value = JSON.stringify(bots);
  entry.has_value = true;
}

function addPresetBot(section: AdapterPresetSection): void {
  if (!section.envKey) return;
  const entry = ensureAdapterEnvEntry(section.envKey);
  const bots = parsePresetBotList(section);
  const bot: Record<string, unknown> = {};
  for (const field of section.fields) {
    if (field.path && field.defaultValue !== undefined) {
      setNestedValue(bot, field.path, field.defaultValue);
    }
  }
  bots.push(bot);
  entry.value = JSON.stringify(bots);
  entry.has_value = true;
}

function removePresetBot(section: AdapterPresetSection, index: number): void {
  if (!section.envKey) return;
  const entry = ensureAdapterEnvEntry(section.envKey);
  const bots = parsePresetBotList(section);
  bots.splice(index, 1);
  entry.value = JSON.stringify(bots);
  entry.has_value = true;
}

function presetSecretSaved(envKey: string, path?: string, index?: number): boolean {
  const entry = findAdapterEnvEntry(envKey);
  if (!entry) return false;
  if (!path) return entry.sensitive && entry.has_value;
  const jsonPath = `/${index ?? 0}/${path.split('.').map((part) =>
    part.replace(/~/g, '~0').replace(/\//g, '~1'),
  ).join('/')}`;
  return Boolean(entry.sensitive_paths?.includes(jsonPath));
}

function presetInputType(type: AdapterPresetField['type']): string {
  return type === 'secret' ? 'password' : type === 'number' ? 'number' : 'text';
}

function isPresetSecret(field: AdapterPresetField): boolean {
  return field.type === 'secret'
    || isSensitiveAdapterEnv(field.path ?? '')
    || isSensitiveAdapterEnv(field.envKey ?? '');
}

function isPresetTextArea(type: AdapterPresetField['type']): boolean {
  return type === 'multiline' || type === 'string-list' || type === 'json';
}

function removeAdapterEnvEntry(index: number): void {
  adapterEnv.value.splice(index, 1);
}

function isSensitiveAdapterEnv(key: string): boolean {
  const parts = key.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
  if (parts.includes('token') && parts.some((part) => /^(expires?|expiry|expiration)$/.test(part))) {
    return parts.some((part) => ['secret', 'password', 'passwd', 'cookie', 'credential'].includes(part));
  }
  return parts.some((part) => [
    'token', 'secret', 'password', 'passwd', 'cookie', 'proxy', 'ticket', 'credential',
    'signature', 'authorization', 'passphrase',
  ].includes(part))
    || /(^|_)(api|access|private|client|app|verify|encrypt|recovery)_key($|_)/i.test(key)
    || /(^|_)webhook_url($|_)/i.test(key);
}

async function loadAdapters(): Promise<void> {
  loadingAdapters.value = true;
  try {
    const result = await unwrap<{
      modules: string[];
      process_override: boolean;
      desired_revision?: string;
      driver: string;
      driver_process_override: boolean;
      installed_packages: Record<string, string | null>;
      catalog?: AdapterCatalogEntry[];
      adapter_env?: AdapterEnvEntry[];
      connections?: PlatformSnapshot;
    }>(api.get('/platform/adapters'));
    let config = result.connections;
    saveSupported.value = Boolean(
      config
        && result.installed_packages
        && Array.isArray(result.catalog)
        && result.catalog.length > 0
        && Array.isArray(result.adapter_env),
    );
    packageStatusSupported.value = Boolean(result.installed_packages);
    const catalog = result.catalog?.length ? result.catalog : bundledCatalog.adapters;
    adapterCatalog.value = catalog.map((adapter) => {
      const localPolicy = bundledUnavailable.get(adapter.module);
      return localPolicy ? { ...adapter, ...localPolicy } : adapter;
    });
    if (!config) {
      const legacyOnebot = await unwrap<PlatformSnapshot['onebot']>(api.get('/platform/onebot'));
      config = {
        onebot: legacyOnebot,
        qq: {
          app_id: '', has_secret: false, use_websocket: true,
          intent: Object.fromEntries(qqIntentNames.map((key) => [key, false])),
          additional_bots: 0,
        },
        telegram: {
          has_token: false, is_webhook: false, api_server: 'https://api.telegram.org/',
          has_proxy: false, webhook_url: '', additional_bots: 0,
        },
        discord: {
          has_token: false, intent: { guild_messages: true, direct_messages: true, message_content: false },
          has_proxy: false, register_all_commands: false, additional_bots: 0,
        },
      };
    }
    const modules = result.modules ?? [];
    for (const preset of presets) {
      selected[preset.key] = modules.includes(preset.module);
    }
    const catalogModules = new Set(adapterCatalog.value.map((adapter) => adapter.module));
    selectedGenericModules.value = modules.filter((module) =>
      !moduleToPreset.has(module) && catalogModules.has(module),
    );
    customModulesText.value = modules.filter((module) => !catalogModules.has(module)).join('\n');
    processOverride.value = result.process_override;
    desiredRevision.value = result.desired_revision ?? system.status?.desired_revision ?? '';
    driverProcessOverride.value = result.driver_process_override;
    installedPackages.value = result.installed_packages ?? {};
    adapterEnv.value = (result.adapter_env ?? []).map((entry) => ({
      ...entry,
      module: entry.module ?? '',
    }));
    driver.value = result.driver ?? '';

    Object.assign(onebot, {
      host: config.onebot.host,
      port: String(config.onebot.port),
      wsUrlsText: config.onebot.ws_urls.join('\n'),
      mode: config.onebot.ws_urls.length ? 'forward' : 'reverse',
      hasToken: config.onebot.has_token,
      accessToken: '',
    });
    Object.assign(qq, {
      appId: config.qq.app_id,
      hasSecret: config.qq.has_secret,
      useWebsocket: config.qq.use_websocket,
      appSecret: '',
    });
    Object.assign(qq.intent, config.qq.intent);
    Object.assign(telegram, {
      hasToken: config.telegram.has_token,
      isWebhook: config.telegram.is_webhook,
      apiServer: config.telegram.api_server,
      webhookUrl: config.telegram.webhook_url,
      hasProxy: config.telegram.has_proxy,
      token: '',
      proxy: '',
    });
    Object.assign(discord, {
      hasToken: config.discord.has_token,
      hasProxy: config.discord.has_proxy,
      registerAllCommands: config.discord.register_all_commands,
      token: '',
      proxy: '',
    });
    Object.assign(discord.intent, config.discord.intent);
    savedDraftSnapshot.value = currentDraftSnapshot();
    adapterLoadFailed.value = false;
  } catch (err) {
    adapterLoadFailed.value = true;
    toastApiError(toast, err);
  } finally {
    loadingAdapters.value = false;
  }
}

function currentDraftSnapshot(): string {
  return JSON.stringify({
    modules: enabledModules.value,
    driver: driver.value,
    onebot: {
      mode: onebot.mode,
      host: onebot.host,
      port: onebot.port,
      wsUrlsText: onebot.wsUrlsText,
      accessToken: onebot.accessToken,
      hasToken: onebot.hasToken,
    },
    qq: {
      appId: qq.appId,
      appSecret: qq.appSecret,
      hasSecret: qq.hasSecret,
      useWebsocket: qq.useWebsocket,
      intent: qq.intent,
    },
    telegram: {
      token: telegram.token,
      hasToken: telegram.hasToken,
      isWebhook: telegram.isWebhook,
      apiServer: telegram.apiServer,
      webhookUrl: telegram.webhookUrl,
      proxy: telegram.proxy,
      hasProxy: telegram.hasProxy,
    },
    discord: {
      token: discord.token,
      hasToken: discord.hasToken,
      proxy: discord.proxy,
      hasProxy: discord.hasProxy,
      registerAllCommands: discord.registerAllCommands,
      intent: discord.intent,
    },
    adapterEnv: adapterEnv.value.map((entry) => ({
      key: entry.key,
      module: entry.module,
      value: entry.value,
      has_value: entry.has_value,
    })),
  });
}

async function saveAdapters(): Promise<void> {
  if (saving.value || system.operationPending) return;
  saving.value = true;
  const connections: Record<string, unknown> = {};
  if (selected.onebot) {
    connections.onebot = {
      host: onebot.host,
      port: onebot.port,
      ws_urls: onebot.mode === 'forward'
        ? onebot.wsUrlsText.split(/[\s,]+/).map((url) => url.trim()).filter(Boolean)
        : [],
      access_token: onebot.accessToken,
    };
  }
  if (selected.qq) {
    connections.qq = {
      app_id: qq.appId,
      app_secret: qq.appSecret,
      use_websocket: qq.useWebsocket,
      intent: qq.intent,
    };
  }
  if (selected.telegram) {
    connections.telegram = {
      token: telegram.token,
      is_webhook: telegram.isWebhook,
      api_server: telegram.apiServer,
      webhook_url: telegram.webhookUrl,
      proxy: telegram.proxy,
    };
  }
  if (selected.discord) {
    connections.discord = {
      token: discord.token,
      proxy: discord.proxy,
      register_all_commands: discord.registerAllCommands,
      intent: discord.intent,
    };
  }

  try {
    await system.refreshStatus();
    const managed = system.managed;
    const revision = desiredRevision.value || system.status?.desired_revision || '';
    const options = managed
      ? revisionWriteOptions(revision, idempotencyKey('platform-adapters'))
      : undefined;
    const result = await unwrap<{
      revision_id?: string;
      desired_revision?: string;
    }>(api.put('/platform/adapters', {
      modules: enabledModules.value,
      driver: driver.value,
      connections,
      adapter_env: adapterEnv.value
        .filter((entry) => entry.key.trim())
        .map((entry) => ({ key: entry.key, value: entry.value, module: entry.module })),
    }, options));
    const nextRevision = result.desired_revision ?? result.revision_id ?? revision;
    desiredRevision.value = nextRevision;
    if (managed) {
      system.noteDesiredRevision(nextRevision);
      await system.applyRevision(nextRevision);
      toast.success(t('features.platforms.modulesApplied'));
    } else {
      toast.success(t('features.platforms.saved'));
    }
    await loadAdapters();
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    saving.value = false;
  }
}

async function loadLink(): Promise<void> {
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

function packageVersion(packageName: string): string | null {
  return installedPackages.value[packageName] ?? null;
}

function useRecommendedDriver(): void {
  driver.value = '~fastapi+~httpx+~websockets';
}

onMounted(() => {
  void loadLink();
  void loadAdapters();
  timer = window.setInterval(loadLink, 5000);
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
      {{ system.managed ? t('features.platforms.introManaged') : t('features.platforms.intro') }}
    </p>
    <v-alert v-if="adapterLoadFailed" type="error" variant="tonal" class="mb-3">
      {{ t('features.platforms.loadFailed') }}
      <template #append>
        <v-btn size="small" variant="text" @click="loadAdapters">{{ t('core.common.refresh') }}</v-btn>
      </template>
    </v-alert>
    <v-alert v-else-if="!saveSupported" type="warning" variant="tonal" class="mb-3">
      {{ t('features.platforms.backendUpdateRequired') }}
    </v-alert>
    <v-alert v-if="unavailableSelected.length" type="warning" variant="tonal" class="mb-4">
      {{ t('features.platforms.legacyUnavailable', {
        names: unavailableSelected.map((adapter) => adapter.name).join('、'),
      }) }}
    </v-alert>

    <ConversationPolicyEditor />

    <v-card class="pa-4 mb-4" :loading="loadingAdapters">
      <div class="d-flex flex-wrap align-center ga-2 mb-1">
        <div class="text-h6 font-weight-medium">{{ t('features.platforms.addedTitle') }}</div>
        <v-chip size="small" variant="tonal" color="primary">{{ selectedAdapterCards.length }}</v-chip>
        <v-tooltip :text="t('features.platforms.connectionStatusOpen')" location="top">
          <template #activator="{ props }">
            <v-btn
              v-bind="props"
              :icon="healthy === true ? 'mdi-lan-connect' : healthy === false ? 'mdi-lan-disconnect' : 'mdi-lan'"
              :color="linkColor"
              size="small"
              variant="tonal"
              :aria-label="t('features.platforms.connectionStatusOpen')"
              @click="connectionStatusDialog = true"
            />
          </template>
        </v-tooltip>
        <v-spacer />
        <v-chip v-if="processOverride" size="small" color="warning" variant="tonal">
          {{ t('features.platforms.processOverride') }}
        </v-chip>
        <v-btn prepend-icon="mdi-plus" color="primary" @click="catalogDialog = true">
          {{ t('features.platforms.addAdapter') }}
        </v-btn>
      </div>
      <p class="text-body-2 text-medium-emphasis mt-1 mb-4">
        {{ t('features.platforms.addedHint') }}
      </p>

      <v-row v-if="selectedAdapterCards.length">
        <v-col v-for="adapter in selectedAdapterCards" :key="adapter.module" cols="12" md="6" xl="4" class="d-flex">
          <v-card
            variant="outlined"
            class="platform-card platform-card--adapter flex-grow-1"
          >
            <v-card-text class="pb-2">
              <div class="d-flex align-start ga-2">
                <div class="min-width-0 flex-grow-1">
                  <div class="text-subtitle-1 font-weight-medium">
                    {{ moduleToPreset.has(adapter.module)
                      ? t(`features.platforms.cards.${moduleToPreset.get(adapter.module)}`)
                      : adapter.name }}
                  </div>
                  <div class="text-caption text-medium-emphasis">{{ adapter.module }}</div>
                </div>
                <v-btn
                  icon="mdi-close"
                  size="small"
                  variant="text"
                  :aria-label="t('features.platforms.removeAdapter', { name: adapter.name })"
                  @click="removeAdapterCard(adapter.module)"
                />
              </div>
              <div v-if="adapter.description" class="text-caption text-medium-emphasis mt-1">
                {{ adapter.description }}
              </div>
              <v-alert
                v-if="!isAdapterAvailable(adapter)"
                type="warning"
                variant="tonal"
                density="compact"
                class="mt-3"
              >
                <div class="font-weight-medium">{{ t('features.platforms.unavailable') }}</div>
                <div>{{ adapterUnavailableReason(adapter) }}</div>
              </v-alert>
              <div class="d-flex align-center flex-wrap ga-2 mt-3">
                <v-chip
                  v-if="!isAdapterAvailable(adapter)"
                  size="x-small"
                  color="error"
                  variant="tonal"
                >
                  {{ t('features.platforms.unavailable') }}
                </v-chip>
                <v-chip v-if="adapter.package" size="x-small" :color="adapter.official ? 'primary' : 'secondary'" variant="tonal">
                  {{ adapter.official
                    ? t('features.platforms.officialAdapter')
                    : t('features.platforms.communityAdapter') }}
                </v-chip>
                <v-chip
                  v-if="adapter.package && packageStatusSupported"
                  size="x-small"
                  :color="packageVersion(adapter.package) ? 'success' : 'warning'"
                  variant="tonal"
                >
                  {{ packageVersion(adapter.package)
                    ? `${t('features.platforms.installed')} ${packageVersion(adapter.package)}`
                    : t('features.platforms.notInstalled') }}
                </v-chip>
                <v-chip v-else-if="adapter.package" size="x-small" color="secondary" variant="tonal">
                  {{ t('features.platforms.packageStatusUnavailable') }}
                </v-chip>
                <v-chip v-else size="x-small" color="secondary" variant="tonal">
                  {{ t('features.platforms.customModuleTag') }}
                </v-chip>
                <v-btn
                  size="small"
                  color="primary"
                  variant="tonal"
                  prepend-icon="mdi-cog-outline"
                  :disabled="loadingAdapters || !isAdapterAvailable(adapter)"
                  @click="openAdapterConfig(adapter.module)"
                >
                  {{ t('features.platforms.configureAdapter') }}
                </v-btn>
                <v-tooltip v-if="adapter.homepage" :text="t('features.platforms.officialDocsTooltip')" location="top">
                  <template #activator="{ props }">
                    <a
                      v-bind="props"
                      :href="adapter.homepage"
                      target="_blank"
                      rel="noreferrer"
                      class="adapter-docs-link"
                      :aria-label="t('features.platforms.officialDocs')"
                    >
                      <v-icon icon="mdi-open-in-new" size="small" aria-hidden="true" />
                    </a>
                  </template>
                </v-tooltip>
              </div>
            </v-card-text>
          </v-card>
        </v-col>
      </v-row>
      <div v-else class="text-body-2 text-medium-emphasis py-4">
        {{ t('features.platforms.noAdaptersAdded') }}
      </div>

      <v-dialog v-model="catalogDialog" max-width="1100">
        <v-card>
          <v-card-title class="d-flex flex-wrap align-center ga-2">
            <span>{{ t('features.platforms.addDialogTitle') }}</span>
            <v-chip size="small" color="success" variant="tonal">
              {{ t('features.platforms.addableCount', { count: addableCatalogCount }) }}
            </v-chip>
            <v-spacer />
            <v-btn icon="mdi-close" variant="text" :aria-label="t('features.platforms.closePicker')" @click="catalogDialog = false" />
          </v-card-title>
          <v-card-text>
            <p class="text-body-2 text-medium-emphasis mb-3">{{ t('features.platforms.addDialogHint') }}</p>
            <v-row class="mb-3">
              <v-col cols="12">
                <v-text-field
                  v-model="catalogSearch"
                  :label="t('features.platforms.searchAdapters')"
                  prepend-inner-icon="mdi-magnify"
                  clearable
                  hide-details
                />
              </v-col>
            </v-row>
            <v-row>
              <v-col v-for="adapter in filteredCatalog" :key="adapter.module" cols="12" md="6" xl="4" class="d-flex">
                <v-card
                  variant="outlined"
                  class="platform-card platform-card--adapter adapter-picker-card flex-grow-1"
                  :class="{
                    'platform-card--selected': isAdapterSelected(adapter.module),
                  }"
                  @click="toggleCatalogAdapter(adapter)"
                >
                  <v-card-text class="adapter-picker-card__content">
                    <v-checkbox
                      :model-value="isAdapterSelected(adapter.module)"
                      :aria-label="adapterDisplayName(adapter.module)"
                      @click.stop
                      @update:model-value="setAdapterSelected(adapter.module, Boolean($event))"
                      color="primary"
                      density="compact"
                      hide-details
                      class="adapter-picker-card__checkbox"
                    />
                    <div class="adapter-picker-card__heading">
                      <div class="text-subtitle-1 font-weight-medium adapter-picker-card__name">
                        {{ moduleToPreset.has(adapter.module)
                          ? t(`features.platforms.cards.${moduleToPreset.get(adapter.module)}`)
                          : adapter.name }}
                      </div>
                      <div class="text-caption text-medium-emphasis adapter-picker-card__module">{{ adapter.module }}</div>
                    </div>
                    <div v-if="adapter.description" class="text-caption text-medium-emphasis mt-1 adapter-picker-card__description">
                      {{ adapter.description }}
                    </div>
                    <div class="d-flex align-center flex-wrap ga-2 mt-3 adapter-picker-card__meta">
                      <v-chip size="x-small" :color="adapter.official ? 'primary' : 'secondary'" variant="tonal">
                        {{ adapter.official
                          ? t('features.platforms.officialAdapter')
                          : t('features.platforms.communityAdapter') }}
                      </v-chip>
                      <v-chip
                        v-if="packageStatusSupported"
                        size="x-small"
                        :color="packageVersion(adapter.package) ? 'success' : 'warning'"
                        variant="tonal"
                      >
                        {{ packageVersion(adapter.package)
                          ? `${t('features.platforms.installed')} ${packageVersion(adapter.package)}`
                          : t('features.platforms.notInstalled') }}
                      </v-chip>
                      <v-chip v-else size="x-small" color="secondary" variant="tonal">
                        {{ t('features.platforms.packageStatusUnavailable') }}
                      </v-chip>
                      <v-tooltip v-if="adapter.homepage" :text="t('features.platforms.officialDocsTooltip')" location="top">
                        <template #activator="{ props }">
                          <a
                            v-bind="props"
                            :href="adapter.homepage"
                            target="_blank"
                            rel="noreferrer"
                            class="adapter-docs-link"
                            :aria-label="t('features.platforms.officialDocs')"
                            @click.stop
                          >
                            <v-icon icon="mdi-open-in-new" size="small" aria-hidden="true" />
                          </a>
                        </template>
                      </v-tooltip>
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
              <v-col cols="12" md="6" xl="4" class="d-flex">
                <v-card
                  variant="outlined"
                  class="platform-card platform-card--adapter adapter-picker-add-card flex-grow-1"
                  role="button"
                  tabindex="0"
                  :aria-label="t('features.platforms.addCustomModule')"
                  @click="openCustomAdapterDialog"
                  @keydown.enter="openCustomAdapterDialog"
                  @keydown.space.prevent="openCustomAdapterDialog"
                >
                  <v-card-text class="adapter-picker-add-card__content">
                    <v-icon icon="mdi-plus-circle-outline" size="large" color="primary" aria-hidden="true" />
                    <span class="text-body-1 font-weight-medium">{{ t('features.platforms.addCustomModule') }}</span>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
            <div v-if="!filteredCatalog.length" class="text-body-2 text-medium-emphasis py-4">
              {{ t('features.platforms.noAdaptersFound') }}
            </div>
          </v-card-text>
          <v-card-actions>
            <v-spacer />
            <v-btn color="primary" @click="catalogDialog = false">{{ t('features.platforms.finishAdding') }}</v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>

      <v-dialog v-model="customAdapterDialog" max-width="520">
        <v-card>
          <v-card-title class="d-flex align-center">
            <span>{{ t('features.platforms.customModules') }}</span>
            <v-spacer />
            <v-btn
              icon="mdi-close"
              variant="text"
              :aria-label="t('features.platforms.closeConfigDialog')"
              @click="customAdapterDialog = false"
            />
          </v-card-title>
          <v-divider />
          <v-card-text>
            <p class="text-body-2 text-medium-emphasis mb-3">
              {{ t('features.platforms.customModulesHint') }}
            </p>
            <v-text-field
              v-model="customModuleDraft"
              :label="t('features.platforms.customModulePath')"
              :error-messages="customModuleError || undefined"
              prepend-inner-icon="mdi-code-braces"
              autofocus
              hide-details="auto"
              @update:model-value="customModuleError = ''"
              @keyup.enter="addCustomAdapterModule"
            />
          </v-card-text>
          <v-card-actions>
            <v-spacer />
            <v-btn variant="text" @click="customAdapterDialog = false">
              {{ t('core.common.cancel') }}
            </v-btn>
            <v-btn
              color="primary"
              prepend-icon="mdi-plus"
              :disabled="!customModuleDraft.trim()"
              @click="addCustomAdapterModule"
            >
              {{ t('features.platforms.addCustomModule') }}
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>

      <v-dialog v-model="adapterConfigDialog" max-width="900" scrollable>
        <v-card v-if="configuringAdapter">
          <v-card-title class="d-flex align-start ga-3">
            <div class="min-width-0">
              <div class="text-h6">{{ t('features.platforms.configureAdapterTitle', { name: adapterDisplayName(configuringModule) }) }}</div>
              <div class="text-caption text-medium-emphasis text-break">{{ configuringModule }}</div>
            </div>
            <v-spacer />
            <v-btn
              icon="mdi-close"
              variant="text"
              :aria-label="t('features.platforms.closeConfigDialog')"
              @click="adapterConfigDialog = false"
            />
          </v-card-title>
          <v-divider />
          <v-card-text>
            <p class="text-body-2 text-medium-emphasis mb-4">{{ t('features.platforms.adapterConfigHint') }}</p>
            <v-card variant="tonal" class="mb-4 pa-3">
              <div class="d-flex align-center ga-2 mb-1">
                <v-icon icon="mdi-web" size="small" />
                <div class="text-subtitle-1 font-weight-medium">{{ t('features.platforms.driverTitle') }}</div>
              </div>
              <div class="text-caption text-medium-emphasis mb-3">{{ t('features.platforms.driverSharedHint') }}</div>
              <v-text-field
                v-model="driver"
                label="DRIVER"
                :hint="t('features.platforms.driverHint')"
                persistent-hint
                placeholder="~fastapi+~httpx+~websockets"
              />
              <v-btn size="small" variant="text" class="mt-1" @click="useRecommendedDriver">
                {{ t('features.platforms.useRecommendedDriver') }}
              </v-btn>
              <v-alert v-if="driverProcessOverride" type="warning" variant="tonal" density="compact" class="mt-2">
                {{ t('features.platforms.driverOverride') }}
              </v-alert>
              <v-alert v-if="configuringRemotePlatform" type="info" variant="tonal" density="compact" class="mt-3">
                {{ t('features.platforms.remoteDriverHint') }}
              </v-alert>
            </v-card>
            <v-alert
              v-if="dialogProcessOverrideKeys.length"
              type="warning"
              variant="tonal"
              density="compact"
              class="mb-4"
            >
              {{ t('features.platforms.adapterEnvProcessOverride', { keys: dialogProcessOverrideKeys.join(', ') }) }}
            </v-alert>

            <template v-if="configuringPreset === 'onebot'">
              <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('features.platforms.onebotConfig') }}</div>
              <div class="text-caption text-medium-emphasis mb-3">{{ t('features.platforms.onebotGuide') }}</div>
              <v-select
                v-model="onebot.mode"
                :label="t('features.platforms.connectionMode')"
                :items="[
                  { title: t('features.platforms.reverseMode'), value: 'reverse' },
                  { title: t('features.platforms.forwardMode'), value: 'forward' },
                ]"
                item-title="title"
                item-value="value"
              />
              <template v-if="onebot.mode === 'reverse'">
                <v-text-field v-model="onebot.host" :label="t('features.platforms.host')" />
                <v-text-field v-model="onebot.port" :label="t('features.platforms.port')" type="number" />
              </template>
              <v-textarea
                v-else
                v-model="onebot.wsUrlsText"
                :label="t('features.platforms.wsUrls')"
                :hint="t('features.platforms.wsUrlsHint')"
                persistent-hint
                rows="2"
                auto-grow
              />
              <v-text-field
                v-model="onebot.accessToken"
                :label="t('features.platforms.accessToken')"
                type="password"
                :placeholder="onebot.hasToken ? t('features.platforms.secretSaved') : ''"
                :hint="t('features.platforms.secretHint')"
                persistent-hint
              />
            </template>

            <template v-else-if="configuringPreset === 'qq'">
              <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('features.platforms.cards.qq') }}</div>
              <v-text-field v-model="qq.appId" label="App ID" autocomplete="off" />
              <v-text-field
                v-model="qq.appSecret"
                label="App Secret"
                type="password"
                autocomplete="new-password"
                :placeholder="qq.hasSecret ? t('features.platforms.secretSaved') : ''"
              />
              <v-switch
                v-model="qq.useWebsocket"
                :label="t('features.platforms.qqWebsocket')"
                color="primary"
                hide-details
              />
              <div class="text-caption text-medium-emphasis mt-3 mb-1">{{ t('features.platforms.qqIntents') }}</div>
              <v-checkbox
                v-for="name in ['guild_messages', 'direct_message', 'c2c_group_at_messages', 'at_messages']"
                :key="name"
                v-model="qq.intent[name]"
                :label="t('features.platforms.intent.' + name)"
                density="compact"
                hide-details
              />
            </template>

            <template v-else-if="configuringPreset === 'telegram'">
              <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('features.platforms.cards.telegram') }}</div>
              <v-text-field
                v-model="telegram.token"
                :label="t('features.platforms.botToken')"
                type="password"
                autocomplete="new-password"
                :placeholder="telegram.hasToken ? t('features.platforms.secretSaved') : ''"
              />
              <v-btn-toggle v-model="telegram.isWebhook" mandatory color="primary" density="comfortable" class="mb-3">
                <v-btn :value="false">{{ t('features.platforms.longPolling') }}</v-btn>
                <v-btn :value="true">Webhook</v-btn>
              </v-btn-toggle>
              <v-text-field v-model="telegram.apiServer" :label="t('features.platforms.telegramApiServer')" />
              <v-text-field
                v-if="telegram.isWebhook"
                v-model="telegram.webhookUrl"
                :label="t('features.platforms.webhookUrl')"
                placeholder="https://example.com/telegram"
              />
              <v-alert v-if="telegram.isWebhook" type="warning" density="compact" variant="tonal" class="mb-3">
                {{ t('features.platforms.webhookHint') }}
              </v-alert>
              <v-text-field
                v-model="telegram.proxy"
                :label="t('features.platforms.proxy')"
                type="password"
                autocomplete="new-password"
                :placeholder="telegram.hasProxy ? t('features.platforms.secretSaved') : ''"
              />
            </template>

            <template v-else-if="configuringPreset === 'discord'">
              <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('features.platforms.cards.discord') }}</div>
              <v-text-field
                v-model="discord.token"
                :label="t('features.platforms.botToken')"
                type="password"
                autocomplete="new-password"
                :placeholder="discord.hasToken ? t('features.platforms.secretSaved') : ''"
              />
              <div class="text-caption text-medium-emphasis mt-2 mb-1">{{ t('features.platforms.discordIntents') }}</div>
              <v-checkbox
                v-for="name in discordIntentNames"
                :key="name"
                v-model="discord.intent[name]"
                :label="t('features.platforms.intent.' + name)"
                density="compact"
                hide-details
              />
              <v-alert type="info" density="compact" variant="tonal" class="my-2">
                {{ t('features.platforms.discordMessageContentHint') }}
              </v-alert>
              <v-switch
                v-model="discord.registerAllCommands"
                :label="t('features.platforms.registerAllCommands')"
                color="primary"
                hide-details
                class="mb-2"
              />
              <v-text-field
                v-model="discord.proxy"
                :label="t('features.platforms.proxy')"
                type="password"
                autocomplete="new-password"
                :placeholder="discord.hasProxy ? t('features.platforms.secretSaved') : ''"
              />
            </template>

            <v-alert v-if="!configuringSchema" type="info" variant="tonal" density="compact" class="mb-4">
              {{ t('features.platforms.genericAdapterConfigHint') }}
            </v-alert>

            <template v-if="configuringSchema">
              <v-alert type="info" variant="tonal" density="compact" class="mb-3">
                {{ configuringSchema.description }}
                <v-tooltip
                  v-if="configuringAdapter?.homepage"
                  :text="t('features.platforms.officialDocsTooltip')"
                  location="top"
                >
                  <template #activator="{ props }">
                    <a
                      v-bind="props"
                      :href="configuringAdapter.homepage"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="adapter-docs-link ml-1"
                      :aria-label="t('features.platforms.officialDocs')"
                    >
                      <v-icon icon="mdi-open-in-new" size="small" aria-hidden="true" />
                    </a>
                  </template>
                </v-tooltip>
              </v-alert>
              <v-alert v-if="configuringSchema.info" type="warning" variant="tonal" density="compact" class="mb-3">
                {{ configuringSchema.info }}
              </v-alert>

              <v-card
                v-for="section in configuringSchema.sections"
                :key="section.envKey ?? section.title"
                variant="tonal"
                class="mb-3 pa-3"
              >
                <div class="d-flex flex-wrap align-center ga-2 mb-1">
                  <div class="text-subtitle-1 font-weight-medium">{{ section.title }}</div>
                  <v-chip v-if="section.envKey" size="x-small" variant="outlined">{{ section.envKey }}</v-chip>
                  <v-spacer />
                  <v-btn
                    v-if="section.kind === 'bot-list'"
                    size="small"
                    prepend-icon="mdi-plus"
                    variant="tonal"
                    @click="addPresetBot(section)"
                  >
                    {{ t('features.platforms.addPresetBot') }}
                  </v-btn>
                </div>
                <div v-if="section.description" class="text-caption text-medium-emphasis mb-3">
                  {{ section.description }}
                </div>

                <template v-if="section.kind === 'bot-list'">
                  <v-card
                    v-for="(bot, botIndex) in parsePresetBotList(section)"
                    :key="`${section.envKey}-${botIndex}`"
                    variant="outlined"
                    class="mb-3 pa-3"
                  >
                    <div class="d-flex align-center mb-2">
                      <div class="text-body-2 font-weight-medium">
                        {{ t('features.platforms.presetBotNumber', { number: botIndex + 1 }) }}
                      </div>
                      <v-spacer />
                      <v-btn
                        icon="mdi-delete-outline"
                        size="small"
                        variant="text"
                        :aria-label="t('features.platforms.removePresetBot')"
                        @click="removePresetBot(section, botIndex)"
                      />
                    </div>
                    <v-row dense>
                      <v-col
                        v-for="field in section.fields"
                        :key="field.path"
                        cols="12"
                        md="6"
                      >
                        <v-switch
                          v-if="field.type === 'boolean'"
                          :model-value="presetBotFieldValue(section, botIndex, field)"
                          :label="field.label"
                          color="primary"
                          hide-details
                          @update:model-value="setPresetBotFieldValue(section, botIndex, field, $event)"
                        />
                        <v-select
                          v-else-if="field.type === 'select'"
                          :model-value="presetBotFieldValue(section, botIndex, field)"
                          :items="field.options ?? []"
                          item-title="label"
                          item-value="value"
                          :label="field.required ? `${field.label} *` : field.label"
                          @update:model-value="setPresetBotFieldValue(section, botIndex, field, $event)"
                        />
                        <v-textarea
                          v-else-if="isPresetTextArea(field.type)"
                          :model-value="presetBotFieldValue(section, botIndex, field)"
                          :label="field.required ? `${field.label} *` : field.label"
                          :hint="field.hint || (field.type === 'string-list' ? t('features.platforms.presetListHint') : '')"
                          :persistent-hint="Boolean(field.hint) || field.type === 'string-list'"
                          :placeholder="isPresetSecret(field) && presetSecretSaved(section.envKey ?? '', field.path, botIndex)
                            ? t('features.platforms.secretSaved')
                            : field.placeholder || (field.type === 'json' ? '{\n  }' : '')"
                          :rows="field.type === 'json' ? 4 : 2"
                          auto-grow
                          @update:model-value="setPresetBotFieldValue(section, botIndex, field, $event)"
                        />
                        <v-text-field
                          v-else
                          :model-value="presetBotFieldValue(section, botIndex, field)"
                          :label="field.required ? `${field.label} *` : field.label"
                          :type="presetInputType(field.type)"
                          :placeholder="isPresetSecret(field)
                            && presetSecretSaved(section.envKey ?? '', field.path, botIndex)
                            ? t('features.platforms.secretSaved')
                            : field.placeholder || ''"
                          :hint="field.hint"
                          :persistent-hint="Boolean(field.hint)"
                          autocomplete="new-password"
                          @update:model-value="setPresetBotFieldValue(section, botIndex, field, $event)"
                        />
                      </v-col>
                    </v-row>
                  </v-card>
                  <div v-if="!parsePresetBotList(section).length" class="text-body-2 text-medium-emphasis py-2">
                    {{ t('features.platforms.presetBotEmpty') }}
                  </div>
                </template>

                <v-row v-else dense>
                  <v-col v-for="field in section.fields" :key="field.envKey" cols="12" md="6">
                    <v-switch
                      v-if="field.type === 'boolean'"
                      :model-value="presetFieldValue(field)"
                      :label="field.label"
                      color="primary"
                      hide-details
                      @update:model-value="setPresetFieldValue(field, $event)"
                    />
                    <v-select
                      v-else-if="field.type === 'select'"
                      :model-value="presetFieldValue(field)"
                      :items="field.options ?? []"
                      item-title="label"
                      item-value="value"
                      :label="field.label"
                      @update:model-value="setPresetFieldValue(field, $event)"
                    />
                    <v-textarea
                      v-else-if="isPresetTextArea(field.type)"
                      :model-value="presetFieldValue(field)"
                      :label="field.label"
                      :hint="field.hint || (field.type === 'string-list' ? t('features.platforms.presetListHint') : '')"
                      :persistent-hint="Boolean(field.hint) || field.type === 'string-list'"
                      :placeholder="field.placeholder || (field.type === 'json' ? '{\n  }' : '')"
                      :rows="field.type === 'json' ? 4 : 2"
                      auto-grow
                      @update:model-value="setPresetFieldValue(field, $event)"
                    />
                    <v-text-field
                      v-else
                      :model-value="presetFieldValue(field)"
                      :label="field.label"
                      :type="presetInputType(field.type)"
                      :placeholder="isPresetSecret(field) && presetSecretSaved(field.envKey ?? '')
                        ? t('features.platforms.secretSaved')
                        : field.placeholder || ''"
                      :hint="field.hint"
                      :persistent-hint="Boolean(field.hint)"
                      autocomplete="new-password"
                      @update:model-value="setPresetFieldValue(field, $event)"
                    />
                  </v-col>
                </v-row>
              </v-card>

              <v-expansion-panels variant="accordion" class="mt-4">
                <v-expansion-panel>
                  <v-expansion-panel-title>
                    {{ t('features.platforms.advancedAdapterEnvTitle', { count: advancedAdapterEnv.length }) }}
                  </v-expansion-panel-title>
                  <v-expansion-panel-text>
                    <div class="d-flex align-center mb-3">
                      <div class="text-caption text-medium-emphasis">{{ t('features.platforms.adapterEnvHint') }}</div>
                      <v-spacer />
                      <v-btn size="small" prepend-icon="mdi-plus" variant="tonal" @click="addAdapterEnvEntry">
                        {{ t('features.platforms.adapterEnvAdd') }}
                      </v-btn>
                    </div>
                    <template v-if="advancedAdapterEnv.length">
                      <v-row v-for="item in advancedAdapterEnv" :key="item.index" dense>
                        <v-col cols="12" md="4">
                          <v-text-field v-model="item.entry.key" :label="t('features.platforms.adapterEnvKey')" autocomplete="off" hide-details />
                        </v-col>
                        <v-col cols="12" md="7">
                          <v-textarea
                            v-model="item.entry.value"
                            :label="t('features.platforms.adapterEnvValue')"
                            :type="item.entry.sensitive || isSensitiveAdapterEnv(item.entry.key) ? 'password' : 'text'"
                            :placeholder="item.entry.has_value && (item.entry.sensitive || isSensitiveAdapterEnv(item.entry.key)) ? t('features.platforms.secretSaved') : ''"
                            autocomplete="new-password"
                            rows="1"
                            auto-grow
                            hide-details
                          />
                        </v-col>
                        <v-col cols="12" md="1" class="d-flex justify-end">
                          <v-btn icon="mdi-delete-outline" size="small" variant="text" :aria-label="t('features.platforms.adapterEnvRemove')" @click="removeAdapterEnvEntry(item.index)" />
                        </v-col>
                      </v-row>
                    </template>
                    <div v-else class="text-body-2 text-medium-emphasis py-2">
                      {{ t('features.platforms.adapterEnvEmpty') }}
                    </div>
                  </v-expansion-panel-text>
                </v-expansion-panel>
              </v-expansion-panels>
            </template>

            <template v-else>
              <v-divider class="my-4" />
              <div class="d-flex flex-wrap align-center ga-2 mb-1">
                <div class="text-subtitle-1 font-weight-medium">{{ t('features.platforms.adapterEnvTitle') }}</div>
                <v-spacer />
                <v-btn size="small" prepend-icon="mdi-plus" variant="tonal" @click="addAdapterEnvEntry">
                  {{ t('features.platforms.adapterEnvAdd') }}
                </v-btn>
              </div>
              <div class="text-caption text-medium-emphasis mb-3">{{ t('features.platforms.adapterEnvHint') }}</div>
              <template v-if="currentAdapterEnv.length">
                <v-row v-for="item in currentAdapterEnv" :key="item.index" dense>
                  <v-col cols="12" md="4">
                    <v-text-field v-model="item.entry.key" :label="t('features.platforms.adapterEnvKey')" autocomplete="off" hide-details />
                  </v-col>
                  <v-col cols="12" md="7">
                    <v-textarea
                      v-model="item.entry.value"
                      :label="t('features.platforms.adapterEnvValue')"
                      :type="item.entry.sensitive || isSensitiveAdapterEnv(item.entry.key) ? 'password' : 'text'"
                      :placeholder="item.entry.has_value && (item.entry.sensitive || isSensitiveAdapterEnv(item.entry.key)) ? t('features.platforms.secretSaved') : ''"
                      autocomplete="new-password"
                      rows="1"
                      auto-grow
                      hide-details
                    />
                  </v-col>
                  <v-col cols="12" md="1" class="d-flex justify-end">
                    <v-btn icon="mdi-delete-outline" size="small" variant="text" :aria-label="t('features.platforms.adapterEnvRemove')" @click="removeAdapterEnvEntry(item.index)" />
                  </v-col>
                </v-row>
              </template>
              <div v-else class="text-body-2 text-medium-emphasis py-2">
                {{ t('features.platforms.adapterEnvEmpty') }}
              </div>
            </template>

            <v-expansion-panels v-if="unassignedAdapterEnv.length" variant="accordion" class="mt-4">
              <v-expansion-panel>
                <v-expansion-panel-title>
                  {{ t('features.platforms.adapterEnvUnassignedTitle', { count: unassignedAdapterEnv.length }) }}
                </v-expansion-panel-title>
                <v-expansion-panel-text>
                  <v-alert type="info" density="compact" variant="tonal" class="mb-3">
                    {{ t('features.platforms.adapterEnvUnassignedHint') }}
                  </v-alert>
                  <v-row v-for="item in unassignedAdapterEnv" :key="item.index" dense>
                    <v-col cols="12" md="3">
                      <v-text-field
                        v-model="item.entry.key"
                        :label="t('features.platforms.adapterEnvKey')"
                        autocomplete="off"
                        hide-details
                      />
                    </v-col>
                    <v-col cols="12" md="5">
                      <v-text-field
                        v-model="item.entry.value"
                        :label="t('features.platforms.adapterEnvValue')"
                        :type="item.entry.sensitive || isSensitiveAdapterEnv(item.entry.key) ? 'password' : 'text'"
                        :placeholder="item.entry.has_value && (item.entry.sensitive || isSensitiveAdapterEnv(item.entry.key))
                          ? t('features.platforms.secretSaved')
                          : ''"
                        autocomplete="new-password"
                        hide-details
                      />
                    </v-col>
                    <v-col cols="12" md="3">
                      <v-select
                        v-model="item.entry.module"
                        :items="adapterEnvModuleItems"
                        item-title="title"
                        item-value="value"
                        :label="t('features.platforms.adapterEnvModule')"
                        hide-details
                      />
                    </v-col>
                    <v-col cols="12" md="1" class="d-flex justify-end">
                      <v-btn
                        icon="mdi-delete-outline"
                        size="small"
                        variant="text"
                        :aria-label="t('features.platforms.adapterEnvRemove')"
                        @click="removeAdapterEnvEntry(item.index)"
                      />
                    </v-col>
                  </v-row>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </v-card-text>
          <v-card-actions>
            <v-spacer />
            <v-btn variant="text" @click="adapterConfigDialog = false">{{ t('features.platforms.dialogDone') }}</v-btn>
          </v-card-actions>
        </v-card>
      </v-dialog>

      <v-alert v-if="hasUnsavedChanges" type="warning" variant="tonal" density="compact" class="mt-3">
        {{ t('features.platforms.restartHint') }}
      </v-alert>
      <div class="d-flex justify-end mt-3">
        <v-btn
          color="primary"
          prepend-icon="mdi-content-save"
          :loading="saving"
          :disabled="loadingAdapters || adapterLoadFailed || !saveSupported || system.operationPending"
          @click="saveAdapters"
        >
          {{ t('features.platforms.saveAdapters') }}
        </v-btn>
      </div>
    </v-card>

    <v-dialog v-model="connectionStatusDialog" max-width="900" scrollable>
      <v-card>
        <v-card-title class="d-flex align-center ga-3">
          <v-icon
            :icon="healthy === true ? 'mdi-lan-connect' : healthy === false ? 'mdi-lan-disconnect' : 'mdi-lan'"
            :color="linkColor"
          />
          <div class="text-h6">{{ t('features.platforms.connectionsTitle') }}</div>
          <v-chip :color="linkColor" size="small" variant="tonal">
            {{ healthy === null
              ? (link?.unavailable ? t('features.platforms.healthUnknown') : t('features.platforms.notApplicable'))
              : healthLabel(healthy) }}
          </v-chip>
          <v-spacer />
          <v-btn
            icon="mdi-close"
            variant="text"
            :aria-label="t('features.platforms.connectionStatusClose')"
            @click="connectionStatusDialog = false"
          />
        </v-card-title>
        <v-divider />
        <v-card-text>
          <p class="text-body-2 text-medium-emphasis mb-4">{{ t('features.platforms.connectionStatusHint') }}</p>
          <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-3">
            {{ error }}
            <template #append>
              <v-btn size="small" variant="text" @click="loadLink">{{ t('core.common.refresh') }}</v-btn>
            </template>
          </v-alert>
          <v-alert v-if="!link && !error" type="info" variant="tonal" density="compact" class="mb-3">
            {{ t('features.platforms.connectionStatusLoading') }}
          </v-alert>
          <v-alert v-if="link && link.applicable === false" type="info" variant="tonal" density="compact" class="mb-3">
            {{ t('features.platforms.noOnebotNeeded') }}
          </v-alert>
          <v-alert v-else-if="link && healthy === false" type="warning" variant="tonal" density="compact" class="mb-3">
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
                <td>{{ connection.instance_ref }}</td>
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
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="connectionStatusDialog = false">{{ t('features.platforms.connectionStatusClose') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<style scoped>
.platform-card {
  transition: border-color 120ms ease, background-color 120ms ease;
}

.platform-card--selected {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.035);
}

.platform-card--adapter {
  min-height: 156px;
}

.platform-card--unavailable {
  border-style: dashed;
  cursor: not-allowed;
}

.adapter-picker-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.adapter-picker-card__content {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
}

.adapter-picker-card__checkbox {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  margin: 0;
}

.adapter-picker-card__heading {
  min-width: 0;
  padding-right: 38px;
}

.adapter-picker-card__name {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.35;
}

.adapter-picker-card__module {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.adapter-picker-card__description {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.35;
}

.adapter-picker-add-card {
  display: flex;
  flex-direction: column;
  border-style: dashed;
  cursor: pointer;
  transition: border-color 120ms ease, background-color 120ms ease;
}

.adapter-picker-add-card:hover {
  border-color: rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.035);
}

.adapter-picker-add-card__content {
  display: flex;
  flex: 1;
  align-self: stretch;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  text-align: center;
}

.adapter-picker-card__meta {
  margin-top: auto !important;
}

.adapter-docs-link {
  display: inline-flex;
  min-width: 32px;
  min-height: 32px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: rgb(var(--v-theme-primary));
}

.adapter-docs-link:hover {
  background: rgba(var(--v-theme-primary), 0.08);
}

.adapter-docs-link:focus-visible,
.adapter-picker-add-card:focus-visible {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
}

.min-width-0 {
  min-width: 0;
}
</style>
