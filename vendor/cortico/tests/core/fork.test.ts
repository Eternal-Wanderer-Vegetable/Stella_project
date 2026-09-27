import { FixtureClient } from './fixture-protocol.ts';
/** runForkLoop 的软提醒与硬轮数上限。 */
import { describe, expect, it } from 'vitest';
import { runForkLoop } from "./fixture-fork.ts";
import { nullLogger } from '../../src/core/util.ts';
import type { ChatMessage, LLMChatOptions, LLMResult } from './fixture-types.ts';
import type { ModelSpec, ToolDef, ToolSchema } from '../../src/core/types.ts';

const SPEC: ModelSpec = { model: 'test', thinking: false };

/** 每轮都调一次工具,直到 stopAfter 轮之后改说结论 */
class ScriptedLLM implements FixtureClient {
  round = 0;
  seen: ChatMessage[][] = [];
  constructor(private readonly toolRounds: number) {}
  async chat(_spec: ModelSpec, messages: ChatMessage[], _tools?: ToolSchema[], _opts?: LLMChatOptions): Promise<LLMResult> {
    this.seen.push(messages.map((m) => ({ ...m })));
    this.round++;
    const usage = { promptTokens: 0, completionTokens: 0, cacheHitTokens: 0, cacheMissTokens: 0 };
    if (this.round > this.toolRounds) {
      return { message: { role: 'assistant', content: '整理完了' }, usage };
    }
    return {
      message: {
        role: 'assistant',
        content: `第 ${this.round} 轮在干活`,
        tool_calls: [{ id: `c${this.round}`, type: 'function', function: { name: 'touch', arguments: '{}' } }],
      },
      usage,
    };
  }
}

const touch: ToolDef = {
  name: 'touch',
  description: 'test',
  tags: [],
  parameters: { type: 'object', properties: {}, required: [] },
  handler: async () => 'ok',
};

function toolTexts(seen: ChatMessage[][]): string[] {
  const last = seen[seen.length - 1];
  return last.filter((m) => m.role === 'tool').map((m) => m.content);
}

describe('runForkLoop 回合契约', () => {
  it("收尾提醒出现在声明的 soft 轮", async () => {
    const llm = new ScriptedLLM(10);
    await runForkLoop({
      id: 'dream',
      llm,
      spec: SPEC,
      messages: [{ role: 'user', content: '开始' }],
      tools: [touch],
      maxRounds: 8,
      softRounds: 3,
      log: nullLogger(),
      wrapUpHint: 'WRAP',
    });
    // 第 3 轮的工具回执带提醒,第 1/2/4 轮不带
    const hinted = toolTexts(llm.seen).map((t) => t.includes('WRAP'));
    expect(hinted.slice(0, 5)).toEqual([false, false, true, false, false]);
  });

  it("未指定 soft 时在 maxRounds-1 轮提醒", async () => {
    const llm = new ScriptedLLM(10);
    await runForkLoop({
      id: 'dream',
      llm,
      spec: SPEC,
      messages: [{ role: 'user', content: '开始' }],
      tools: [touch],
      maxRounds: 4,
      log: nullLogger(),
      wrapUpHint: 'WRAP',
    });
    // 最后一次请求带的是前 3 轮的回执:提醒落在第 3 轮(maxRounds-1)
    const hinted = toolTexts(llm.seen).map((t) => t.includes('WRAP'));
    expect(hinted).toEqual([false, false, true]);
  });

  it("达到硬轮数上限时在返回正文中加入 capNote", async () => {
    const llm = new ScriptedLLM(99);
    const out = await runForkLoop({
      id: 'dream',
      llm,
      spec: SPEC,
      messages: [{ role: 'user', content: '开始' }],
      tools: [touch],
      maxRounds: 3,
      log: nullLogger(),
      capNote: '(没做完:轮数用满被收线了)',
    });
    expect(out).toContain('第 3 轮在干活');
    expect(out).toContain('没做完');
  });

  it('自然收尾不加 capNote', async () => {
    const llm = new ScriptedLLM(1);
    const out = await runForkLoop({
      id: 'dream',
      llm,
      spec: SPEC,
      messages: [{ role: 'user', content: '开始' }],
      tools: [touch],
      maxRounds: 5,
      log: nullLogger(),
      capNote: '(没做完:轮数用满被收线了)',
    });
    expect(out).toBe('整理完了');
  });

  it("一轮中的多个工具调用逐个执行并按序配对", async () => {
    const calls: string[] = [];
    const many: FixtureClient = {
      async chat(_s, _m, _t, _o): Promise<LLMResult> {
        const usage = { promptTokens: 0, completionTokens: 0, cacheHitTokens: 0, cacheMissTokens: 0 };
        if (calls.length > 0) return { message: { role: 'assistant', content: '好了' }, usage };
        return {
          message: {
            role: 'assistant',
            content: '一次读齐',
            tool_calls: [
              { id: 'a', type: 'function', function: { name: 'touch', arguments: '{"n":1}' } },
              { id: 'b', type: 'function', function: { name: 'touch', arguments: '{"n":2}' } },
              { id: 'c', type: 'function', function: { name: 'touch', arguments: '{"n":3}' } },
            ],
          },
          usage,
        };
      },
    };
    await runForkLoop({
      id: 'dream',
      llm: many,
      spec: SPEC,
      messages: [{ role: 'user', content: '开始' }],
      tools: [{ ...touch, handler: async (args) => { calls.push(String(args.n)); return `ok${String(args.n)}`; } }],
      maxRounds: 5,
      log: nullLogger(),
    });
    expect(calls).toEqual(['1', '2', '3']);
  });
});
