<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';

import { useSystemStore } from '@/stores/system';

const system = useSystemStore();
const { t } = useI18n();

const color = computed(() =>
  system.controlAvailable
  && system.coreReady
  && system.revisionsMatch
  && !system.operationPending
  && !system.status?.external_conflict
    ? 'success'
    : system.controlAvailable ? 'warning' : 'error',
);

function shortRevision(value?: string): string {
  return value ? value.slice(0, 8) : '—';
}

function phaseLabel(phase?: string): string {
  if (!phase) return t('features.system.unknown');
  const labels: Record<string, string> = {
    accepted: t('features.system.phases.accepted'),
    validating: t('features.system.phases.validating'),
    prepared: t('features.system.phases.prepared'),
    draining: t('features.system.phases.draining'),
    stopping: t('features.system.phases.stopping'),
    starting: t('features.system.phases.starting'),
    verifying: t('features.system.phases.verifying'),
    restoring_config: t('features.system.phases.restoringConfig'),
    starting_previous: t('features.system.phases.startingPrevious'),
    awaiting_controller_restart: t('features.system.phases.awaitingControllerRestart'),
    succeeded: t('features.system.phases.succeeded'),
    rolled_back: t('features.system.phases.rolledBack'),
    failed: t('features.system.phases.failed'),
  };
  return labels[phase] ?? phase;
}

const visible = computed(() => system.managed || !system.controlAvailable);
</script>

<template>
  <v-alert v-if="visible" :type="color" variant="tonal" density="compact" class="mx-4 mt-4">
    <div class="d-flex flex-wrap ga-2 align-center">
      <span>
        <strong>{{ t('features.system.control') }}:</strong>
        {{ system.controlAvailable ? t('features.system.connected') : t('features.system.reconnecting') }}
      </span>
      <span v-if="system.managed && system.status">
        <strong>{{ t('features.system.saved') }}:</strong>
        {{ shortRevision(system.status.desired_revision) }}
      </span>
      <span v-if="system.managed && system.status">
        <strong>{{ t('features.system.applied') }}:</strong>
        {{ system.revisionsMatch ? t('features.system.yes') : shortRevision(system.status.applied_revision) }}
      </span>
      <span v-if="system.managed && system.status?.core">
        <strong>{{ t('features.system.core') }}:</strong>
        {{ phaseLabel(system.status.core.phase) }}
      </span>
      <span v-if="system.managed && system.operation">
        <strong>{{ t('features.system.operation') }}:</strong>
        {{ phaseLabel(system.operation.phase) }}
      </span>
    </div>
    <div v-if="system.managed && system.controlAvailable && system.coreUnavailable" class="mt-1">
      {{ t('features.system.coreUnavailable') }}
      <span v-if="system.status?.core?.error">{{ t('features.system.error') }}: {{ system.status.core.error }}</span>
    </div>
    <div v-if="system.managed && system.status?.external_conflict" class="mt-1">
      {{ t('features.system.externalConflict') }}
    </div>
    <div v-if="system.operation?.error_code" class="mt-1">
      {{ t('features.system.error') }}: {{ system.operation.error_code }}
    </div>
    <div v-if="system.operation?.phase === 'rolled_back' && system.operation.recovery_attempted" class="mt-1">
      {{ t('features.system.restored') }}
    </div>
    <div v-if="system.operation?.phase === 'failed' && system.operation.recovery_attempted" class="mt-1">
      {{ t('features.system.recoveryFailed') }}
    </div>
    <div v-if="system.operation?.restart_scope === 'controller'" class="mt-1">
      {{ t('features.system.controllerRestart') }}
    </div>
    <div v-if="!system.controlAvailable && system.statusError" class="mt-1">
      {{ t('features.system.reconnectingDetail') }}
    </div>
  </v-alert>
</template>
