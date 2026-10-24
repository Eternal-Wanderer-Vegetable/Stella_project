<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import { api, unwrap } from '@/api/http';
import { formatSeconds, type GravitasStatus } from '@/api/gravitas';

interface StatusPayload {
  gravitas?: GravitasStatus | null;
}

const { t } = useI18n();
const status = ref<GravitasStatus | null>(null);
const loading = ref(false);
const loadError = ref('');

const assessment = computed(() => status.value?.assessment);
const facts = computed(() => assessment.value?.facts ?? []);
const unassessed = computed(() => assessment.value?.unassessed ?? []);
const criteria = computed(() => Object.entries(assessment.value?.criteria ?? {}));

async function refresh(): Promise<void> {
  loading.value = true;
  loadError.value = '';
  try {
    const payload = await unwrap<StatusPayload>(api.get('/gravitas/status'));
    status.value = payload.gravitas ?? null;
  } catch (error) {
    loadError.value = (error as Error).message;
  } finally {
    loading.value = false;
  }
}

function scopeLabel(scope: { kind: string; id: string }): string {
  return `${scope.kind} / ${scope.id}`;
}

function modeColor(mode: string): string {
  if (mode === 'shadow') return 'info';
  if (mode === 'enforce') return 'warning';
  return 'secondary';
}

function criterionValue(key: string, value: number | string | string[]): string {
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'number' && key.endsWith('_seconds')) return formatSeconds(value);
  return String(value);
}

