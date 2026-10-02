<script setup lang="ts">
// 消息流程页（计划 §6.7）：左侧消息筛选 / 中央分层画布 / 浮动节点详情卡。
// 默认画「完整流程」——目录里每个节点都在，执行过的着色、没走过的灰色
// not_observed（计划 §6.4：未经过的可能路径灰色显示，绝不自动标 skipped）。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import type { FlowEvent, FlowMessageSummary } from '@/api/flow';
import { useFlowStore } from '@/stores/flow';
import {
  CANVAS_PAD,
  edgePath,
  layoutFlow,
  layoutFull,
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

const NODE_W = 128;
const NODE_H = 40;
const CARD_W = 320;

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const playing = ref(false);
let playTimer: ReturnType<typeof setInterval> | null = null;

// 'full' = 完整流程（目录全节点，默认）；'executed' = 只看实际发生的
const viewMode = ref<'full' | 'executed'>('full');
const canvasEl = ref<HTMLElement | null>(null);
// 浮动详情卡：锚在节点点击位置（相对画布容器）
const card = ref<{ nodeId: string; x: number; y: number } | null>(null);

onMounted(() => {
  void store.loadMessages();
});

onBeforeUnmount(() => {
  store.stopStream();
  stopPlay();
});

const laneOrder = computed<string[]>(() => {
  if (store.spec?.lanes?.length) {
    return store.spec.lanes.map(([id]) => id);
  }
  return [...new Set(store.nodeStates.map((n) => store.nodeLane(n.nodeId)))];
});

const laneLabels = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {};
  for (const [id, label] of store.spec?.lanes ?? []) out[id] = label;
  out.other = '其他';
  return out;
});

/** 实际路径模式：只画发生过事件的节点（泳道为行、执行顺序为列）。 */
const executedLayout = computed(() =>
  layoutFlow({
    nodeStates: store.nodeStates,
    laneOf: (nodeId: string) => store.nodeLane(nodeId),
    laneOrder: laneOrder.value,
    specEdges: store.spec?.edges ?? [],
    specNodes: store.specNodeById.size
      ? Object.fromEntries(store.specNodeById)
      : undefined,
  }),
);

/** 完整流程模式：目录全节点 + 执行状态叠加（默认视图）。 */
const fullLayout = computed(() => {
  if (!store.spec) return null;
  return layoutFull({
    spec: store.spec,
    executed: store.executedNodeMap,
    labelOf: (nodeId: string) => store.nodeLabel(nodeId),
    laneOf: (nodeId: string) => store.nodeLane(nodeId),
  });
});

const layout = computed(() =>
  viewMode.value === 'full' ? fullLayout.value : executedLayout.value,
);
const laidNodes = computed<LaidNode[]>(() => layout.value?.nodes ?? []);
const laidEdges = computed<LaidEdge[]>(() => layout.value?.edges ?? []);
const canvasSize = computed(() => ({
  w: layout.value?.width ?? CANVAS_PAD,
  h: layout.value?.height ?? CANVAS_PAD,
}));

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

const completenessText = computed(() => {
  const d = store.detail;
  if (!d) return '';
  if (d.loss) return '有已知丢失（known loss）';
  if (d.status === 'interrupted') return '进程中断，未闭合（partial）';
  if (!d.complete) return '不完整（partial）';
  return '完整';
});

const rootKindLabel = (item: FlowMessageSummary) =>
  ROOT_KIND_LABELS[item.root_kind] ?? item.root_kind;

const outcomeLabel = (outcome: string) => OUTCOME_LABELS[outcome] ?? outcome;

const fmtTime = (iso: string) => (iso ? iso.replace('T', ' ').slice(0, 19) : '—');

function pick(item: FlowMessageSummary) {
  closeCard();
  playing.value = false;
  stopPlay();
  void store.openTrace(item.trace_id).then(() => {
    void store.loadSpec();
    if (item.status === 'interrupted') return;
    void store.startStream();
  });
}

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.unknown;
}

