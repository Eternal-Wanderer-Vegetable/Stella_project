<script setup lang="ts">
// 消息流程页（计划 §6.7）：左侧消息筛选 / 中央分层流式画布 / 浮动节点详情卡。
// 布局为 ComfyUI 式左→右分层流（有始有终：开始/结束锚点见 flowLayout）。
// 「完整流程/实际路径」共用同一套坐标：切换只是淡出未走过的节点与边
// （CSS 过渡），不是两张图硬切。未走过的路径灰色「未走到」，绝不标 skipped。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import type { FlowEvent, FlowMessageSummary } from '@/api/flow';
import { useFlowStore } from '@/stores/flow';
import { fitNodeText } from '@/stores/flowReducer';
import { formatDbTime } from '@/utils/time';
import {
  edgePath,
  layoutExecuted,
  layoutLayered,
  type LaidEdge,
  type LaidNode,
} from '@/views/data/flowLayout';

const store = useFlowStore();

const ROOT_KIND_LABELS: Record<string, string> = {
  qq_passive: 'QQ 被动消息',
  qq_chat: 'QQ 对话',
  qq_command: 'QQ 命令',
  webchat: 'WebChat',
  proactive: '主动发言',
  consolidate: '记忆整合',
  compact: '会话压缩',
  cometa_task: 'Cometa 任务',
  effect: '效果结算',
};

// 业务结果的中文名（root 结束时的 outcome 事实；未知值原样展示）
const OUTCOME_LABELS: Record<string, string> = {
  passive_only: '仅被动记录',
  delivered: '已送达',
  partial: '部分送达',
  not_delivered: '未送达',
  budget_blocked: '预算拦截',
  cancelled: '已取消',
  silent: '保持沉默',
  plugin_handled: '插件接管',
  command_done: '命令完成',
  command_sent: '命令已发送',
  command_error: '命令出错',
  blocked: '已阻断',
  done: '已完成',
  error: '出错',
  closed: '已关闭',
};

const STATUS_COLORS: Record<string, string> = {
  succeeded: '#4caf50',
  closed: '#4caf50',
  running: '#2196f3',
  waiting: '#00bcd4',
  failed: '#f44336',
  blocked: '#ff9800',
  cancelled: '#9e9e9e',
  timed_out: '#9c27b0',
  skipped: '#78909c',
  unknown: '#bdbdbd',
  not_observed: '#5c6470',
};

// 泳道 → 色相（节点左色条 + 图例；按目录泳道顺序取色）
const LANE_HUES: Record<string, string> = {
  web: 'hsl(205, 70%, 55%)',
  ingress: 'hsl(145, 60%, 45%)',
  command: 'hsl(275, 55%, 60%)',
  gate: 'hsl(35, 85%, 55%)',
  prepare: 'hsl(190, 65%, 45%)',
  capability: 'hsl(260, 60%, 62%)',
  generate: 'hsl(0, 70%, 60%)',
  finalize: 'hsl(95, 55%, 45%)',
  delivery: 'hsl(160, 65%, 40%)',
  background: 'hsl(45, 80%, 50%)',
  cometa: 'hsl(320, 60%, 55%)',
  other: 'hsl(210, 10%, 55%)',
};

const laneColor = (lane: string) => LANE_HUES[lane] ?? LANE_HUES.other;

const NODE_W = 128;
const NODE_H = 40;
const CARD_W = 380;

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const playing = ref(false);
let playTimer: ReturnType<typeof setInterval> | null = null;
// O10：播放速率（0.5x/1x/2x/4x），步进间隔 = 300ms / speed
const playbackSpeed = ref(1);
const SPEED_OPTIONS = [0.5, 1, 2, 4];

// 两种视图共用同一布局坐标；'executed' 只是把未走过的元素淡出
const viewMode = ref<'full' | 'executed'>('full');
const canvasEl = ref<HTMLElement | null>(null);
// 浮动详情卡：锚在节点点击位置（相对画布容器）
const card = ref<{ nodeId: string; x: number; y: number } | null>(null);
// 视图切换的边淡出窗口：节点在滑动到位前，先把旧路径藏起来
const morphing = ref(false);
let morphTimer: ReturnType<typeof setTimeout> | null = null;

// O09 生命周期：页面隐藏停 SSE、恢复补读重连；列表轮询随页面挂载/卸载
function onVisibility() {
  store.onVisibilityChange();
}

onMounted(() => {
  void store.loadMessages();
  store.startListPolling();
  document.addEventListener('visibilitychange', onVisibility);
});

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibility);
  store.stopListPolling();
  store.stopStream();
  stopPlay();
  if (morphTimer) clearTimeout(morphTimer);
});

const laneLegend = computed<Array<{ id: string; label: string; color: string }>>(
  () => {
    const lanes: Array<[string, string]> = store.spec?.lanes ?? [];
    return lanes.map(([id, label]) => ({ id, label, color: laneColor(id) }));
  },
);

const laneLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {};
  for (const [id, label] of store.spec?.lanes ?? []) out[id] = label;
  out.other = '其他';
  return out;
});

