import type { FlowEvent } from '@/api/flow';
import {
  dedupeAndOrder,
  fallbackNodeLabel,
  fitNodeText,
  projectNode,
  projectNodes,
} from '@/stores/flowReducer';
import { describe, expect, it } from 'vitest';

// 消息流程投影 reducer 合同（计划 §8.1 Dashboard reducer tests）：
// 去重/排序/「最近事件定状态」/start 无 finish 不伪装成功。

function ev(over: Partial<FlowEvent> & { event_id: string }): FlowEvent {
  return {
    row_id: 0,
    span_id: '',
    parent_span_id: '',
    node_id: 'n',
    instance_key: '',
    seq: 0,
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

describe('dedupeAndOrder', () => {
  it('dedupes by event_id and orders by row_id', () => {
    const out = dedupeAndOrder([
      ev({ event_id: 'b', row_id: 3 }),
      ev({ event_id: 'a', row_id: 2 }),
      ev({ event_id: 'b', row_id: 3 }),
      ev({ event_id: 'c', row_id: 1 }),
    ]);
    expect(out.map((e) => e.event_id)).toEqual(['c', 'a', 'b']);
  });

  it('keeps insertion-order duplicates when row_id ties are stable', () => {
    const out = dedupeAndOrder([
      ev({ event_id: 'a', row_id: 1 }),
      ev({ event_id: 'b', row_id: 1 }),
    ]);
    expect(out).toHaveLength(2);
  });
});

describe('projectNode', () => {
  it('start without finish stays running, never succeeded', () => {
    const node = projectNode('x', [
      ev({ event_id: '1', kind: 'start', status: 'running' }),
    ], '节点');
    expect(node.status).toBe('running');
  });

  it('no events at all is not_observed', () => {
    expect(projectNode('x', [], '节点').status).toBe('not_observed');
  });

  it('latest finish wins; last descriptive outcome stays visible', () => {
    const node = projectNode('x', [
      ev({ event_id: '1', kind: 'start', status: 'running' }),
      ev({ event_id: '2', kind: 'finish', status: 'failed',
           reason_code: 'provider_error' }),
      ev({ event_id: '3', kind: 'finish', status: 'succeeded' }),
    ], '节点');
    expect(node.status).toBe('succeeded');
    // 成功 finish 不携带 reason：保留最近一次有信息量的事实，不清洗成空
    expect(node.businessOutcome).toBe('provider_error');
  });

  it('decision carries reason_code as business outcome', () => {
    const node = projectNode('x', [
      ev({ event_id: '1', kind: 'decision', status: 'blocked',
           reason_code: 'pause_all' }),
    ], '预算');
    expect(node.status).toBe('blocked');
    expect(node.businessOutcome).toBe('pause_all');
  });

  it('checkpoint implies succeeded with summary outcome', () => {
    const node = projectNode('x', [
      ev({ event_id: '1', kind: 'checkpoint', status: 'succeeded',
           summary: 'spawned, not awaited' }),
    ], '触发');
    expect(node.status).toBe('succeeded');
    expect(node.businessOutcome).toBe('spawned, not awaited');
  });

  it('counts distinct instances (multi-segment / retries)', () => {
    const node = projectNode('x', [
      ev({ event_id: '1', kind: 'start', instance_key: 'seg:0' }),
      ev({ event_id: '2', kind: 'finish', instance_key: 'seg:0' }),
      ev({ event_id: '3', kind: 'start', instance_key: 'seg:1' }),
      ev({ event_id: '4', kind: 'finish', instance_key: 'seg:1' }),
    ], '发送');
    expect(node.instances).toBe(2);
  });

  it('keeps the last non-null duration', () => {
    const node = projectNode('x', [
      ev({ event_id: '1', kind: 'start' }),
      ev({ event_id: '2', kind: 'finish', duration_ms: 12.3 }),
      ev({ event_id: '3', kind: 'finish', duration_ms: 40 }),
    ], '节点');
    expect(node.durationMs).toBe(40);
  });
});

describe('projectNodes', () => {
  it('groups by node and sorts by first occurrence (seq)', () => {
    const nodes = projectNodes([
      ev({ event_id: '1', node_id: 'b', seq: 2 }),
      ev({ event_id: '2', node_id: 'a', seq: 1 }),
    ], (id) => id.toUpperCase());
    expect(nodes.map((n) => n.nodeId)).toEqual(['a', 'b']);
    expect(nodes[0].label).toBe('A');
  });
});

describe('fallbackNodeLabel', () => {
  it('explains custom extension hooks and passes through the rest', () => {
    expect(fallbackNodeLabel('hook.custom:my_hook')).toBe('扩展钩子 my_hook');
    expect(fallbackNodeLabel('chat.group_lock')).toBe('chat.group_lock');
  });
});

describe('fitNodeText', () => {
  it('keeps text that fits the node box', () => {
    expect(fitNodeText('群锁排队', 13)).toBe('群锁排队');
  });

  it('truncates overflowing text with an ellipsis', () => {
    const out = fitNodeText('回复闸门评估评估评估评估评估', 6);
    expect(out.endsWith('…')).toBe(true);
    expect(out.length).toBeLessThan(7);
  });

  it('counts CJK full-width and latin half-width', () => {
    // 13 全宽额度：17 个半宽字符（≈9.35）放得下
    expect(fitNodeText('abcdefghijklmnopq', 13)).toBe('abcdefghijklmnopq');
    // 6 全宽 + 6 半宽 ≈ 9.3 > 9 → 截断
    expect(fitNodeText('回复闸门评估abcdef', 9)).not.toBe('回复闸门评估abcdef');
  });
});
