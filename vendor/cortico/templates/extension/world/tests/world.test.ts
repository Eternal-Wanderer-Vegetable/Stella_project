import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { ToolCallContext } from 'cortico/core/types.ts';
import { dryMountWorld, fakeWorldContext } from 'cortico/extensions/dry-mount.ts';
import { EXAMPLE } from '../src/definition.ts';
import { EXAMPLE_DEFAULTS } from '../src/config.ts';
import { FakeHost } from './helpers/fake-host.ts';

let scratchDir: string;
beforeEach(() => { scratchDir = mkdtempSync(join(tmpdir(), 'example-world-')); });
afterEach(() => rmSync(scratchDir, { recursive: true, force: true }));

describe('Example World', () => {
  it('干装载不报失败:装载器会接受它', async () => {
    const report = await dryMountWorld(EXAMPLE, { scratchDir });
    expect(report.failures).toEqual([]);
  });

  it('挂载时投一条 example.started 事件,origin 是 internal', async () => {
    const world = EXAMPLE.create(fakeWorldContext(EXAMPLE, { scratchDir }));
    const host = new FakeHost();
    await world.start(host);
    expect(host.events.map((e) => e.type)).toEqual(['example.started']);
    expect(host.events[0].origin).toBe('internal');
    await world.stop();
  });

  it('example_echo 使用配置的回执开头，配置修改立即生效', async () => {
    const ctx = fakeWorldContext(EXAMPLE, { scratchDir });
    const world = EXAMPLE.create(ctx);
    const echo = world.tools().find((t) => t.name === 'example_echo')!;
    const call = {} as ToolCallContext;
    expect(await echo.handler({ text: 'hi' }, call)).toBe(`${EXAMPLE_DEFAULTS.greeting} hi`);
    ctx.persist({ greeting: 'Hello.' });
    expect(await echo.handler({ text: 'hi' }, call)).toBe('Hello. hi');
  });
});