/**
 * 分层流式布局：完整 = 目录全图；实际 = 已执行子图收束成一条连通路径。
 * 切换时节点按 CSS transform 过渡滑到新坐标（边淡出再淡入），不是硬切。
 *
 * 修复计划 §6.6（R8）：缺 spec（unmapped/invalid）时从事件事实回退——
 * 节点来自运行事实（unknown 占位），边只来自合法 transition 事实，
 * 绝不返回 graphLayout=null 让「实际路径」空白误导。
 */
const fallbackSpec = computed(() => {
  const transitions = store.transitionFacts;
  const edges: Array<{ src: string; dst: string; kind: string; label: string }> = [];
  const seen = new Set<string>();
  for (const t of transitions) {
    const m = (t.metrics ?? {}) as Record<string, unknown>;
    const from = String(m.from_node ?? '');
    const to = String(m.to_node ?? '');
    if (!from || !to || from === to) continue;
    const key = `${from}->${to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ src: from, dst: to, kind: String(m.relation_kind ?? 'order'), label: '' });
  }
  return {
    lanes: [] as Array<[string, string]>,
    nodes: [],
    edges,
    entry_roots: {},
  };
});

const graphLayout = computed(() => {
  const spec = store.spec ?? fallbackSpec.value;
  if (!store.detail) return null;
  if (!store.spec && !store.executedNodeMap.size) return null;
  const input = {
    spec,
    executed: store.executedNodeMap,
    labelOf: (nodeId: string) => store.nodeLabel(nodeId),
    laneOf: (nodeId: string) => store.nodeLane(nodeId),
    transitions: store.transitionFacts,
    rootEnded: store.rootEnded,
  };
  return viewMode.value === 'full'
    ? layoutLayered(input)
    : layoutExecuted(input);
});
const laidNodes = computed<LaidNode[]>(() => graphLayout.value?.nodes ?? []);
const laidEdges = computed<LaidEdge[]>(() => graphLayout.value?.edges ?? []);
const canvasSize = computed(() => ({
  w: graphLayout.value?.width ?? 400,
  h: graphLayout.value?.height ?? 200,
}));

/** 节点是否激活过（有真实事件；锚点恒为激活态）。 */
function isExecuted(node: LaidNode): boolean {
  return node.anchor !== undefined || store.executedNodeMap.has(node.nodeId);
}

function edgeClass(e: LaidEdge): Record<string, boolean> {
  return {
    'flow-edge': true,
    [`edge-${e.kind}`]: true,
    active: Boolean(e.active) && viewMode.value === 'full',
    dim:
      viewMode.value === 'full' &&
      !e.active &&
      e.kind !== 'spawn' &&
      e.kind !== 'cause',
    // O05：实际视图里两端都执行过、但没有真实 transition 事实的边
    //（如只走了另一条分支）画成虚线淡显，不冒充走过的路径
    untaken: viewMode.value === 'executed' && e.traversed === false,
    morph: morphing.value,
  };
}

const selectedNode = computed<LaidNode | null>(() => {
  if (!card.value) return null;
  return laidNodes.value.find((n) => n.nodeId === card.value?.nodeId) ?? null;
});

const selectedNodeDetail = computed(() =>
  store.executedNodeMap.get(card.value?.nodeId ?? '') ?? null,
);

const currentEvent = computed<FlowEvent | null>(() => {
  if (store.playbackIndex < 0) return null;
  return store.orderedEvents[store.playbackIndex] ?? null;
});

// O01/M1 完整性合同：integrity（writer 账本）优先于 producer 粗视角
//（complete/loss）；unknown = 观测自身失败，不冒充任何一种完整
const completenessText = computed(() => {
  const d = store.detail;
  if (!d) return '';
  if (d.integrity === 'unknown') return '完整性未知（观测自身失败）';
  if (d.integrity === 'complete') return '完整（已持久化）';
  if (d.integrity === 'partial') return '不完整（partial）';
  if (d.loss) return '有已知丢失（known loss）';
  if (d.status === 'interrupted') return '进程中断，未闭合（partial）';
  if (!d.complete) return '不完整（partial）';
  return '完整';
});

const rootKindLabel = (item: FlowMessageSummary) =>
  ROOT_KIND_LABELS[item.root_kind] ?? item.root_kind;

// 修复计划 §6.2（R5/R8）：spec 缺失的诚实文案——不猜绑定，事实仍可读
const specMissingText = computed(() => {
  const binding = store.detail?.spec_binding ?? '';
  if (binding === 'invalid') return 'spec 归档缺失（invalid）：事件事实如下';
  if (binding === 'legacy_unverified') return '旧版拓扑（未验证绑定）：事件事实如下';
  return '拓扑版本缺失（unmapped）：按事件回退展示';
});

// 列表图标按 O01 修复后的活跃判定：running=在跑，interrupted=过期化身，
// 其余为已知终态（closed/outcome 落定）
function listIcon(status: string): string {
  if (status === 'running') return 'mdi-play-circle';
  if (status === 'interrupted') return 'mdi-alert-circle';
  return 'mdi-check-circle';
}

const outcomeLabel = (outcome: string) => OUTCOME_LABELS[outcome] ?? outcome;

// 库里是 UTC（+00:00）：必须转本地时区显示，否则会被当成「记录停在几小时前」
const fmtTime = (iso: string) => formatDbTime(iso);

function pick(item: FlowMessageSummary) {
  closeCard();
  playing.value = false;
  stopPlay();
  void store.openTrace(item.trace_id).then(() => {
    void store.loadSpec();
    // 以详情接口的最新状态为准（列表可能滞后）：interrupted 不再订阅
    if (store.detail?.status === 'interrupted') return;
    void store.startStream();
  });
}

// 修复计划 §6.6（R8）：输出/全部指标可展开——「前 4 行输出 / 最近一组
// metrics」不再被当成全部；截断/不可用必须显式可展开
const showAllOutput = ref(false);
const showAllMetrics = ref(false);

// 修复计划 §6.6（R7）：关联轨迹可跳转；对象履历可反查并回跳运行
function openRelatedTrace(traceId: string) {
  if (!traceId) return;
  void store.openTrace(traceId).then(() => {
    void store.loadSpec();
  });
}

const entityDialog = ref(false);
const entityHistory = ref<Array<Record<string, unknown>>>([]);
const entityHistoryKey = ref('');

async function openEntityHistory(entityType: string, entityId: string) {
  entityHistoryKey.value = `${entityType}:${entityId}`;
  try {
    const { getEntityHistory } = await import('@/api/flow');
    entityHistory.value = await getEntityHistory(entityType, entityId) as Array<Record<string, unknown>>;
  } catch {
    entityHistory.value = [];
  }
  entityDialog.value = true;
}

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.unknown;
}

// O10：「未观测」（spec 有、本次无任何事件）与「明确跳过」（status=skipped
// 事实）是两回事；未观测不解释为跳过，也不说「未走到」。
const NODE_STATUS_LABELS: Record<string, string> = {
  not_observed: '未观测',
  skipped: '已跳过',
};

function nodeStatusText(status: string): string {
  return NODE_STATUS_LABELS[status] ?? status;
}

// 未激活 = 统一灰（体/条同灰）；激活 = 状态色。泳道归属由彩色圆点标识。
const INACTIVE_BODY = '#757575';
const INACTIVE_BAR = '#9e9e9e';

function nodeBodyColor(n: LaidNode): string {
  if (n.anchor !== undefined) {
    return n.anchor === 'start' ? '#4caf50' : '#78909c';
  }
  return isExecuted(n) ? statusColor(n.status) : INACTIVE_BODY;
}

function nodeBarColor(n: LaidNode): string {
  if (n.anchor !== undefined) return 'transparent';
  return isExecuted(n) ? statusColor(n.status) : INACTIVE_BAR;
}

function onNodeClick(node: LaidNode, event?: MouseEvent) {
  if (node.anchor !== undefined) return;
  store.selectNode(node.nodeId);
  const rect = canvasEl.value?.getBoundingClientRect();
  const clickX = event ? event.clientX - (rect?.left ?? 0) : (rect?.width ?? 400) / 2;
  const clickY = event ? event.clientY - (rect?.top ?? 0) : (rect?.height ?? 300) / 2;
  const maxX = (rect?.width ?? 800) - CARD_W - 12;
  const maxY = (rect?.height ?? 480) - 320;
  card.value = {
    nodeId: node.nodeId,
    x: Math.max(8, Math.min(clickX + 14, maxX)),
    y: Math.max(8, Math.min(clickY - 20, maxY)),
  };
}

function closeCard() {
  card.value = null;
  store.selectNode('');
}

watch(viewMode, () => {
  // 布局变化：卡锚点失效；边先淡出，节点滑到新坐标后再淡入
  closeCard();
  if (reducedMotion) return;
  morphing.value = true;
  if (morphTimer) clearTimeout(morphTimer);
  morphTimer = setTimeout(() => {
    morphing.value = false;
  }, 480);
});

// O10：按当前速率启动步进定时器（间隔 = 300ms / speed）
function startPlayTimer() {
  stopPlayTimer();
  playTimer = setInterval(() => {
    if (store.playbackIndex >= store.orderedEvents.length - 1) {
      stopPlay();
      return;
    }
    store.stepPlayback(1);
  }, reducedMotion ? 0 : 300 / playbackSpeed.value);
}

function stopPlayTimer() {
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
  }
}

function togglePlay() {
  if (playing.value) {
    stopPlay();
    return;
  }
  if (store.playbackIndex < 0) store.setPlayback(0);
  playing.value = true;
  startPlayTimer();
  if (reducedMotion) {
    stopPlay();
  }
}

// O10：播放中切速率 → 立即按新间隔重启定时器
watch(playbackSpeed, () => {
  if (!playing.value || reducedMotion) return;
  startPlayTimer();
});

function stopPlay() {
  playing.value = false;
  stopPlayTimer();
}

const platformOptions = ['qq', 'webchat', 'cometa'];
const rootKindOptions = Object.keys(ROOT_KIND_LABELS);
</script>

<template>
  <v-row dense>
    <!-- 左：消息列表 -->
    <v-col cols="12" md="3">
      <v-card variant="flat" :elevation="1">
        <v-card-title class="text-subtitle-1">消息</v-card-title>
        <v-card-text class="pb-0">
          <v-select
            v-model="store.platformFilter"
            :items="platformOptions"
            label="平台"
            clearable
            density="compact"
            hide-details
            class="mb-2"
            @update:model-value="store.loadMessages()"
          />
          <v-select
            v-model="store.rootKindFilter"
            :items="rootKindOptions"
            label="入口"
            clearable
            density="compact"
            hide-details
            @update:model-value="store.loadMessages()"
          />
        </v-card-text>
        <v-list density="compact" class="flow-list">
          <v-list-item
            v-for="item in store.messages"
            :key="item.trace_id"
            :active="store.detail?.trace_id === item.trace_id"
            @click="pick(item)"
          >
            <template #prepend>
              <v-icon
                :icon="listIcon(item.status)"
                :color="item.status === 'running' ? 'primary' : (item.complete ? 'success' : 'warning')"
                size="small"
              />
            </template>
            <v-list-item-title class="text-body-2">
              {{ rootKindLabel(item) }}
              <v-chip v-if="item.outcome" size="x-small" class="ml-1" label>
                {{ outcomeLabel(item.outcome) }}
              </v-chip>
            </v-list-item-title>
            <v-list-item-subtitle class="text-caption">
              {{ fmtTime(item.started_utc) }} · {{ item.scope || item.platform }}
            </v-list-item-subtitle>
          </v-list-item>
          <v-list-item v-if="!store.messages.length">
            <v-list-item-title class="text-body-2 text-medium-emphasis">
              暂无消息轨迹（开启 Bot 后处理消息即会出现）
            </v-list-item-title>
          </v-list-item>
          <v-list-item v-if="store.messagesCursor">
            <v-btn
              block
              size="small"
              variant="text"
              :loading="store.loadingList"
              @click="store.loadMoreMessages()"
            >
              加载更早的轨迹（已载 {{ store.messages.length }} / 共 {{ store.messagesTotal }}）
            </v-btn>
          </v-list-item>
        </v-list>
      </v-card>
    </v-col>

    <!-- 中：画布 + 播放 -->
    <v-col cols="12" md="9">
      <v-card variant="flat" :elevation="1">
        <v-card-text v-if="!store.detail" class="text-medium-emphasis">
          选择左侧一条消息，查看它从「开始」到「结束」经过的完整处理流程（灰色虚线节点是本次未观测到的路径——没有事实，不解释为跳过或未执行）。
        </v-card-text>
        <template v-else>
          <v-card-text class="pb-0 d-flex flex-wrap ga-2 align-center">
            <span class="text-subtitle-2">
              {{ ROOT_KIND_LABELS[store.detail.root_kind] ?? store.detail.root_kind }}
            </span>
            <v-chip size="x-small" label>{{ store.detail.scope }}</v-chip>
            <v-chip
              size="x-small"
              label
              :color="store.detail.complete ? 'success' : 'warning'"
            >
              {{ completenessText }}
            </v-chip>
            <v-chip
              v-if="(store.detail.lost_events ?? 0) > 0"
              size="x-small"
              label
              color="error"
            >
              丢失 {{ store.detail.lost_events }} 条事件
            </v-chip>
            <v-chip v-if="store.spec" size="x-small" label>
              图版本 {{ store.spec.topology_version }}
              <template v-if="store.detail.spec_binding === 'exact'"> · 精确绑定</template>
              <template v-else-if="store.detail.spec_binding === 'legacy_unverified'"> · 旧版未验证</template>
            </v-chip>
            <v-chip v-else size="x-small" label color="warning">
              {{ specMissingText }}
            </v-chip>
            <v-spacer />
            <v-btn-toggle
              v-model="viewMode"
              mandatory
              density="compact"
              variant="outlined"
            >
              <v-btn value="full" size="small">完整流程</v-btn>
              <v-btn value="executed" size="small">实际路径</v-btn>
            </v-btn-toggle>
            <v-btn
              v-if="!store.live"
              size="x-small"
              variant="tonal"
              prepend-icon="mdi-play-circle"
              @click="store.startStream()"
            >
              实时
            </v-btn>
            <v-btn
              v-else
              size="x-small"
              variant="tonal"
              color="primary"
              prepend-icon="mdi-stop-circle"
              @click="store.stopStream()"
            >
              停止
            </v-btn>
            <v-btn
              size="x-small"
              variant="text"
              :loading="store.eventsLoading"
              @click="store.refreshTraceBundle()"
            >
              刷新
            </v-btn>
          </v-card-text>

          <!-- 关联轨迹（trace 间因果，独立于画布节点）：可点击跳转（R7） -->
          <v-card-text
            v-if="store.detail.relations.length"
            class="pt-1 pb-0 d-flex flex-wrap ga-2 align-center"
          >
            <span class="text-caption text-medium-emphasis">关联：</span>
            <v-chip
              v-for="(rel, i) in store.detail.relations"
              :key="i"
              size="x-small"
              label
              variant="tonal"
              class="flow-relation-chip"
              :title="`打开关联轨迹 ${rel.trace_id.slice(0, 8)}…`"
              @click="openRelatedTrace(rel.trace_id)"
            >
              <v-icon start size="x-small">mdi-link-variant</v-icon>
              {{ rel.direction === 'out' ? '派生' : '触发自' }}
              {{ rel.trace_id.slice(0, 8) }}…
              <template v-if="rel.evidence">（{{ rel.evidence }}）</template>
            </v-chip>
          </v-card-text>

          <!-- 对象履历（修复计划 §6.6 R7）：消息 → 整合/候选/通知对象可追踪 -->
          <v-card-text
            v-if="store.traceEntities.length"
            class="pt-1 pb-0 d-flex flex-wrap ga-2 align-center"
          >
            <span class="text-caption text-medium-emphasis">对象：</span>
            <v-chip
              v-for="(ent, i) in store.traceEntities.slice(0, 12)"
              :key="i"
              size="x-small"
              label
              variant="outlined"
              class="flow-relation-chip"
              :title="`${ent.entity_type}:${ent.entity_id} 的状态履历`"
              @click="openEntityHistory(String(ent.entity_type), String(ent.entity_id))"
            >
              <v-icon start size="x-small">mdi-shape-outline</v-icon>
              {{ ent.entity_type }}:{{ String(ent.entity_id).slice(0, 10) }}
              <template v-if="ent.to_state"> → {{ ent.to_state }}</template>
            </v-chip>
            <span v-if="store.traceEntities.length > 12" class="text-caption text-medium-emphasis">
              …共 {{ store.traceEntities.length }} 条对象变化
            </span>
          </v-card-text>

          <!-- 输入 / 输出：这条消息进去什么样、回复出来什么样 -->
          <v-card-text
            v-if="store.io && (store.io.input || store.io.output.lines.length || store.io.notes.length)"
            class="pt-1 pb-0"
          >
            <div class="io-grid">
              <div class="io-cell">
                <div class="text-caption text-medium-emphasis mb-1">
                  <v-icon size="x-small">mdi-import</v-icon> 输入
                </div>
                <div v-if="store.io.input" class="io-text" :title="store.io.input.content">
                  {{ store.io.input.content }}
                </div>
                <div v-else class="text-caption text-medium-emphasis">（无用户输入）</div>
              </div>
              <div class="io-cell">
                <div class="text-caption text-medium-emphasis mb-1">
                  <v-icon size="x-small">mdi-export</v-icon> 输出
                  <span v-if="store.io.output.count">（{{ store.io.output.count }} 行）</span>
                </div>
                <div v-if="store.io.output.lines.length">
                  <div
                    v-for="(line, i) in (showAllOutput
                      ? store.io.output.lines
                      : store.io.output.lines.slice(0, 4))"
                    :key="i"
                    class="io-text"
                    :title="line"
                  >
                    {{ line }}
                  </div>
                  <v-btn
                    v-if="store.io.output.lines.length > 4"
                    size="x-small"
                    variant="text"
                    class="px-0"
                    @click="showAllOutput = !showAllOutput"
                  >
                    {{ showAllOutput
                      ? '收起'
                      : `展开全部 ${store.io.output.lines.length} 行` }}
                  </v-btn>
                </div>
                <div v-else class="text-caption text-medium-emphasis">（无）</div>
              </div>
            </div>
            <div v-if="store.io.notes.length" class="text-caption text-medium-emphasis mt-1">
              {{ store.io.notes.join('；') }}
            </div>
          </v-card-text>

          <!-- 泳道图例（节点圆点颜色 ↔ 处理阶段） -->
          <v-card-text
            v-if="laneLegend.length"
            class="pt-1 pb-0 d-flex flex-wrap ga-2 align-center"
          >
            <span
              v-for="lane in laneLegend"
              :key="lane.id"
              class="d-inline-flex align-center ga-1 text-caption text-medium-emphasis"
            >
              <span
                class="lane-dot"
                :style="{ background: lane.color }"
              />{{ lane.label }}
            </span>
          </v-card-text>

          <div
            ref="canvasEl"
            class="flow-canvas"
            :class="{ 'reduce-motion': reducedMotion }"
            @click.self="closeCard"
          >
            <svg
              :width="canvasSize.w"
              :height="canvasSize.h"
              :viewBox="`0 0 ${canvasSize.w} ${canvasSize.h}`"
              role="img"
              aria-label="消息处理流程图：从开始到结束的分层流式布局"
              @click.self="closeCard"
            >
              <defs>
                <marker
                  id="flow-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--v-theme-on-surface)" opacity="0.5" />
                </marker>
              </defs>
              <!-- 边 -->
              <g>
                <path
                  v-for="e in laidEdges"
                  :key="e.id"
                  :d="edgePath(e.from, e.to)"
                  :class="edgeClass(e)"
                  marker-end="url(#flow-arrow)"
                />
              </g>
              <!-- 节点（外层 g 以 CSS transform 定位：视图切换时滑动过渡） -->
              <g
                v-for="n in laidNodes"
                :key="n.nodeId"
                class="flow-node-pos"
                :style="{ transform: `translate(${n.x}px, ${n.y}px)` }"
              >
                <g
                  class="flow-node"
                  :class="{
                    selected: n.nodeId === card?.nodeId,
                    pulse: n.status === 'running' && !reducedMotion,
                    unexecuted: !isExecuted(n),
                  }"
                  role="button"
                  :tabindex="n.anchor === undefined ? 0 : -1"
                  @click.stop="onNodeClick(n, $event)"
                  @keydown.enter="onNodeClick(n)"
                >
                  <!-- 锚点：开始 / 结束 -->
                  <template v-if="n.anchor !== undefined">
                    <rect
                      width="64"
                      height="26"
                      rx="13"
                      :fill="nodeBodyColor(n)"
                      opacity="0.92"
                    />
                    <text x="32" y="17" class="flow-anchor-label">
                      {{ n.label }}
                    </text>
                  </template>
                  <template v-else>
                    <rect
                      :width="NODE_W"
                      :height="NODE_H"
                      rx="8"
                      :fill="nodeBodyColor(n)"
                      opacity="0.92"
                    />
                    <!-- 左条：只有激活（状态色）/ 未激活（灰）两种 -->
                    <rect width="5" :height="NODE_H" rx="2" :fill="nodeBarColor(n)" />
                    <!-- 泳道归属圆点（唯一的泳道色彩来源） -->
                    <circle
                      :cx="NODE_W - 11"
                      cy="12"
                      r="4"
                      :fill="laneColor(n.lane)"
                    >
                      <title>{{ laneLabels[n.lane] ?? n.lane }}</title>
                    </circle>
                    <text :x="NODE_W / 2" :y="17" class="flow-node-label">
                      {{ fitNodeText(n.label, 13) }}
                    </text>
                    <text :x="NODE_W / 2" :y="31" class="flow-node-status">
                      {{ fitNodeText(isExecuted(n) ? nodeStatusText(n.status) : '未观测', 18) }}<template v-if="n.instances > 1"> ×{{ n.instances }}</template>
                    </text>
                  </template>
                </g>
              </g>
            </svg>
            <div v-if="!laidNodes.length" class="text-medium-emphasis pa-4">
              暂无节点{{ store.spec ? '' : '（拓扑清单缺失，无法渲染完整流程）' }}。
            </div>

            <!-- 浮动节点详情卡 -->
            <v-card
              v-if="selectedNode"
              class="flow-card"
              :style="{ left: `${card?.x}px`, top: `${card?.y}px` }"
              variant="elevated"
              :elevation="6"
              @click.stop
            >
              <v-card-text class="pa-3">
                <div class="d-flex align-center ga-1 mb-1">
                  <span
                    class="lane-dot"
                    :style="{ background: laneColor(selectedNode.lane) }"
                  />
                  <span class="text-subtitle-2">{{ selectedNode.label }}</span>
                  <v-chip
                    size="x-small"
                    label
                    :color="statusColor(selectedNode.status)"
                  >
                    {{ nodeStatusText(selectedNode.status) }}
                  </v-chip>
                  <v-spacer />
                  <v-btn
                    icon="mdi-close"
                    size="x-small"
                    variant="text"
                    @click="closeCard"
                  />
                </div>
                <div class="text-caption text-medium-emphasis mb-1">
                  {{ selectedNode.nodeId }}
                  <template v-if="selectedNode.spec?.kind === 'unknown'">
                    · 未知节点（不在当前目录，事件事实如下）
                  </template>
                  <template v-else-if="selectedNode.spec?.opaque"> · 外部边界（opaque）</template>
                  <template v-if="selectedNode.spec?.derived"> · 派生节点</template>
                  <template v-if="selectedNode.spec && selectedNode.spec.kind !== 'unknown'">
                    · {{ laneLabels[selectedNode.lane] ?? selectedNode.lane }}
                  </template>
                </div>
                <div v-if="selectedNode.status === 'skipped'" class="text-body-2 mb-1">
                  已跳过<template v-if="selectedNode.outcome">（原因：{{ selectedNode.outcome }}）</template>
                </div>
                <div v-else-if="selectedNode.outcome" class="text-body-2 mb-1">
                  事实：{{ selectedNode.outcome }}
                </div>
                <div v-if="selectedNodeDetail" class="text-caption mb-1">
                  实例 {{ selectedNode.instances }}
                  <template v-if="selectedNodeDetail.running_count"> · 在跑 {{ selectedNodeDetail.running_count }}</template>
                  <template v-if="selectedNodeDetail.succeeded_count"> · 成功 {{ selectedNodeDetail.succeeded_count }}</template>
                  <template v-if="selectedNodeDetail.failed_count"> · 失败 {{ selectedNodeDetail.failed_count }}</template>
                  <template v-if="selectedNodeDetail.durationMs != null">
                    · 最近耗时 {{ selectedNodeDetail.durationMs.toFixed(1) }} ms
                  </template>
                </div>
                <div v-else class="text-caption text-medium-emphasis mb-1">
                  本次消息未观测到这个节点（无事实，不猜测原因）。
                </div>
                <template v-if="selectedNodeDetail?.events?.length">
                  <v-divider class="my-2" />
                  <div class="text-caption">
                    <div
                      v-for="ev in selectedNodeDetail.events.slice(-8)"
                      :key="ev.event_id"
                      class="py-0.5"
                    >
                      <v-icon size="x-small" :color="statusColor(ev.status)">
                        mdi-circle-slice-8
                      </v-icon>
                      {{ ev.kind }} {{ nodeStatusText(ev.status) }}
                      <span v-if="(ev.attempt ?? 0) > 0" class="text-medium-emphasis">
                        #{{ ev.attempt }}</span>
                      <span v-if="ev.instance_key" class="text-medium-emphasis">
                        [{{ ev.instance_key }}]</span>
                      <span v-if="ev.reason_code" class="text-medium-emphasis">
                        {{ ev.reason_code }}</span>
                      <span v-if="ev.error_code" class="text-error">
                        {{ ev.error_code }}</span>
                      <span v-if="ev.summary" class="text-medium-emphasis">
                        {{ ev.summary }}</span>
                    </div>
                  </div>
                </template>
                <template v-if="selectedNodeDetail?.metrics?.length">
                  <v-divider class="my-2" />
                  <pre class="flow-metrics">{{ JSON.stringify(
                    showAllMetrics
                      ? selectedNodeDetail.metrics
                      : selectedNodeDetail.metrics[selectedNodeDetail.metrics.length - 1],
                    null, 1
                  ) }}</pre>
                  <v-btn
                    v-if="selectedNodeDetail.metrics.length > 1"
                    size="x-small"
                    variant="text"
                    class="px-0"
                    @click="showAllMetrics = !showAllMetrics"
                  >
                    {{ showAllMetrics
                      ? '只看最近一组'
                      : `展开全部 ${selectedNodeDetail.metrics.length} 组指标` }}
                  </v-btn>
                </template>
              </v-card-text>
            </v-card>
          </div>

          <!-- 播放控制 -->
          <v-card-text class="pt-2">
            <div class="d-flex align-center ga-2">
              <v-btn
                icon="mdi-skip-previous"
                size="x-small"
                variant="text"
                :disabled="!store.orderedEvents.length"
                @click="store.resetPlayback(); stopPlay()"
              />
              <v-btn
                :icon="playing ? 'mdi-pause' : 'mdi-play'"
                size="small"
                variant="tonal"
                :disabled="store.orderedEvents.length < 2"
                @click="togglePlay"
              />
              <!-- O10：播放速率 0.5x/1x/2x/4x（间隔 = 300ms / speed） -->
              <v-btn-toggle
                v-model="playbackSpeed"
                mandatory
                density="compact"
                variant="outlined"
                divided
              >
                <v-btn
                  v-for="s in SPEED_OPTIONS"
                  :key="s"
                  :value="s"
                  size="x-small"
                >
                  {{ s }}x
                </v-btn>
              </v-btn-toggle>
              <v-btn
                icon="mdi-chevron-right"
                size="x-small"
                variant="text"
                :disabled="store.playbackIndex >= store.orderedEvents.length - 1"
                @click="store.stepPlayback(1); stopPlay()"
              />
              <v-slider
                :model-value="store.playbackIndex"
                :min="-1"
                :max="Math.max(0, store.orderedEvents.length - 1)"
                :step="1"
                density="compact"
                hide-details
                :label="store.playbackIndex < 0 ? '实时' : '回放'"
                @update:model-value="(v: number | number[]) => { stopPlay(); store.setPlayback(Number(v)); }"
              />
              <v-chip size="x-small" label>
                {{ store.visibleEvents.length }} / {{ store.orderedEvents.length }} 事件
              </v-chip>
              <v-chip
                v-if="store.detail.persisted_events"
                size="x-small"
                label
                :color="store.eventsTruncated ? 'warning' : undefined"
                :title="`存储已提交 ${store.detail.persisted_events} 条事件；浏览器已加载 ${store.orderedEvents.length} 条——两者独立（修复计划 §6.6 R8）`"
              >
                已载 {{ store.orderedEvents.length }} / 存储 {{ store.detail.persisted_events }}
              </v-chip>
              <v-btn
                v-if="store.eventsTruncated"
                size="x-small"
                variant="tonal"
                color="warning"
                :loading="store.eventsLoading"
                @click="store.loadMoreEvents()"
              >
                继续加载事件（当前为部分加载）
              </v-btn>
            </div>
            <div v-if="currentEvent" class="text-caption text-medium-emphasis mt-1">
              {{ fmtTime(currentEvent.ts_utc) }} ·
              {{ store.nodeLabel(currentEvent.node_id) }} ·
              {{ currentEvent.kind }} {{ nodeStatusText(currentEvent.status) }}
              <template v-if="(currentEvent.attempt ?? 0) > 0">
                · 第 {{ currentEvent.attempt }} 次尝试</template>
              <template v-if="currentEvent.reason_code">
                （{{ currentEvent.reason_code }}）</template>
              <template v-if="currentEvent.error_code">
                [{{ currentEvent.error_code }}]</template>
              <template v-if="currentEvent.summary"> {{ currentEvent.summary }}</template>
            </div>
          </v-card-text>
        </template>
      </v-card>
    </v-col>
  </v-row>

  <!-- 对象履历（修复计划 §6.6 R7）：对象视角 ↔ 运行视角互查 -->
  <v-dialog v-model="entityDialog" max-width="640">
    <v-card>
      <v-card-title class="text-subtitle-1 d-flex align-center">
        对象履历
        <v-chip size="x-small" label class="ml-2">{{ entityHistoryKey }}</v-chip>
        <v-spacer />
        <v-btn icon="mdi-close" size="small" variant="text" @click="entityDialog = false" />
      </v-card-title>
      <v-card-text>
        <div
          v-for="(h, i) in entityHistory"
          :key="i"
          class="d-flex align-center ga-2 py-1 flex-wrap"
          style="border-bottom: 1px solid rgba(128,128,128,.15)"
        >
          <span class="text-caption">{{ fmtTime(String(h.ts_utc ?? '')) }}</span>
          <v-chip size="x-small" label>{{ h.from_state || '∅' }} → {{ h.to_state || '∅' }}</v-chip>
          <v-spacer />
          <v-btn
            v-if="h.trace_id"
            size="x-small"
            variant="text"
            @click="entityDialog = false; openRelatedTrace(String(h.trace_id))"
          >
            打开运行 {{ String(h.trace_id).slice(0, 8) }}…
          </v-btn>
        </div>
        <div v-if="!entityHistory.length" class="text-caption text-medium-emphasis">
          该对象没有状态变化事实。
        </div>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.io-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
}
.io-cell {
  min-width: 0;
}
.io-text {
  font-size: 12px;
  line-height: 1.5;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(var(--v-theme-on-surface), 0.06);
  overflow-wrap: anywhere;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.flow-list {
  max-height: 560px;
  overflow-y: auto;
}
.flow-canvas {
  position: relative;
  overflow: auto;
  max-height: 560px;
  background:
    radial-gradient(rgba(var(--v-theme-on-surface), 0.05) 1px, transparent 1px);
  background-size: 22px 22px;
}
.flow-card {
  position: absolute;
  width: 380px;
  max-width: calc(100% - 16px);
  max-height: 460px;
  overflow-y: auto;
  z-index: 10;
}
.flow-card :deep(.text-caption),
.flow-card :deep(.text-body-2),
.flow-card :deep(.text-subtitle-2) {
  overflow-wrap: anywhere;
  word-break: break-word;
  white-space: normal;
}
.flow-relation-chip {
  cursor: pointer;
}
.lane-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: none;
}
.flow-node-pos {
  transition: transform 0.45s cubic-bezier(0.4, 0, 0.2, 1);
}
.flow-edge {
  fill: none;
  stroke: rgba(var(--v-theme-on-surface), 0.35);
  stroke-width: 1.2;
  transition: opacity 0.25s ease, stroke 0.4s ease;
}
.flow-edge.morph {
  opacity: 0.06;
}
.edge-spawn,
.edge-cause {
  stroke-dasharray: 4 3;
  stroke: rgba(var(--v-theme-on-surface), 0.28);
}
.edge-condition {
  stroke: rgba(var(--v-theme-primary), 0.45);
}
.flow-edge.dim {
  opacity: 0.15;
}
/* O05：实际视图里没有真实 transition 事实的边——虚线淡显，不冒充走过 */
.flow-edge.untaken {
  stroke-dasharray: 3 3;
  opacity: 0.25;
}
.flow-edge.active {
  stroke: rgba(var(--v-theme-primary), 0.9);
  stroke-width: 1.8;
}
.flow-edge.gone {
  opacity: 0;
}
.flow-node {
  cursor: pointer;
  outline: none;
  transform-box: fill-box;
  transform-origin: center;
  transition: opacity 0.4s ease;
}
.flow-node:focus rect,
.flow-node.selected rect {
  stroke: rgb(var(--v-theme-primary));
  stroke-width: 2;
}
.flow-node.unexecuted rect {
  stroke-dasharray: 3 2;
}
.flow-node-label {
  font-size: 11px;
  text-anchor: middle;
  fill: #fff;
  paint-order: stroke;
}
.flow-node.unexecuted .flow-node-label {
  fill: rgba(var(--v-theme-on-surface), 0.75);
}
.flow-node-status {
  font-size: 9px;
  text-anchor: middle;
  fill: rgba(255, 255, 255, 0.85);
}
.flow-node.unexecuted .flow-node-status {
  fill: rgba(var(--v-theme-on-surface), 0.55);
}
.flow-anchor-label {
  font-size: 12px;
  font-weight: 600;
  text-anchor: middle;
  fill: #fff;
}
.flow-node.pulse rect {
  animation: flow-pulse 1.2s ease-in-out infinite;
}
.reduce-motion .flow-node.pulse rect {
  animation: none;
}
.reduce-motion .flow-node,
.reduce-motion .flow-node-pos,
.reduce-motion .flow-edge {
  transition: none;
}
@keyframes flow-pulse {
  0%, 100% { opacity: 0.85; }
  50% { opacity: 0.55; }
}
.flow-metrics {
  font-size: 10px;
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-radius: 6px;
  padding: 6px;
  max-height: 140px;
  overflow: auto;
}
</style>
