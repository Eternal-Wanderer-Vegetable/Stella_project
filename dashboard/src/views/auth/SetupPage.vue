<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';

import { useAuthStore } from '@/stores/auth';
import { toastApiError, useToast } from '@/stores/toast';

const { t } = useI18n();
const router = useRouter();
const auth = useAuthStore();
const toast = useToast();

const username = ref('');
const password = ref('');
const confirm = ref('');
const busy = ref(false);

const mismatch = computed(
  () => confirm.value.length > 0 && confirm.value !== password.value,
);

async function submit(): Promise<void> {
  if (!username.value || !password.value || mismatch.value || busy.value) return;
  busy.value = true;
  try {
    await auth.setup(username.value, password.value);
    toast.success(t('features.auth.submitSetup'));
    router.push({ name: 'welcome' });
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <v-row justify="center" align="center" class="fill-height">
    <v-col cols="12" sm="8" md="5" lg="4">
      <v-card elevation="8" class="pa-2">
        <v-card-item>
          <div class="d-flex align-center mb-2">
            <v-icon icon="mdi-star-four-points" color="secondary" class="mr-2" />
            <v-card-title class="text-h5">{{ $t('features.auth.setupTitle') }}</v-card-title>
          </div>
          <v-card-subtitle>{{ $t('features.auth.setupHint') }}</v-card-subtitle>
        </v-card-item>
        <v-card-text>
          <v-form @submit.prevent="submit">
            <v-text-field
              v-model="username"
              :label="$t('features.auth.username')"
              prepend-inner-icon="mdi-account-outline"
              autocomplete="username"
            />
            <v-text-field
              v-model="password"
              :label="$t('features.auth.password')"
              prepend-inner-icon="mdi-lock-outline"
              type="password"
              autocomplete="new-password"
            />
            <v-text-field
              v-model="confirm"
              :label="$t('features.auth.confirmPassword')"
              prepend-inner-icon="mdi-lock-check-outline"
              type="password"
              autocomplete="new-password"
              :error-messages="mismatch ? [$t('features.auth.passwordMismatch')] : []"
            />
            <v-btn
              type="submit"
              block
              size="large"
              class="mt-2"
              :loading="busy"
              :disabled="mismatch"
            >
              {{ $t('features.auth.submitSetup') }}
            </v-btn>
          </v-form>
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>
