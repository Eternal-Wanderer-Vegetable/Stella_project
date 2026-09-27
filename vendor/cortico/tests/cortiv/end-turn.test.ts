import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CortiV } from '../../bots/cortiv/persona/persona.ts';
import { nullLogger } from '../../src/core/util.ts';

describe('CortiV end_turn(显式收工)', () => {
  let dir: string;
  beforeEach(() => (dir = mkdtempSync(join(tmpdir(), 'cortiv-endturn-'))));
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it('主session带end_turn(endsTurn+barrierAfter+flow);梦session不带', async () => {
    const p = new CortiV({ memoryDir: dir });
    const sessions = p.declareSessions();
    const main = sessions.find((d) => d.id === 'main')!;
    const dream = sessions.find((d) => d.id === 'dream')!;

    const endTurn = main.tools().find((t) => t.name === 'end_turn')!;
    expect(endTurn).toBeDefined();
    expect(endTurn.endsTurn).toBe(true);
    expect(endTurn.barrierAfter).toBe(true);
    expect(endTurn.tags).toEqual(['flow']);
    expect(await endTurn.handler({}, { role: 'main', log: nullLogger() })).toBe('[turn ended]');

    // 梦的契约是"最后一段话=浮现值",终止工具会让它交白卷
    expect(dream.tools().some((t) => t.name === 'end_turn')).toBe(false);
  });

  it('继承的其余主session工具原样保留', () => {
    const p = new CortiV({ memoryDir: dir });
    const names = p.declareSessions().find((d) => d.id === 'main')!.tools().map((t) => t.name);
    expect(names).toContain('read_file');
    expect(names).toContain('write_file');
    expect(names).toContain('list_files');
  });
});
