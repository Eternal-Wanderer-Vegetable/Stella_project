import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { writeFileSync, mkdirSync, utimesSync } from 'node:fs';
import { join } from 'node:path';
import { CortiSoulmate } from '../../bots/corti-soulmate/persona/index.ts';
import type { PersonaRole } from '../../bots/corti-soulmate/persona/permissions.ts';
import { buildRoster } from '../../bots/corti-soulmate/persona/roster.ts';
import { makeCfg, makeFakeHarnessApi } from '../core/helpers.ts';
import { tmpPersona, cleanup, ctxFor, pick } from './helpers.ts';

describe('花名册(派生视图)', () => {
  let dir: string;
  beforeEach(() => {
    dir = tmpPersona();
    mkdirSync(join(dir, 'people'), { recursive: true });
  });
  afterEach(() => cleanup(dir));

  // 空值返回空串，空态文案由 MEMORY.md 模板提供。
  it('空目录 → 空串,空态文案让模板去说', () => {
    expect(buildRoster(dir)).toBe('');
  });

  it('people目录不存在 → 空串', () => {
    expect(buildRoster(join(dir, '不存在的子目录'))).toBe('');
  });

  it('每人一行:文件名去.md + 第一行', () => {
    writeFileSync(join(dir, 'people', '阿明-12345.md'), '阿明:群主,爱开玩笑,对我还算友好\n\n- 07-16 他说……\n', 'utf8');
    writeFileSync(join(dir, 'people', '小北.md'), '小北:新来的,话不多\n', 'utf8');
    const r = buildRoster(dir);
    expect(r).toContain('- 阿明-12345 — 阿明:群主,爱开玩笑,对我还算友好');
    expect(r).toContain('- 小北 — 小北:新来的,话不多');
    expect(r.split('\n').length).toBe(2);
  });

  it('第一行为空的档案使用默认文本', () => {
    writeFileSync(join(dir, 'people', '空档案.md'), '\n第二行不能冒充花名册概括\n', 'utf8');
    expect(buildRoster(dir)).toContain('- 空档案 — (档案第一行为空)');
    expect(buildRoster(dir)).not.toContain('第二行不能冒充');
  });
});

/** 主 session 的工具面(文件工具 + World 工具 + end_turn + schedule_wake) */
const mainTools = (core: CortiSoulmate) => core.declareSessions().find((d) => d.id === 'main')!.tools();

