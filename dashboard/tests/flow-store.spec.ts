import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';

import type { FlowEvent } from '@/api/flow';
import { useFlowStore } from '@/stores/flow';

// store 集成测试：去重合并、播放切片与钳位、spec 缺失回退标签。
// 不触网（openTrace/fetchEvents/startStream 由 webui API 测试与手动验证覆盖）。

function ev(over: Partial<FlowEvent> & { event_id: string; row_id: number }): FlowEvent {
  return {
    span_id: '',
    parent_span_id: '',
    node_id: 'n',
    instance_key: '',
    seq: over.row_id,
    kind: 'decision',
    status: 'succeeded',
    reason_code: '',
    ts_utc: '2026-10-02T00:00:00',
    duration_ms: null,
    summary: '',
    metrics: {},
    ...over,
  } as FlowEvent;
}

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('flow store', () => {
  it('mergeEvents dedupes by event_id and keeps row order', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 2, node_id: 'x' }),
      ev({ event_id: 'b', row_id: 1, node_id: 'y' }),
    ]);
    store.mergeEvents([ev({ event_id: 'a', row_id: 2, node_id: 'x' })]);
    expect(store.orderedEvents.map((e) => e.event_id)).toEqual(['b', 'a']);
  });

  it('playback slices visible events and clamps the index', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1 }),
      ev({ event_id: 'b', row_id: 2 }),
      ev({ event_id: 'c', row_id: 3 }),
    ]);
    store.setPlayback(1);
    expect(store.visibleEvents).toHaveLength(2);
    store.setPlayback(99);
    expect(store.playbackIndex).toBe(2);
    store.setPlayback(-5);
    expect(store.playbackIndex).toBe(-1); // 回到实时
    expect(store.visibleEvents).toHaveLength(3);
  });

  it('stepPlayback starts from the tail when live', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1 }),
      ev({ event_id: 'b', row_id: 2 }),
    ]);
    store.stepPlayback(-1);
    expect(store.playbackIndex).toBe(0);
    store.resetPlayback();
    store.stepPlayback(1);
    expect(store.playbackIndex).toBe(1);
  });

  it('node projection follows playback position', () => {
    const store = useFlowStore();
    store.mergeEvents([
      ev({ event_id: 'a', row_id: 1, node_id: 'gate', kind: 'decision',
           status: 'blocked', reason_code: 'pause_all' }),
      ev({ event_id: 'b', row_id: 2, node_id: 'gen', kind: 'start',
           status: 'running' }),
    ]);
    expect(store.nodeStates.map((n) => n.nodeId)).toEqual(['gate', 'gen']);
    store.setPlayback(0); // 只回放到第一个事件
    expect(store.nodeStates.map((n) => n.nodeId)).toEqual(['gate']);
    const gate = store.nodeStates[0];
    expect(gate.status).toBe('blocked');
    expect(gate.businessOutcome).toBe('pause_all');
  });

  it('unmapped nodes fall back to readable labels', () => {
    const store = useFlowStore();
    expect(store.nodeLabel('chat.group_lock')).toBe('chat.group_lock');
    expect(store.nodeLabel('hook.custom:ext')).toBe('扩展钩子 ext');
    expect(store.nodeLane('anything')).toBe('other');
  });

  it('selectNode tracks selection', () => {
    const store = useFlowStore();
    store.selectNode('send.segment');
    expect(store.selectedNodeId).toBe('send.segment');
  });
});
