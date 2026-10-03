<script setup lang="ts">
// 个人记忆管理页（计划 §6.9）：owner/audience 精确筛选 + 删除/导出。
// 服务端只认 PERSON 行；本页筛选只是视图，不充当授权。
import { onMounted, ref } from 'vue'

interface PersonalMemoryItem {
  id: string
  owner_key: string
  subject_key: string
  audience: string
  source_conversation_key: string
  type: string
  content: string
  importance: number | null
  confidence: number | null
  status: string
  policy_version: string
  updated_at: string | null
}

const items = ref<PersonalMemoryItem[]>([])
const total = ref(0)
const loading = ref(false)
const subjectFilter = ref('')
const audienceFilter = ref('')
const page = ref(1)
const itemsPerPage = 50

async function load() {
  loading.value = true
  try {
    const params = new URLSearchParams({
      subject_key: subjectFilter.value,
      audience: audienceFilter.value,
      limit: String(itemsPerPage),
      offset: String((page.value - 1) * itemsPerPage),
    })
    const res = await fetch(`/api/v1/personal-memory?${params}`)
    const body = await res.json()
    items.value = body?.data?.items ?? []
    total.value = body?.data?.total ?? 0
  } finally {
    loading.value = false
  }
}

async function remove(item: PersonalMemoryItem) {
  if (!window.confirm(`确认删除该条个人记忆（${item.subject_key} / ${item.audience}）？删除不可恢复。`)) return
  await fetch(`/api/v1/personal-memory/${item.id}`, { method: 'DELETE' })
  await load()
}

async function exportAll() {
  const params = new URLSearchParams({ subject_key: subjectFilter.value })
  const res = await fetch(`/api/v1/personal-memory/export?${params}`)
  const body = await res.json()
  const blob = new Blob([JSON.stringify(body?.data ?? {}, null, 2)], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'personal-memory-export.json'
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(load)
</script>

<template>
  <v-card flat>
    <v-card-title class="d-flex align-center ga-4">
      <span>个人记忆（PERSON 归属）</span>
      <v-spacer />
      <v-text-field
        v-model="subjectFilter"
        label="主体（qq:<QQ号>）"
        density="compact"
        hide-details
        clearable
        style="max-width: 220px"
        @keyup.enter="page = 1; load()"
      />
      <v-select
        v-model="audienceFilter"
        :items="['', 'PRIVATE_ONLY', 'USER_SHARED']"
        label="受众"
        density="compact"
        hide-details
        style="max-width: 180px"
        @update:model-value="page = 1; load()"
      />
      <v-btn color="primary" variant="tonal" :loading="loading" @click="page = 1; load()">
        查询
      </v-btn>
      <v-btn variant="tonal" @click="exportAll">导出 JSON</v-btn>
    </v-card-title>
    <v-card-text>
      <v-data-table
        :headers="[
          { title: '主体', key: 'subject_key' },
          { title: '受众', key: 'audience' },
          { title: '类型', key: 'type' },
          { title: '来源会话', key: 'source_conversation_key' },
          { title: '重要度', key: 'importance' },
          { title: '更新时间', key: 'updated_at' },
          { title: '操作', key: 'actions', sortable: false },
        ]"
        :items="items"
        :items-length="total"
        :loading="loading"
        :items-per-page="itemsPerPage"
        density="compact"
      >
        <template #item.audience="{ item }">
          <v-chip :color="item.audience === 'PRIVATE_ONLY' ? 'error' : 'primary'" size="small">
            {{ item.audience }}
          </v-chip>
        </template>
        <template #item.updated_at="{ item }">
          {{ item.updated_at ? new Date(item.updated_at + 'Z').toLocaleString() : '' }}
        </template>
        <template #item.actions="{ item }">
          <v-btn icon="mdi-delete" size="small" variant="text" color="error" @click="remove(item)" />
        </template>
      </v-data-table>
      <v-alert type="info" variant="tonal" density="compact" class="mt-4">
        仅显示 PERSON 归属的记忆；群空间记忆请在「会话/记忆」页按空间管理。
        删除会立即推进该主体的缓存版本（各端热缓存随即失效）。
      </v-alert>
    </v-card-text>
  </v-card>
</template>
