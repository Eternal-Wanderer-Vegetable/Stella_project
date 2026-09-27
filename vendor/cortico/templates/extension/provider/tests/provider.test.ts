import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { dryMountProvider } from 'cortico/extensions/dry-mount.ts';
import EXAMPLE from '../src/index.ts';
import { buildExampleRequestBody } from '../src/native.ts';

let scratchDir: string;
beforeEach(() => { scratchDir = mkdtempSync(join(tmpdir(), 'example-provider-')); });
afterEach(() => rmSync(scratchDir, { recursive: true, force: true }));

describe('Example provider', () => {
  it('干装载不报失败:装载器会接受它', () => {
    expect(dryMountProvider(EXAMPLE, { scratchDir }).failures).toEqual([]);
  });

  it('请求体带模型、消息与工具;采样参数只在给了时出现', () => {
    const body = buildExampleRequestBody(
      { model: 'm', thinking: false, temperature: 0.7 },
      [{ role: 'user', content: 'hi' }],
      [{ name: 'example_echo', description: 'echo', parameters: { type: 'object', properties: {} } }],
    );
    expect(body.model).toBe('m');
    expect(body.temperature).toBe(0.7);
    expect(body.max_tokens).toBeUndefined();
    expect(body.reasoning_effort).toBeUndefined();
    expect(Array.isArray(body.messages)).toBe(true);
    expect(Array.isArray(body.tools)).toBe(true);
  });
});
