import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import type { BotDefinition } from 'cortico/bot.ts';
import type { CoreConfig, ToolCallContext } from 'cortico/core/types.ts';
import { dryMountBot } from 'cortico/extensions/dry-mount.ts';
import definition from '../index.ts';
import { ExamplePersona, MEMORY_FILE } from '../persona/persona.ts';

const packageDir = resolve(import.meta.dirname, '..');
let scratchDir: string;
beforeEach(() => { scratchDir = mkdtempSync(join(tmpdir(), 'example-bot-')); });
afterEach(() => rmSync(scratchDir, { recursive: true, force: true }));

const persona = () =>
  new ExamplePersona({ memoryDir: join(scratchDir, 'memory'), packageDir, worlds: [], rounds: () => ({ soft: 6, hard: 12 }) });

describe('Example bot', () => {
  it('干装载不报失败:装载器会接受它', () => {
    const report = dryMountBot(definition as unknown as BotDefinition<CoreConfig>, { scratchDir, packageDir });
    expect(report.failures).toEqual([]);
  });

  it('记忆整份进前缀;memory_write 追加一行', async () => {
    const p = persona();
    const write = p.declareSessions()[0].tools().find((t) => t.name === 'memory_write')!;
    expect(await write.handler({ text: '我喜欢雨天。' }, {} as ToolCallContext)).toBe('[written]');
    expect(readFileSync(join(scratchDir, 'memory', MEMORY_FILE), 'utf8')).toContain('我喜欢雨天。');
    const [segment] = await p.systemSegments({ now: new Date(), timezone: 'Asia/Shanghai', worlds: [] });
    expect(segment.text).toContain('我喜欢雨天。');
    expect(segment.text).toContain('没有挂载任何 World');
  });

  it('blobs:put 回 mem: 句柄,get 取回同一份字节,越出 Memory 的句柄取不到', () => {
    const p = persona();
    const handle = p.blobs.put('cat.png', new Uint8Array([1, 2, 3]), 'image/png');
    expect(handle).toBe('mem:blobs/cat.png');
    expect([...(p.blobs.get(handle)?.bytes ?? [])]).toEqual([1, 2, 3]);
    expect(p.blobs.get('mem:../outside.png')).toBeNull();
    expect(p.blobs.list().map((b) => b.handle)).toEqual(['mem:blobs/cat.png']);
  });
});