function onNodeClick(node: LaidNode, event: MouseEvent) {
  store.selectNode(node.nodeId);
  const rect = canvasEl.value?.getBoundingClientRect();
  const clickX = event.clientX - (rect?.left ?? 0);
  const clickY = event.clientY - (rect?.top ?? 0);
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
  // 布局切换后节点位置全变，浮动卡锚点失效：直接关掉
  closeCard();
});

function togglePlay() {
  if (playing.value) {
    stopPlay();
    return;
  }
  if (store.playbackIndex < 0) store.setPlayback(0);
  playing.value = true;
  playTimer = setInterval(() => {
    if (store.playbackIndex >= store.orderedEvents.length - 1) {
      stopPlay();
      return;
    }
    store.stepPlayback(1);
  }, reducedMotion ? 0 : 300);
  if (reducedMotion) {
    stopPlay();
  }
}

function stopPlay() {
  playing.value = false;
  if (playTimer) {
    clearInterval(playTimer);
    playTimer = null;
  }
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
                :icon="item.status === 'closed' ? 'mdi-check-circle' : 'mdi-alert-circle'"
                :color="item.complete ? 'success' : 'warning'"
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
        </v-list>
      </v-card>
    </v-col>

    <!-- 中：画布 + 播放 -->
    <v-col cols="12" md="9">
      <v-card variant="flat" :elevation="1">
        <v-card-text v-if="!store.detail" class="text-medium-emphasis">
          选择左侧一条消息，查看它从进入到结束经过的完整处理流程（灰色节点是本次没有走到的路径）。
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
            <v-chip v-if="store.spec" size="x-small" label>
              图版本 {{ store.spec.topology_version }}
            </v-chip>
            <v-chip v-else size="x-small" label color="warning">
              拓扑版本缺失（unmapped）
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
            <v-btn size="x-small" variant="text" @click="store.fetchEvents()">
              刷新
            </v-btn>
          </v-card-text>

          <!-- 关联轨迹（trace 间因果，独立于画布节点） -->
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
            >
              <v-icon start size="x-small">mdi-link-variant</v-icon>
              {{ rel.direction === 'out' ? '派生' : '触发自' }}
              {{ rel.trace_id.slice(0, 8) }}…
              <template v-if="rel.evidence">（{{ rel.evidence }}）</template>
            </v-chip>
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
              aria-label="消息处理流程图"
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
              <!-- 泳道背景与标签 -->
              <g>
                <rect
                  v-for="(lane, idx) in laneOrder"
                  :key="lane"
                  x="0"
                  :y="CANVAS_PAD - 20 + idx * (NODE_H + 72)"
                  :width="canvasSize.w"
                  :height="NODE_H + 40"
                  class="flow-lane-bg"
                  :class="{ alt: idx % 2 === 1 }"
                />
                <text
                  v-for="(lane, idx) in laneOrder"
                  :key="`label-${lane}`"
                  :x="4"
                  :y="CANVAS_PAD - 6 + idx * (NODE_H + 72)"
                  class="flow-lane-label"
                >
                  {{ laneLabels[lane] ?? lane }}
                </text>
              </g>
              <!-- 边 -->
              <g>
                <path
                  v-for="e in laidEdges"
                  :key="e.id"
                  :d="edgePath(e.from, e.to)"
                  class="flow-edge"
                  :class="[`edge-${e.kind}`, {
                    active: e.active,
                    dim: viewMode === 'full' && !e.active,
                  }]"
                  marker-end="url(#flow-arrow)"
                />
              </g>
              <!-- 节点 -->
              <g
                v-for="n in laidNodes"
                :key="n.nodeId"
                :transform="`translate(${n.x}, ${n.y})`"
                class="flow-node"
                :class="{
                  selected: n.nodeId === card?.nodeId,
                  pulse: n.status === 'running' && !reducedMotion,
                  unexecuted: n.status === 'not_observed',
                }"
                role="button"
                tabindex="0"
                @click.stop="onNodeClick(n, $event)"
                @keydown.enter="store.selectNode(n.nodeId)"
              >
                <rect
                  :width="NODE_W"
                  :height="NODE_H"
                  rx="8"
                  :fill="statusColor(n.status)"
                  :opacity="n.status === 'not_observed' ? 0.35 : 0.85"
                />
                <text :x="NODE_W / 2" :y="17" class="flow-node-label">
                  {{ n.label }}
                </text>
                <text :x="NODE_W / 2" :y="31" class="flow-node-status">
                  {{ n.status === 'not_observed' ? '未走到' : n.status }}<template v-if="n.instances > 1"> ×{{ n.instances }}</template>
                </text>
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
                  <span class="text-subtitle-2">{{ selectedNode.label }}</span>
                  <v-chip
                    size="x-small"
                    label
                    :color="statusColor(selectedNode.status)"
                  >
                    {{ selectedNode.status === 'not_observed' ? '未走到' : selectedNode.status }}
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
                  <template v-if="selectedNode.spec?.opaque"> · 外部边界（opaque）</template>
                  <template v-if="selectedNode.spec?.derived"> · 派生节点</template>
                  <template v-if="selectedNode.spec">
                    · {{ laneLabels[selectedNode.lane] ?? selectedNode.lane }}
                  </template>
                </div>
                <div v-if="selectedNode.outcome" class="text-body-2 mb-1">
                  事实：{{ selectedNode.outcome }}
                </div>
                <div v-if="selectedNodeDetail" class="text-caption mb-1">
                  实例 {{ selectedNode.instances }}
                  <template v-if="selectedNodeDetail.durationMs != null">
                    · 最近耗时 {{ selectedNodeDetail.durationMs.toFixed(1) }} ms
                  </template>
                </div>
                <div v-else class="text-caption text-medium-emphasis mb-1">
                  本次消息没有经过这个节点（无事实，不猜测原因）。
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
                      {{ ev.kind }} {{ ev.status }}
                      <span v-if="ev.instance_key" class="text-medium-emphasis">
                        [{{ ev.instance_key }}]</span>
                      <span v-if="ev.reason_code" class="text-medium-emphasis">
                        {{ ev.reason_code }}</span>
                      <span v-if="ev.summary" class="text-medium-emphasis">
                        {{ ev.summary }}</span>
                    </div>
                  </div>
                </template>
                <template v-if="selectedNodeDetail?.metrics?.length">
                  <v-divider class="my-2" />
                  <pre class="flow-metrics">{{ JSON.stringify(
                    selectedNodeDetail.metrics[selectedNodeDetail.metrics.length - 1],
                    null, 1
                  ) }}</pre>
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
            </div>
            <div v-if="currentEvent" class="text-caption text-medium-emphasis mt-1">
              {{ fmtTime(currentEvent.ts_utc) }} ·
              {{ store.nodeLabel(currentEvent.node_id) }} ·
              {{ currentEvent.kind }} {{ currentEvent.status }}
              <template v-if="currentEvent.reason_code">
                （{{ currentEvent.reason_code }}）</template>
              <template v-if="currentEvent.summary"> {{ currentEvent.summary }}</template>
            </div>
          </v-card-text>
        </template>
      </v-card>
    </v-col>
  </v-row>
</template>

<style scoped>
.flow-list {
  max-height: 560px;
  overflow-y: auto;
}
.flow-canvas {
  position: relative;
  overflow: auto;
  max-height: 560px;
}
.flow-card {
  position: absolute;
  width: 320px;
  max-height: 340px;
  overflow-y: auto;
  z-index: 10;
}
.flow-lane-bg {
  fill: transparent;
  stroke: rgba(var(--v-theme-on-surface), 0.06);
}
.flow-lane-bg.alt {
  fill: rgba(var(--v-theme-on-surface), 0.03);
}
.flow-lane-label {
  font-size: 10px;
  fill: rgba(var(--v-theme-on-surface), 0.45);
}
.flow-edge {
  fill: none;
  stroke: rgba(var(--v-theme-on-surface), 0.35);
  stroke-width: 1.2;
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
  opacity: 0.18;
}
.flow-edge.active {
  stroke: rgba(var(--v-theme-primary), 0.9);
  stroke-width: 1.8;
}
.flow-node {
  cursor: pointer;
  outline: none;
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
.flow-node.pulse rect {
  animation: flow-pulse 1.2s ease-in-out infinite;
}
.reduce-motion .flow-node.pulse rect {
  animation: none;
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
