<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { useCustomizerStore, type ThemeMode } from '@/stores/customizer';
import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

// 设置页（方案 §6.12）：外观 / 安全 / 维护(doctor) / 关于
const toast = useToast();
const customizer = useCustomizerStore();

const username = ref('');
const oldPassword = ref('');
const newPassword = ref('');
const busy = ref(false);
interface DoctorItem {
  id: string;
  level: string;
  title: string;
  detail?: string;
  fix_hint?: string;
}
interface DoctorSummary {
  ok: number;
  warn: number;
  error: number;
  blocking: boolean;
  total: number;
}
interface DoctorReport {
  version: number;
  summary: DoctorSummary;
  items: DoctorItem[];
}
const doctor = ref<{
  ok: boolean;
  report?: DoctorReport;
  summary?: DoctorSummary;
  error?: string;
  output?: string;
  exit_code?: number;
} | null>(null);
const doctorLoading = ref(false);
const showRawDoctor = ref(false);

const storedUser = localStorage.getItem('stella-user') ?? '';
username.value = storedUser;

async function saveAccount(): Promise<void> {
  if (!oldPassword.value || !newPassword.value) {
    toast.warning('请填写当前密码与新密码');
    return;
  }
  busy.value = true;
  try {
    const data = await unwrap<{ token: string }>(
      api.patch('/auth/account', {
        old_password: oldPassword.value,
        new_password: newPassword.value,
      }),
    );
    localStorage.setItem('stella-token', data.token);
    toast.success('密码已修改，其它登录态已注销');
    oldPassword.value = '';
    newPassword.value = '';
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    busy.value = false;
  }
}

async function runDoctor(): Promise<void> {
  doctorLoading.value = true;
  try {
    doctor.value = await unwrap<{ ok: boolean; output: string }>(api.get('/system/doctor'));
  } catch (err) {
    toastApiError(toast, err);
  } finally {
    doctorLoading.value = false;
  }
}

function setTheme(mode: ThemeMode): void {
  customizer.setThemeMode(mode);
}

onMounted(() => {
  // 无额外初始化
});
</script>

<template>
  <v-container fluid class="pa-6">
    <h1 class="text-h5 font-weight-bold mb-4">设置</h1>

    <v-row>
      <v-col cols="12" md="6">
        <v-card class="pa-4 mb-4">
          <div class="text-subtitle-1 font-weight-medium mb-3">外观</div>
          <v-btn-toggle
            :model-value="customizer.themeMode"
            mandatory
            density="compact"
            @update:model-value="(v: ThemeMode) => setTheme(v)"
          >
            <v-btn value="light">浅色</v-btn>
            <v-btn value="dark">深色</v-btn>
            <v-btn value="system">跟随系统</v-btn>
          </v-btn-toggle>
        </v-card>

        <v-card class="pa-4 mb-4">
          <div class="text-subtitle-1 font-weight-medium mb-3">安全</div>
          <v-text-field v-model="username" label="用户名" density="compact" disabled />
          <v-text-field v-model="oldPassword" label="当前密码" type="password" density="compact" />
          <v-text-field v-model="newPassword" label="新密码（≥8 位）" type="password" density="compact" />
          <v-btn color="primary" class="mt-2" :loading="busy" @click="saveAccount">
            修改密码（其它登录态将注销）
          </v-btn>
        </v-card>

        <v-card class="pa-4">
          <div class="text-subtitle-1 font-weight-medium mb-3">关于</div>
          <div class="text-body-2 text-medium-emphasis">
            Stella 控制台 · WebUI v2（设计文档见 design_docs）。AGPL-3.0。
            插件生态与 AstrBot 兼容。
          </div>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card class="pa-4">
          <div class="d-flex align-center mb-3">
            <div class="text-subtitle-1 font-weight-medium">环境自检（doctor）</div>
            <v-spacer />
            <v-btn size="small" :loading="doctorLoading" @click="runDoctor">运行</v-btn>
          </div>
          <div v-if="!doctor" class="text-body-2 text-medium-emphasis">
            运行环境自检（Python/依赖/目录/端口/NapCat 探活）。
          </div>
          <template v-else>
            <!-- 摘要 -->
            <div class="d-flex align-center ga-2 mb-2 flex-wrap">
              <v-chip color="success" size="small" variant="tonal">
                通过 {{ doctor.summary?.ok ?? 0 }}
              </v-chip>
              <v-chip color="warning" size="small" variant="tonal">
                警告 {{ doctor.summary?.warn ?? 0 }}
              </v-chip>
              <v-chip color="error" size="small" variant="tonal">
                错误 {{ doctor.summary?.error ?? 0 }}
              </v-chip>
              <v-chip size="small" variant="outlined">共 {{ doctor.summary?.total ?? 0 }} 项</v-chip>
              <v-chip
                v-if="doctor.summary?.blocking"
                color="error"
                size="small"
                variant="tonal"
              >
                存在阻塞项：Bot 无法启动
              </v-chip>
            </div>
            <v-alert
              v-if="doctor.summary?.blocking"
              type="warning"
              variant="tonal"
              density="compact"
              class="mb-2"
            >
              存在阻塞级问题，deploy start 会拒绝启动。逐项修复（见各项的修复建议）后重跑自检。
            </v-alert>
            <v-alert v-if="doctor.error" type="error" variant="tonal" density="compact" class="mb-2">
              {{ doctor.error }}
              <div v-if="doctor.output" class="text-caption mt-1">{{ doctor.output }}</div>
            </v-alert>

            <!-- 检查项列表 -->
            <v-list density="compact">
              <v-list-item v-for="item in doctor.report?.items ?? []" :key="item.id">
                <template #prepend>
                  <v-icon
                    :icon="
                      item.level === 'error'
                        ? 'mdi-close-circle'
                        : item.level === 'warn'
                          ? 'mdi-alert'
                          : 'mdi-check-circle'
                    "
                    :color="
                      item.level === 'error'
                        ? 'error'
                        : item.level === 'warn'
                          ? 'warning'
                          : 'success'
                    "
                  />
                </template>
                <v-list-item-title class="text-body-2">{{ item.title }}</v-list-item-title>
                <v-list-item-subtitle>
                  {{ item.detail }}
                  <code v-if="item.fix_hint" class="fix-hint mt-1">{{ item.fix_hint }}</code>
                </v-list-item-subtitle>
              </v-list-item>
            </v-list>

            <v-expansion-panels class="mt-2">
              <v-expansion-panel title="原始 JSON">
                <v-expansion-panel-text>
                  <pre class="doctor-pre">{{ JSON.stringify(doctor.report, null, 2) }}</pre>
                </v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
          </template>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<style scoped>
.fix-hint {
  display: block;
  font-size: 0.72rem;
  background: rgba(var(--v-theme-surface), 0.8);
  padding: 2px 6px;
  border-radius: 4px;
}
.doctor-pre {
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.72rem;
  max-height: 420px;
  overflow-y: auto;
  background: rgba(var(--v-theme-background), 0.6);
  border-radius: 8px;
  padding: 8px;
}
</style>
