<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { api, unwrap } from '@/api/http';
import { toastApiError, useToast } from '@/stores/toast';

// 知识库页（方案 §6.7）：列表 → 详情（概览/文档/检索测试/授权）
interface Kb { kb_id: string; name: string; mode: string; role: string }
interface KbDocument { doc_id: string; title: string; status: string; active_version?: number }
interface Evidence { doc_id: string | null; chunk: number | null; text: string; score?: number | null }

const kbs = ref<Kb[]>([]);
const detail = ref<{ name: string; documents: KbDocument[]; grants?: unknown } | null>(null);
const currentId = ref('');
const createDialog = ref(false);
const newName = ref('');
const newDesc = ref('');
const importDialog = ref(false);
const importUrl = ref('');
const importFile = ref<File | null>(null);
const retrieveQuery = ref('');
const retrieveResults = ref<Evidence[]>([]);
const toast = useToast();

async function load(): Promise<void> {
  try {
    kbs.value = (await unwrap<{ knowledge_bases: Kb[] }>(api.get('/knowledge-bases'))).knowledge_bases;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function openDetail(kb: Kb): Promise<void> {
  try {
    detail.value = await unwrap(api.get(`/knowledge-bases/${kb.kb_id}`)) as typeof detail.value;
    currentId.value = kb.kb_id;
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function create(): Promise<void> {
  try {
    await unwrap(api.post('/knowledge-bases', { name: newName.value, description: newDesc.value }));
    toast.success('知识库已创建');
    createDialog.value = false;
    newName.value = '';
    newDesc.value = '';
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function archiveKb(kb: Kb): Promise<void> {
  try {
    await unwrap(api.delete(`/knowledge-bases/${kb.kb_id}`));
    detail.value = null;
    toast.success('已归档');
    await load();
  } catch (err) {
    toastApiError(toast, err);
  }
}

async function importFileNow(): Promise<void> {
  if (importFile.value) {
    const buf = await importFile.value.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(buf).subarray(0, 40 * 1024 * 1024)));
    try {
      const data = await unwrap<{ state: string }>(
        api.post(`/knowledge-bases/${currentId.value}/documents`, {
          file_base64: b64, title: importFile.value.name,
        }),
      );
      toast.success(`导入完成：${data.state}`);
      importDialog.value = false;
      await openDetail({ kb_id: currentId.value } as Kb);
    } catch (err) {
      toastApiError(toast, err);
    }
    return;
  }
  if (importUrl.value) {
    try {
      const data = await unwrap<{ state: string }>(
        api.post(`/knowledge-bases/${currentId.value}/documents`, { url: importUrl.value }),
      );
      toast.success(`导入完成：${data.state}`);
      importDialog.value = false;
      await openDetail({ kb_id: currentId.value } as Kb);
    } catch (err) {
      toastApiError(toast, err);
    }
  }
}

async function retrieveNow(): Promise<void> {
  try {
    const data = await unwrap<{ evidence: Evidence[] }>(
      api.post(`/knowledge-bases/${currentId.value}/retrieve`, { query: retrieveQuery.value }),
    );
    retrieveResults.value = data.evidence;
  } catch (err) {
    toastApiError(toast, err);
  }
}

onMounted(load);
</script>

<template>
  <v-container fluid class="pa-6">
    <div class="d-flex align-center mb-4">
      <h1 class="text-h5 font-weight-bold">知识库</h1>
      <v-spacer />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="createDialog = true">新建</v-btn>
    </div>

    <v-row v-if="!detail">
      <v-col v-for="kb in kbs" :key="kb.kb_id" cols="12" sm="6" md="4">
        <v-card class="pa-4" @click="openDetail(kb)">
          <div class="text-subtitle-1 font-weight-medium">{{ kb.name }}</div>
          <div class="text-caption text-medium-emphasis">{{ kb.mode }} · 我的角色 {{ kb.role }}</div>
        </v-card>
      </v-col>
    </v-row>
    <div v-if="!detail && !kbs.length" class="text-body-2 text-medium-emphasis pa-4">
      还没有知识库。知识库是「你主动上传的外部资料」，与个人长期记忆分库存储。
    </div>

    <v-card v-if="detail" class="pa-4">
      <div class="d-flex align-center mb-3">
        <v-btn variant="text" prepend-icon="mdi-arrow-left" @click="detail = null; currentId = ''">
          返回
        </v-btn>
        <div class="text-subtitle-1 font-weight-medium ml-2">{{ currentId }}</div>
        <v-spacer />
        <v-btn size="small" color="primary" prepend-icon="mdi-upload" @click="importDialog = true">
          导入文档
        </v-btn>
        <v-btn size="small" color="error" variant="text" @click="archiveKb({ kb_id: currentId } as Kb)">
          归档
        </v-btn>
      </div>

      <div class="text-subtitle-2 mb-1">文档</div>
      <v-table density="compact" v-if="detail.documents?.length">
        <thead><tr><th>文档</th><th>状态</th><th>版本</th></tr></thead>
        <tbody>
          <tr v-for="doc in detail.documents" :key="doc.doc_id">
            <td>{{ doc.title }}</td>
            <td><v-chip size="x-small" variant="tonal">{{ doc.status }}</v-chip></td>
            <td>{{ doc.active_version ?? '—' }}</td>
          </tr>
        </tbody>
      </v-table>
      <div v-else class="text-body-2 text-medium-emphasis">还没有文档。</div>

      <div class="text-subtitle-2 mt-4 mb-1">检索测试</div>
      <div class="d-flex ga-2">
        <v-text-field v-model="retrieveQuery" label="查询" density="compact" hide-details />
        <v-btn color="primary" @click="retrieveNow">检索</v-btn>
      </div>
      <v-card v-for="(ev, i) in retrieveResults" :key="i" variant="outlined" class="pa-3 mt-2">
        <div class="text-caption text-medium-emphasis">
          文档 {{ ev.doc_id }} · chunk {{ ev.chunk }} · 分数 {{ ev.score ?? '—' }}
        </div>
        <div class="text-body-2">{{ ev.text }}</div>
      </v-card>
      <div class="text-caption text-disabled mt-2">
        知识库内容不会成为 Stella 的长期记忆（隔离护栏）。
      </div>
    </v-card>

    <v-dialog v-model="createDialog" width="460">
      <v-card>
        <v-card-title>新建知识库</v-card-title>
        <v-card-text>
          <v-text-field v-model="newName" label="名称" />
          <v-text-field v-model="newDesc" label="描述" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="createDialog = false">取消</v-btn>
          <v-btn color="primary" @click="create">创建</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="importDialog" width="520">
      <v-card>
        <v-card-title>导入文档（md/txt/pdf/docx 或 URL）</v-card-title>
        <v-card-text>
          <v-file-input v-model="importFile" label="选择文件" density="compact" />
          <v-text-field v-model="importUrl" label="或导入 URL" density="compact" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="importDialog = false">取消</v-btn>
          <v-btn color="primary" @click="importFileNow">导入</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>
