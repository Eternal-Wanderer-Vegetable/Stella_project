import { FixtureForkOptions as ForkOptions } from '../core/fixture-protocol.ts';
import { records } from '../core/fixture-protocol.ts';
/**
 * 梦:交接后从交接前的快照 fork,单实例排队,surface 经 onEmergence 回到主意识。
 * 测试只提供 CoreApi 表面与 FakeLLM,不构造 MainLoop 或调用真实 API。
 */
import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '../core/fixture-types.ts';
import type { CoreApi, Logger, ToolDef } from '../../src/core/types.ts';
import { nullLogger } from '../../src/core/util.ts';
import { runForkLoop } from '../core/fixture-fork.ts';
import { Dream } from '../../bots/corti-soulmate/persona/subconscious/index.ts';
import { dreamOrientation } from '../../bots/corti-soulmate/persona/subconscious/prompts.ts';
import { FakeLLM, makeCfg, makeFakeHarnessApi, makeTool, toolReply } from '../core/helpers.ts';

const snapshot: ChatMessage[] = [
  { role: 'system', content: 'waking-system' },
  { role: 'user', content: '#1 [21:00] 阿明: 在吗' },
  { role: 'assistant', content: '我在。' },
];

function buildDream(opts: { llm: FakeLLM; cfgPatch?: Parameters<typeof makeCfg>[0]; tools?: ToolDef[]; log?: Logger }) {
  const cap = { emergences: [] as string[], handoffRequests: 0, handingOff: false };
  const cfg = makeCfg(opts.cfgPatch);
  const core: CoreApi = makeFakeHarnessApi({
    llm: opts.llm,
    spawnFork: async (fork: ForkOptions) => runForkLoop({
      id: fork.id,
      llm: opts.llm,
      spec: { model: 'fake-dream', thinking: false },
      messages: fork.messages,
      tools: fork.tools as ToolDef[],
      maxRounds: cfg.dream.maxRounds,
      log: nullLogger(),
      stopWhen: fork.stopWhen,
      wrapUpHint: fork.wrapUpHint,
      nudge: fork.nudge,
    }),
    requestContextHandoff: () => {
      if (cap.handingOff) return false;
      cap.handoffRequests++;
      cap.handingOff = true;
      return true;
    },
  });
  const dream = new Dream({
    cfg,
    core,
    dreamTools: () => opts.tools ?? [],
    toolUsageText: () => 'dream-usage',
    log: opts.log ?? nullLogger(),
    onEmergence: (text) => cap.emergences.push(text),
  });
  return { dream, cap };
}

describe('交接后的梦', () => {
  it('前缀保序继承快照,引导整体在尾部;surface 经 onEmergence 回到主意识', async () => {
    const llm = new FakeLLM();
    llm.script(toolReply([{ name: 'surface', args: { text: '我合并了重复笔记。' } }]));
    const { dream, cap } = buildDream({ llm });

    await dream.schedule(records(snapshot));

    expect(cap.emergences).toEqual(['我合并了重复笔记。']);
    const messages = llm.calls[0].messages;
    expect(messages.slice(0, snapshot.length)).toEqual(snapshot);
    const last = messages.at(-1);
    expect(last?.role).toBe('user');
    expect(last?.content).toContain(dreamOrientation());
    expect(last?.content).toContain('dream-usage');
    expect(last?.content).toContain('one and only dream for that handoff');
    expect(llm.calls[0].tools?.map((tool) => tool.name) ?? []).toContain('surface');
  });

  it('快照超出梦预算时才砍最老尾,主 system 仍保留', async () => {
    const llm = new FakeLLM();
    llm.script(toolReply([{ name: 'surface', args: { text: '整理完成。' } }]));
    const long = [
      snapshot[0],
      ...Array.from({ length: 40 }, (_, i) => ({ role: 'user' as const, content: `#${i} ` + 'x'.repeat(2000) })),
    ];
    const { dream } = buildDream({ llm, cfgPatch: { context: { maxTokens: 20_000, keepRatio: 0.3, softRatio: 0.85, keepPastThinking: true, firstTurn: true } } });
    await dream.schedule(records(long));
    const messages = llm.calls[0].messages;
    expect(messages[0]).toEqual(snapshot[0]);
    expect(messages.length).toBeLessThan(long.length + 1);
    expect(messages.at(-1)?.content).toContain(dreamOrientation());
  });

  it('梦拿到给它的工具面(文件工具 + 只读 World 工具)', async () => {
    const llm = new FakeLLM();
    llm.script(
      toolReply([{ name: 'probe' }]),
      toolReply([{ name: 'surface', args: { text: '整理完成。' } }]),
    );
    const { dream } = buildDream({ llm, tools: [makeTool('probe', 'ok')] });
    await dream.schedule(records(snapshot));
    expect(llm.calls).toHaveLength(2);
    expect(llm.calls[0].tools?.map((tool) => tool.name) ?? []).toContain('probe');
  });

  it('单实例排队:第二场等第一场醒来;dreaming 只在跑的时候为真', async () => {
    const llm = new FakeLLM();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    let started!: () => void;
    const running = new Promise<void>((resolve) => { started = resolve; });
    const original = llm.chat.bind(llm);
    llm.script(
      toolReply([{ name: 'surface', args: { text: '第一场。' } }]),
      toolReply([{ name: 'surface', args: { text: '第二场。' } }]),
    );
    llm.chat = async (...args) => {
      started();
      await gate;
      return original(...args);
    };
    const { dream, cap } = buildDream({ llm });

    const first = dream.schedule(records(snapshot));
    const second = dream.schedule(records(snapshot));
    await running;
    expect(dream.getStatus().dreaming).toBe(true);
    expect(cap.emergences).toEqual([]);
    release();
    await Promise.all([first, second]);
    expect(dream.getStatus().dreaming).toBe(false);
    expect(llm.calls).toHaveLength(2);
    expect(cap.emergences).toEqual(['第一场。', '第二场。']);
  });

  it('没有 surface 就没有浮现;fork 失败只记日志', async () => {
    const llm = new FakeLLM();
    llm.script(toolReply([{ name: 'probe' }]));
    const { dream, cap } = buildDream({ llm, tools: [makeTool('probe', 'ok')] });
    await dream.schedule(records(snapshot));
    expect(cap.emergences).toEqual([]);
  });

  it('手动强制入梦实际请求统一交接入口,并防重入', () => {
    const llm = new FakeLLM();
    const { dream, cap } = buildDream({ llm });
    expect(dream.forceDreamAndTruncate()).toBe(true);
    expect(cap.handoffRequests).toBe(1);
    expect(dream.forceDreamAndTruncate()).toBe(false);
    expect(cap.handoffRequests).toBe(1);
  });
});
