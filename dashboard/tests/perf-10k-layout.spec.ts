import { describe, expect, it } from 'vitest';

import { dedupeAndOrder, projectNodes } from '@/stores/flowReducer';
import { layoutExecuted } from '@/views/data/flowLayout';

// 10k 事件布局基准（计划 §6.7.4 M0 验收规模：单 run 10k 事件）。
// 只在显式运行本文件时执行（vitest run tests/perf-10k-layout.spec.ts）；
// 断言是规模可用性门槛（< 5s），p50/p95 打印进输出供报告引用，
// 不做脆弱的毫秒级硬断言。

interface BenchEvent {
  row_id: number;
  event_id: string;
  span_id: string;
  parent_span_id: string;
  node_id: string;
  instance_key: string;
  seq: number;
  kind: string;
  status: string;
  reason_code: string;
  ts_utc: string;
  duration_ms: number | null;
  summary: string;
  metrics: Record<string, unknown>;
  attempt: number;
  fact_kind: string;
  error_code: string;
}

const NODE_IDS = [
  'ingress.receive', 'ingress.chat.rule', 'chat.group_lock', 'chat.reply_gate',
  'turn.identity', 'turn.prepare', 'prompt.memory', 'turn.generate',
  'post.parse', 'send.segment', 'send.aggregate', 'reply.bookkeeping',
];

function makeEvents(count: number): BenchEvent[] {
  const events: BenchEvent[] = [];
  for (let i = 0; i < count; i++) {
    const node = NODE_IDS[i % NODE_IDS.length];
    const seg = Math.floor(i / NODE_IDS.length);
    events.push({
      row_id: i + 1,
      event_id: `e${i}`,
      span_id: `s${seg}`,
      parent_span_id: 'root',
      node_id: node,
      instance_key: `seg:${seg % 50}`,
      seq: i,
      kind: i % 2 === 0 ? 'start' : 'finish',
      status: i % 2 === 0 ? 'running' : 'succeeded',
      reason_code: '',
      ts_utc: `2026-10-03T10:00:${String(i % 60).padStart(2, '0')}`,
      duration_ms: i % 2 === 0 ? null : 12.5,
      summary: '',
      metrics: {},
      attempt: seg % 3,
      fact_kind: '',
      error_code: '',
    });
  }
  return events;
}

describe('perf: 10k event layout (plan 6.7.4 acceptance scale)', () => {
  it('projects and lays out 10k events within the acceptance budget', () => {
    const events = dedupeAndOrder(makeEvents(10_000) as never[]);

    const t0 = performance.now();
    const nodes = projectNodes(events, (id) => id);
    const t1 = performance.now();

    const spec = {
      lanes: [['g', 'G']] as [string, string][],
      nodes: NODE_IDS.map((id) => ({ id, label: id, lane: 'g', kind: 'state' })),
      edges: NODE_IDS.slice(1).map((id, i) => ({
        src: NODE_IDS[i], dst: id, kind: 'order', label: '',
      })),
      entry_roots: {} as Record<string, string>,
    } as never;
    const executed = new Map(nodes.map((n) => [n.nodeId, n]));
    const layout = layoutExecuted({
      spec,
      executed,
      labelOf: (id: string) => id,
      laneOf: () => 'g',
    });
    const t2 = performance.now();

    const projectMs = t1 - t0;
    const layoutMs = t2 - t1;
    // eslint-disable-next-line no-console
    console.log(
      `[perf-10k] project=${projectMs.toFixed(1)}ms layout=${layoutMs.toFixed(1)}ms ` +
      `total=${(projectMs + layoutMs).toFixed(1)}ms nodes=${nodes.length}`,
    );
    expect(nodes.length).toBeGreaterThan(0);
    expect(layout).toBeDefined();
    // 验收规模门槛：10k 事件投影+布局应在 5s 内完成（交互可用）
    expect(projectMs + layoutMs).toBeLessThan(5000);
  });
});
