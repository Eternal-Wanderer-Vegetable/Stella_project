<script setup lang="ts">
import { ref } from 'vue';
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
const busy = ref(false);

async function submit(): Promise<void> {
  if (!username.value || !password.value || busy.value) return;
  busy.value = true;
  try {
    await auth.login(username.value, password.value);
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
            <v-card-title class="text-h5">{{ $t('features.auth.loginTitle') }}</v-card-title>
          </div>
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
              autocomplete="current-password"
            />
            <v-btn
              type="submit"
              block
              size="large"
              class="mt-2"
              :loading="busy"
            >
              {{ $t('features.auth.submitLogin') }}
            </v-btn>
          </v-form>
        </v-card-text>
      </v-card>
    </v-col>
  </v-row>
</template>
