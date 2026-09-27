// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
/**
 * [STELLA PATCH] fork turn-policy 单测（patches/turn-policy.patch 的一部分）。
 *
 * 验证 ForkOptions.turnPolicy 的通用语义：
 * - direct：不调用 provider，返回决策文本，session 无 assistant 记录；
 * - silent：不调用 provider，返回空串；
 * - generate / 未提供 policy：行为与上游完全一致。
 * 该文件随补丁维护；上游升级后由 `pnpm --dir node_runtime/cortico verify-patches`
 * 与本套件共同确认补丁仍然成立。
 */
import { describe, expect, it } from 'vitest';
import { Core } from '../../src/core/core.ts';
import { message } from '../../src/protocol/open-responses/context.ts';
import type { SessionDecl } from '../../src/core/types.ts';
import { makeCfg, makeFakePersona, makeLoaded, makeTmpDir, textReply, FakeLLM, type FakePersonaOptions } from './helpers.ts';

const turnDecl: SessionDecl = {
  id: 'turn',
  label: 'turn',
  rounds: () => ({ soft: 1, hard: 1, softHint: () => null }),
  persistent: false,
  receivesEvents: false,
  tools: () => [],
};

async function makeCore(llm: FakeLLM, personaOpts?: FakePersonaOptions) {
  const tmp = makeTmpDir();
  const core = new Core(
    makeLoaded({
      config: makeCfg(),
      rootDir: tmp.dir,
      memoryDir: `${tmp.dir}/persona`,
      dataDir: `${tmp.dir}/data`,
    }),
    { persona: makeFakePersona([], { ...personaOpts, extraSessions: [...(personaOpts?.extraSessions ?? []), turnDecl] }), worlds: [], llm },
  );
  await core.start();
  return {
    core,
    cleanup: async () => {
      await core.stop();
      tmp.cleanup();
    },
  };
}

describe('fork turnPolicy（STELLA PATCH）', () => {
  it('direct：provider 零调用，返回决策文本', async () => {
    const llm = new FakeLLM();
    llm.script(textReply('不应被消费'));
    const { core, cleanup } = await makeCore(llm);
    try {
      const text = await core.spawnFork({
        id: 'turn',
        messages: [message('user', '投影')],
        turnPolicy: () => ({ kind: 'direct', text: '固定文本' }),
      });
      expect(text).toBe('固定文本');
      expect(llm.calls.length).toBe(0);
    } finally {
      await cleanup();
    }
  });

  it('silent：provider 零调用，返回空串', async () => {
    const llm = new FakeLLM();
    llm.script(textReply('不应被消费'));
    const { core, cleanup } = await makeCore(llm);
    try {
      const text = await core.spawnFork({
        id: 'turn',
        messages: [message('user', '投影')],
        turnPolicy: () => ({ kind: 'silent' }),
      });
      expect(text).toBe('');
      expect(llm.calls.length).toBe(0);
    } finally {
      await cleanup();
    }
  });

  it('异步 policy 与 generate 缺省行为保持不变', async () => {
    const llm = new FakeLLM();
    llm.script(textReply('模型正文'));
    const { core, cleanup } = await makeCore(llm);
    try {
      const generated = await core.spawnFork({
        id: 'turn',
        messages: [message('user', '投影')],
        turnPolicy: async () => ({ kind: 'generate' }),
      });
      expect(generated).toBe('模型正文');
      expect(llm.calls.length).toBe(1);
    } finally {
      await cleanup();
    }
  });
});