onMounted(refresh);
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-1">
      <h1 class="text-h5 font-weight-bold">{{ $t('features.gravitas.title') }}</h1>
      <v-spacer />
      <v-btn
        prepend-icon="mdi-refresh"
        variant="tonal"
        :loading="loading"
        @click="refresh"
      >
        {{ $t('features.gravitas.refresh') }}
      </v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis">{{ $t('features.gravitas.subtitle') }}</p>

    <v-alert v-if="loadError" type="error" variant="tonal" class="mt-4">
      {{ loadError }}
    </v-alert>
    <v-alert v-else-if="!status && !loading" type="info" variant="tonal" class="mt-4">
      {{ $t('features.gravitas.unavailable') }}
    </v-alert>

    <template v-if="status">
      <v-row class="mt-2">
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 h-100">
            <div class="text-caption text-medium-emphasis">{{ $t('features.gravitas.mode') }}</div>
            <v-chip class="mt-2" :color="modeColor(status.mode)" size="small">{{ status.mode }}</v-chip>
            <div class="text-caption mt-2">
              {{ $t('features.gravitas.configuredMode') }}: {{ status.configured_mode }}
            </div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 h-100">
            <div class="text-caption text-medium-emphasis">{{ $t('features.gravitas.snapshot') }}</div>
            <v-chip class="mt-2" :color="status.snapshot_valid ? 'success' : 'error'" size="small">
              {{ status.snapshot_valid ? $t('features.gravitas.valid') : $t('features.gravitas.expired') }}
            </v-chip>
            <div class="text-caption mt-2">
              {{ $t('features.gravitas.age') }}: {{ formatSeconds(status.snapshot_age_seconds) }}
            </div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 h-100">
            <div class="text-caption text-medium-emphasis">{{ $t('features.gravitas.assessment') }}</div>
            <v-chip class="mt-2" color="info" size="small">
              {{ assessment?.state === 'complete' ? $t('features.gravitas.complete') : $t('features.gravitas.partial') }}
            </v-chip>
            <div class="text-caption mt-2">
              {{ $t('features.gravitas.facts') }}: {{ facts.length }}
              · {{ $t('features.gravitas.unassessed') }}: {{ assessment?.unassessed_count ?? 0 }}
            </div>
          </v-card>
        </v-col>
        <v-col cols="12" sm="6" md="3">
          <v-card class="pa-4 h-100">
            <div class="text-caption text-medium-emphasis">{{ $t('features.gravitas.reason') }}</div>
            <div class="text-body-1 mt-2">{{ status.reason_code }}</div>
            <div class="text-caption mt-2">
              {{ $t('features.gravitas.redactedCount') }}: {{ assessment?.redacted_fact_count ?? 0 }}
            </div>
          </v-card>
        </v-col>
      </v-row>

      <v-card class="mt-4 pa-4">
        <div class="text-subtitle-1 font-weight-medium mb-3">{{ $t('features.gravitas.facts') }}</div>
        <v-alert v-if="!facts.length" type="info" variant="tonal">{{ $t('features.gravitas.noFacts') }}</v-alert>
        <v-table v-else density="comfortable">
          <thead>
            <tr>
              <th>{{ $t('features.gravitas.scope') }}</th>
              <th>{{ $t('features.gravitas.dimension') }}</th>
              <th>{{ $t('features.gravitas.value') }}</th>
              <th>{{ $t('features.gravitas.factAge') }}</th>
              <th>{{ $t('features.gravitas.validFor') }}</th>
              <th>{{ $t('features.gravitas.reasonCode') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fact in facts" :key="`${fact.scope.kind}:${fact.scope.id}:${fact.dimension}`">
              <td>{{ scopeLabel(fact.scope) }}</td>
              <td>{{ fact.dimension }}</td>
              <td>
                <v-chip size="x-small" :color="fact.fresh ? 'success' : 'warning'" variant="tonal">
                  {{ fact.value }}{{ fact.fresh ? '' : ` · ${$t('features.gravitas.stale')}` }}
                </v-chip>
              </td>
              <td>{{ formatSeconds(fact.age_seconds) }}</td>
              <td>{{ formatSeconds(fact.valid_for_seconds) }}</td>
              <td>{{ fact.reason_code }}</td>
            </tr>
          </tbody>
        </v-table>
      </v-card>

      <v-row class="mt-1">
        <v-col cols="12" md="6">
          <v-card class="pa-4 h-100">
            <div class="text-subtitle-1 font-weight-medium mb-3">{{ $t('features.gravitas.unassessed') }}</div>
            <v-alert v-if="!unassessed.length" type="success" variant="tonal">
              {{ $t('features.gravitas.noUnassessed') }}
            </v-alert>
            <v-list v-else density="compact">
              <v-list-item v-for="item in unassessed" :key="`${item.scope.kind}:${item.scope.id}`">
                <v-list-item-title>{{ scopeLabel(item.scope) }}</v-list-item-title>
                <v-list-item-subtitle>{{ item.dimensions.join(', ') }}</v-list-item-subtitle>
              </v-list-item>
            </v-list>
          </v-card>
        </v-col>
        <v-col cols="12" md="6">
          <v-card class="pa-4 h-100">
            <div class="text-subtitle-1 font-weight-medium mb-3">{{ $t('features.gravitas.appliedAck') }}</div>
            <div class="text-body-2">
              {{ $t('features.gravitas.ackState') }}:
              <strong>{{ assessment?.applied_ack.state ?? $t('features.gravitas.ackNotReceived') }}</strong>
            </div>
            <div class="text-caption text-medium-emphasis mt-1">
              {{ assessment?.applied_ack.reason_code }}
            </div>
            <p v-if="!assessment?.applied_ack.items?.length" class="text-body-2 mt-3 mb-0">
              {{ $t('features.gravitas.noAckItems') }}
            </p>
          </v-card>
        </v-col>
      </v-row>

      <v-row class="mt-1">
        <v-col cols="12" md="6">
          <v-card class="pa-4 h-100">
            <div class="text-subtitle-1 font-weight-medium mb-3">{{ $t('features.gravitas.criteria') }}</div>
            <v-table density="compact">
              <tbody>
                <tr v-for="[key, value] in criteria" :key="key">
                  <th class="text-left">{{ key }}</th>
                  <td>{{ criterionValue(key, value) }}</td>
                </tr>
              </tbody>
            </v-table>
          </v-card>
        </v-col>
        <v-col cols="12" md="6">
          <v-card class="pa-4 h-100">
            <div class="text-subtitle-1 font-weight-medium mb-3">{{ $t('features.gravitas.version') }}</div>
            <dl class="diagnostic-version">
              <dt>{{ $t('features.gravitas.schemaVersion') }}</dt>
              <dd>{{ assessment?.version.diagnostics_schema_version ?? status.schema_version }}</dd>
              <dt>{{ $t('features.gravitas.configVersion') }}</dt>
              <dd>{{ assessment?.version.config_schema_version ?? '—' }}</dd>
              <dt>{{ $t('features.gravitas.policyRevision') }}</dt>
              <dd>{{ assessment?.version.policy_revision ?? status.policy_revision }}</dd>
              <dt>{{ $t('features.gravitas.configDigest') }}</dt>
              <dd class="text-break">{{ assessment?.version.config_digest ?? '—' }}</dd>
            </dl>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </v-container>
</template>

<style scoped>
.diagnostic-version {
  display: grid;
  grid-template-columns: minmax(9rem, 0.4fr) 1fr;
  gap: 0.5rem 1rem;
  margin: 0;
}

.diagnostic-version dt {
  color: rgba(var(--v-theme-on-surface), 0.64);
}

.diagnostic-version dd {
  margin: 0;
  font-family: monospace;
}
</style>
