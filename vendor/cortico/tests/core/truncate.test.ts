import { describe, expect, it } from 'vitest';
import type { ChatMessage } from './fixture-types.ts';

import {
  closeDanglingCalls,
  FOLD_ARGS_PLACEHOLDER,
  FOLD_PLACEHOLDER,
  rebuildTail,
  validatePairing,
} from "./fixture-truncate.ts";

function assistant(
  calls: Array<[string, string] | [string, string, string]> = [],
  content = '',
): ChatMessage {
  return {
    role: 'assistant',
    content,
    tool_calls: calls.length > 0
      ? calls.map(([name, id, args]) => ({
        id,
        type: 'function' as const,
        function: { name, arguments: args ?? '{}' },
      }))
      : undefined,
  };
}

function tool(id: string, content: string): ChatMessage {
  return { role: 'tool', tool_call_id: id, content };
}

describe('rebuildTail user回合截断', () => {
  it('空tail保持为空，不制造协议消息', () => {
    expect(rebuildTail([], 100)).toEqual([]);
  });

  it('预算裁剪对齐到最近可保留的user回合', () => {
    const tail: ChatMessage[] = [
      { role: 'user', content: `旧事件${'旧'.repeat(117)}` },
      assistant([], '旧回答'),
      { role: 'user', content: '新事件' },
      assistant([], '新回答'),
    ];
    const out = rebuildTail(tail, 100);
    expect(out.map((message) => message.content)).toEqual(['新事件', '新回答']);
    expect(out[0].role).toBe('user');
  });

  // 单条消息超出整份预算时省略该条，继续保留更早的轮次。
  it('单条超掉整份预算时,它之前的轮次仍保留', () => {
    const tail: ChatMessage[] = [
      { role: 'user', content: `旧事件${'旧'.repeat(2000)}` },
      assistant([], '旧回答'),
      { role: 'user', content: '新事件' },
      assistant([], '新回答'),
    ];
    const out = rebuildTail(tail, 100);
    expect(out.map((message) => message.content))
      .toEqual(['[turn too long, omitted]', '旧回答', '新事件', '新回答']);
  });

  it('折叠已知的大工具结果，但不折叠user事件', () => {
    const long = '长'.repeat(700);
    const out = rebuildTail([
      { role: 'user', content: long },
      assistant([['qq_read_history', 'r1']]),
      tool('r1', long),
      assistant([], '完成'),
    ], 10_000);
    expect(out[0].content).toBe(long);
    expect(out.find((message) => message.tool_call_id === 'r1')?.content)
      .toBe(FOLD_PLACEHOLDER);
    expect(validatePairing(out)).toEqual([]);
  });

  it('裁剪产生的开头孤儿tool会被丢弃', () => {
    const out = rebuildTail([
      tool('missing', '孤儿'),
      { role: 'user', content: '真正起点' },
      assistant([], '好'),
    ], 10_000);
    expect(out.some((message) => message.role === 'tool')).toBe(false);
    expect(out[0]).toMatchObject({ role: 'user', content: '真正起点' });
  });

  it('在user/assistant边界和尾部补齐悬空调用', () => {
    const out = rebuildTail([
      { role: 'user', content: '事件一' },
      assistant([['send', 's1'], ['read', 'r1']]),
      tool('s1', 'sent'),
      { role: 'user', content: '事件二' },
      assistant([['write', 'w1']]),
    ], 10_000);

    expect(out.find((message) => message.tool_call_id === 'r1')?.content)
      .toBe('[result missing]');
    expect(out.find((message) => message.tool_call_id === 'w1')?.content)
      .toBe('[result missing]');
    expect(validatePairing(out)).toEqual([]);
  });

  // 事件折叠须先于历史预算边界计算。
  it("先折叠工具结果，再按预算保留历史", () => {
    const tail: ChatMessage[] = [];
    for (let i = 0; i < 10; i++) {
      tail.push({ role: 'user', content: `早先第${i}轮` }, assistant([], `答${i}`));
    }
    tail.push(assistant([['external_event_frame', 'big']]));
    tail.push(tool('big', '弹'.repeat(200_000)));
    for (let i = 0; i < 7; i++) {
      tail.push({ role: 'user', content: `之后第${i}轮` }, assistant([], `回${i}`));
    }

    const out = rebuildTail(tail, 30_000);
    expect(out.find((m) => m.tool_call_id === 'big')?.content).toBe(FOLD_PLACEHOLDER);
    expect(out.length).toBeGreaterThanOrEqual(17);
    expect(JSON.stringify(out)).toContain('早先第0轮');
    expect(validatePairing(out)).toEqual([]);
  });

  // tool_calls[].function.arguments 也参与 token 预算，折叠须覆盖该字段。
  it('超阈值的工具入参也折叠,工具名与 call_id 原样保留', () => {
    const tail: ChatMessage[] = [];
    for (let i = 0; i < 10; i++) {
      tail.push({ role: 'user', content: `早先第${i}轮` }, assistant([], `答${i}`));
    }
    tail.push(assistant([
      ['write_file', 'w1', JSON.stringify({ path: 'a.md', text: '文'.repeat(30_000) })],
      ['end_turn', 'e1'],
    ]));
    tail.push(tool('w1', '已写入'), tool('e1', 'ok'));
    tail.push({ role: 'user', content: '最新一条' });

    const out = rebuildTail(tail, 30_000);
    const big = out.find((m) => m.tool_calls?.some((c) => c.id === 'w1'))!;
    const write = big.tool_calls!.find((c) => c.id === 'w1')!;
    expect(write.function.name).toBe('write_file');
    expect(write.function.arguments).toBe(FOLD_ARGS_PLACEHOLDER);
    // 未超过阈值的调用保持原文。
    expect(big.tool_calls!.find((c) => c.id === 'e1')!.function.arguments).toBe('{}');
    expect(JSON.stringify(out)).not.toContain('文文文');
    expect(JSON.stringify(out)).toContain('早先第0轮');
    expect(validatePairing(out)).toEqual([]);
  });

  it('入参没超阈值时一个字都不动', () => {
    const src: ChatMessage[] = [
      { role: 'user', content: '一' },
      assistant([['end_turn', 'e1']], '答'),
      tool('e1', 'ok'),
      { role: 'user', content: '二' },
    ];
    const out = rebuildTail(src, 30_000);
    expect(out).toStrictEqual(src);
  });

  it("折叠后仍超限的单条被省略，继续保留更早历史", () => {
    const tail: ChatMessage[] = [];
    for (let i = 0; i < 6; i++) {
      tail.push({ role: 'user', content: `早先第${i}轮` }, assistant([], `答${i}`));
    }
    // user 事件不折叠:一条就超掉整份预算
    tail.push({ role: 'user', content: '弹'.repeat(200_000) });
    tail.push(assistant([], '看不完'));
    tail.push({ role: 'user', content: '最新一条' });

    const out = rebuildTail(tail, 30_000);
    expect(out.length).toBeGreaterThanOrEqual(10);
    expect(JSON.stringify(out)).toContain('早先第0轮');
    expect(out.some((m) => m.content.includes('[turn too long, omitted]'))).toBe(true);
    expect(out.at(-1)?.content).toBe('最新一条');
  });

  it('validatePairing拒绝孤儿结果、跨边界悬空与尾部悬空', () => {
    expect(validatePairing([tool('x', 'orphan')])).toHaveLength(1);
    expect(validatePairing([
      assistant([['send', 's1']]),
      { role: 'user', content: '提前出现' },
    ])).toHaveLength(1);
    expect(validatePairing([assistant([['send', 's1']])])).toHaveLength(1);
    expect(validatePairing([
      assistant([['send', 's1']]),
      tool('s1', 'ok'),
      { role: 'user', content: '下一轮' },
      assistant([], 'done'),
    ])).toEqual([]);
  });
});

describe('closeDanglingCalls', () => {
  it('补齐尾部assistant声明的全部调用', () => {
    const messages = [
      { role: 'user', content: '事件' } as ChatMessage,
      assistant([['fork', 'f1'], ['schedule_wake', 'w1']]),
    ];
    const out = closeDanglingCalls(messages);
    expect(out.slice(-2).map((message) => message.tool_call_id)).toEqual(['f1', 'w1']);
    expect(validatePairing(out)).toEqual([]);
  });

  it('没有悬空调用时保留原条目', () => {
    const messages: ChatMessage[] = [{ role: 'user', content: '事件' }];
    expect(closeDanglingCalls(messages)).toEqual(messages);
    expect(closeDanglingCalls([])).toEqual([]);
  });
});