describe('MEMORY 0~4 拼装', () => {
  let dir: string;
  let core: CortiSoulmate;
  const ctx = () => ({
    now: new Date('2026-07-17T12:00:00+08:00'),
    timezone: 'Asia/Shanghai',
  });
  /** Persona 的浮现值存于 Core 的不透明状态中。 */
  const withEmergences = (...texts: string[]): void => {
    const state: Record<string, unknown> = { emergences: texts };
    core.attach(makeFakeHarnessApi({ personaState: () => state }));
  };

  beforeEach(() => {
    dir = tmpPersona();
    const cfg = makeCfg();
    cfg.memo = { residentCap: 3, activeCap: 2 };
    core = new CortiSoulmate({ memoryDir: dir, cfg });
  });
  afterEach(() => cleanup(dir));

  it('五段齐全,顺序正确', () => {
    const m = core.assembleMemory(ctx());
    const idx = [
      '【MEMORY 0·地图】', '【MEMORY 1·认知】', '【MEMORY 2·备忘】',
      '【MEMORY 3·反射】', '【MEMORY 4·当下】',
    ].map((h) => m.indexOf(h));
    for (const i of idx) expect(i).toBeGreaterThanOrEqual(0);
    expect([...idx]).toEqual([...idx].sort((a, b) => a - b));
  });

  it('骨架来自模板:改 MEMORY.md 就改了这一段,渲染后不留没填的洞', () => {
    const m = core.assembleMemory(ctx());
    expect(m).not.toMatch(/\{\{/);
    // 空态文案由模板的缺省承载,不在代码里
    expect(m).toContain('(还不认识任何人)');
    expect(m).toContain('(常驻区是空的)');
    expect(m).toContain('(此刻没有)');
  });

  it('MEMORY 0 是最外层目录地图(只到顶层,不含深层文件名)', async () => {
    await pick(mainTools(core), 'write_file').handler(
      { path: 'note/2026-07-17-初次观察.md', content: 'x' }, ctxFor('main'),
    );
    const m = core.assembleMemory(ctx());
    expect(m).toContain('persona/');
    expect(m).toContain('note/');
    expect(m).not.toContain('2026-07-17-初次观察.md');
  });

  it('MEMORY 0:external/qq/images/ 未建目录时给占位文本', () => {
    const m = core.assembleMemory(ctx());
    expect(m).toContain('external/qq/images/');
    expect(m).toContain('(还没有存过图)');
  });

  it('MEMORY 0:external/qq/images/ 按mtime倒序只列最近5个', () => {
    const imgDir = join(dir, 'external', 'qq', 'images');
    mkdirSync(imgDir, { recursive: true });
    const names = ['a', 'b', 'c', 'd', 'e', 'f'];
    names.forEach((n, i) => {
      const p = join(imgDir, `${n}.png`);
      writeFileSync(p, 'x');
      utimesSync(p, new Date(2026, 0, 1 + i), new Date(2026, 0, 1 + i)); // 依次更晚
    });
    const m = core.assembleMemory(ctx());
    for (const n of ['b', 'c', 'd', 'e', 'f']) expect(m).toContain(`- ${n}.png`);
    expect(m).not.toContain('- a.png');
    expect(m.indexOf('- f.png')).toBeLessThan(m.indexOf('- e.png'));
  });

  it('MEMORY 1:无WORLDVIEW时占位;有则全文;花名册跟随', () => {
    const m1 = core.assembleMemory(ctx());
    expect(m1).toContain('(你还没有形成对环境的综合认知——这份文件由你的梦来写)');

    writeFileSync(join(dir, 'WORLDVIEW.md'), '我在一个爱聊游戏的QQ群里。', 'utf8');
    writeFileSync(join(dir, 'people', '阿明.md'), '阿明:群主\n', 'utf8');
    const m2 = core.assembleMemory(ctx());
    expect(m2).toContain('我在一个爱聊游戏的QQ群里。');
    expect(m2).toContain('- 阿明 — 阿明:群主');
  });

  it('MEMORY 2:常驻全文带文件名标头,active只列名,archived一句指路', async () => {
    const wf = pick(mainTools(core), 'write_file');
    const mv = pick(mainTools(core), 'move_file');
    await wf.handler({ path: 'memo/要紧事.md', content: '答应了周五交东西' }, ctxFor('main'));
    await wf.handler({ path: 'memo/次要事.md', content: '下次问问那件事' }, ctxFor('main'));
    await wf.handler({ path: 'memo/第三件.md', content: '三' }, ctxFor('main'));
    await mv.handler({ from: 'memo/次要事.md', to: 'memo/active/次要事.md' }, ctxFor('main'));
    await wf.handler({ path: 'memo/active/已完成.md', content: '已经完成' }, ctxFor('main'));
    await mv.handler({ from: 'memo/active/已完成.md', to: 'memo/archived/已完成.md' }, ctxFor('main'));
    await wf.handler({ path: 'memo/第四件.md', content: '四' }, ctxFor('main'));

    const m = core.assembleMemory(ctx());
    expect(m).toContain('── memo/要紧事.md ──');
    expect(m).toContain('答应了周五交东西');
    expect(m).toContain('「次要事.md」'); // active只列名
    expect(m).not.toContain('下次问问那件事'); // active不放全文
    expect(m).toContain('memo/archived/ 里还有 1 条归档,想看自己翻。');
    expect(m).not.toContain('已经完成'); // archived不放全文
  });

  it('MEMORY 3:浮现逐条;无则(此刻没有)', () => {
    expect(core.assembleMemory(ctx())).toContain('(此刻没有)');
    withEmergences('我想起来:上个月他也这么说过,当时我没接话');
    const m = core.assembleMemory(ctx());
    expect(m).toContain('- 我想起来:上个月他也这么说过,当时我没接话');
  });

  it('MEMORY 4:当前时间按时区渲染并标注时区', () => {
    const m = core.assembleMemory(ctx());
    expect(m).toContain('2026-07-17T12:00:00.000+08:00');
    expect(m).toContain('Asia/Shanghai');
  });
});

describe('CortiSoulmate 静态文本与核心动作', () => {
  let dir: string;
  let core: CortiSoulmate;
  beforeEach(() => {
    dir = tmpPersona();
    core = new CortiSoulmate({ memoryDir: dir, cfg: makeCfg() });
  });
  afterEach(() => cleanup(dir));

  it('constitutionText:构造时种下占位;有内容读当下内容', () => {
    expect(core.constitutionText().trim()).toBe('(宪法尚未写入)');
    writeFileSync(join(dir, 'CONSTITUTION.md'), '第一条:诚实。', 'utf8');
    expect(core.constitutionText()).toBe('第一条:诚实。');
  });

  it('toolUsageText(main):memo容量数字按cfg实时插值', () => {
    const u = core.toolUsageText('main');
    expect(u).toContain('7 resident');
    expect(u).toContain('up to 21');
  });

  it('toolUsageText:主意识与梦各一份文案;未知 session id 按主意识', () => {
    const roles: PersonaRole[] = ['main', 'dream'];
    const byRole = roles.map((r) => core.toolUsageText(r));
    expect(new Set(byRole).size).toBe(2);
    expect(core.toolUsageText('cognition')).toBe(core.toolUsageText('main'));
    expect(core.toolUsageText('main')).toContain('end_turn');
  });

  it('primitiveToolSpecs:只剩 schedule_wake 的 schema,无 handler', () => {
    const specs = core.primitiveToolSpecs();
    expect(specs.map((s) => s.name)).toEqual(['schedule_wake']);
    const wake = specs[0];
    const wakeParams = wake.parameters as {
      properties: Record<string, unknown>;
      oneOf: Array<{ required: string[] }>;
    };
    expect(wakeParams.properties).toHaveProperty('after_minutes');
    expect(wakeParams.properties).toHaveProperty('block');
    expect(wakeParams.properties).toHaveProperty('wake_keyword');
    expect(wakeParams.properties).toHaveProperty('overflow_limit');
    expect(wakeParams.oneOf).toEqual([{ required: ['at'] }, { required: ['after_minutes'] }]);
    for (const s of specs) expect('handler' in s).toBe(false);
  });

  it('构造时ensureDirs建好骨架', () => {
    const m = core.assembleMemory({ now: new Date(), timezone: 'Asia/Shanghai' });
    for (const seg of ['note/', 'people/', 'memo/', 'active/', 'archived/']) {
      expect(m).toContain(seg);
    }
  });
});
