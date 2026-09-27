/** 验证文件工具回执与实际文件内容、路径、行区间及改动统计一致。 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { Cormini } from '../../bots/cormini/persona/persona.ts';
import { globToRegExp } from '../../bots/cormini/persona/memory.ts';
import { nullLogger } from '../../src/core/util.ts';


let dir: string;
let p: Cormini;

const run = (name: string, args: Record<string, unknown>): Promise<string> => {
  const t = p.declareSessions()[0].tools().find((x) => x.name === name)!;
  return t.handler(args, { role: 'main', log: nullLogger() }) as Promise<string>;
};
const put = (rel: string, text: string): void => {
  mkdirSync(join(dir, dirname(rel)), { recursive: true });
  writeFileSync(join(dir, rel), text, 'utf8');
};
const disk = (rel: string): string => readFileSync(join(dir, rel), 'utf8');

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'cormini-tools-'));
  p = new Cormini({ memoryDir: dir });
});
afterEach(() => rmSync(dir, { recursive: true, force: true }));

describe('read_file:整份或行区间', () => {
  beforeEach(() => put('a.md', '一\n二\n三\n'));

  it('不给区间就是原文,一个字不加', async () => {
    expect(await run('read_file', { path: 'a.md' })).toBe('一\n二\n三\n');
  });

  it('offset + limit 取一段,抬头说清第几到第几行、共几行', async () => {
    expect(await run('read_file', { path: 'a.md', offset: 2, limit: 1 })).toBe('[a.md 第 2-2 行,共 3 行]\n二');
    expect(await run('read_file', { path: 'a.md', offset: 2 })).toBe('[a.md 第 2-3 行,共 3 行]\n二\n三');
    expect(await run('read_file', { path: 'a.md', limit: 2 })).toBe('[a.md 第 1-2 行,共 3 行]\n一\n二');
  });

  it('负 offset 从文件尾倒数:读长笔记的末尾几行', async () => {
    expect(await run('read_file', { path: 'a.md', offset: -2 })).toBe('[a.md 第 2-3 行,共 3 行]\n二\n三');
    expect(await run('read_file', { path: 'a.md', offset: -9 })).toBe('[a.md 第 1-3 行,共 3 行]\n一\n二\n三');
  });

  it('越界与空文件各有一句实话', async () => {
    expect(await run('read_file', { path: 'a.md', offset: 9 })).toBe('[a.md 共 3 行,没有第 9 行]');
    put('empty.md', '');
    expect(await run('read_file', { path: 'empty.md', offset: 1 })).toBe('[empty.md 是空文件]');
    expect(await run('read_file', { path: 'nope.md', offset: 1 })).toBe('[not found] nope.md');
  });
});

describe('edit_file:精确替换', () => {
  const profile = 'viewers/bilibili/1.md';
  beforeEach(() => put(profile, '抬杠王(1) — 旧摘要\n\n2026-08-01 来过。\n'));

  it('唯一命中就换,其余一字不动;回执报从第几行起、换了几处、现在多大', async () => {
    const out = await run('edit_file', { path: profile, old_string: '旧摘要', new_string: '新摘要' });
    const next = '抬杠王(1) — 新摘要\n\n2026-08-01 来过。\n';
    expect(out).toBe(`[edited] ${profile} 第 1 行起换了 1 处,现在 ${next.length} 字符`);
    expect(disk(profile)).toBe(next);
  });

  it('替换文本按字面写入,$& 之类不当模式', async () => {
    await run('edit_file', { path: profile, old_string: '来过', new_string: '$&来过两次' });
    expect(disk(profile)).toContain('$&来过两次');
  });

  it('找不到、不唯一、空串、原样不变:都不动文件,回执说清怎么办', async () => {
    const before = disk(profile);
    expect(await run('edit_file', { path: profile, old_string: '没有的话', new_string: 'x' }))
      .toContain('没有这段文字');
    expect(await run('edit_file', { path: profile, old_string: '', new_string: 'x' })).toContain('不能为空');
    expect(await run('edit_file', { path: profile, old_string: '旧摘要', new_string: '旧摘要' })).toContain('相同');
    put('dup.md', '甲 乙 甲\n');
    expect(await run('edit_file', { path: 'dup.md', old_string: '甲', new_string: '丙' })).toContain('出现 2 次');
    expect(disk(profile)).toBe(before);
    expect(disk('dup.md')).toBe('甲 乙 甲\n');
  });

  it('replace_all 全换,回执数出几处', async () => {
    put('dup.md', '甲 乙 甲\n');
    const out = await run('edit_file', { path: 'dup.md', old_string: '甲', new_string: '丙', replace_all: true });
    expect(out).toContain('换了 2 处');
    expect(disk('dup.md')).toBe('丙 乙 丙\n');
  });

  it('不存在、目录、逃逸路径各自失败,不抛', async () => {
    expect(await run('edit_file', { path: 'nope.md', old_string: 'a', new_string: 'b' })).toContain('不存在');
    expect(await run('edit_file', { path: 'viewers', old_string: 'a', new_string: 'b' })).toContain('是目录');
    expect(await run('edit_file', { path: '../x.md', old_string: 'a', new_string: 'b' })).toContain('[edit failed]');
  });
});

describe('delete_file', () => {
  it('删掉文件并回执;宪法这类常驻前缀的文件拒删', async () => {
    put('notes/old.md', 'x\n');
    put('CONSTITUTION.md', '# 我\n');
    expect(await run('delete_file', { path: 'notes/old.md' })).toBe('[deleted] notes/old.md');
    expect(existsSync(join(dir, 'notes/old.md'))).toBe(false);
    expect(await run('delete_file', { path: 'CONSTITUTION.md' })).toContain('常驻系统前缀');
    expect(existsSync(join(dir, 'CONSTITUTION.md'))).toBe(true);
  });

  it('目录、不存在、逃逸路径各自失败', async () => {
    put('notes/a.md', 'x\n');
    expect(await run('delete_file', { path: 'notes' })).toContain('是目录');
    expect(await run('delete_file', { path: 'nope.md' })).toContain('不存在');
    expect(await run('delete_file', { path: '../x.md' })).toContain('[delete failed]');
    expect(existsSync(join(dir, 'notes/a.md'))).toBe(true);
  });
});

describe('glob_files:按名找,最近改过的在前', () => {
  beforeEach(() => {
    put('notes/a.md', 'a');
    put('notes/b.txt', 'b');
    put('deep/x/c.md', 'c');
    // 构造时种下的 CONSTITUTION.md 也在树里:把它压成最旧的,顺序才可断言
    const t = (min: number): Date => new Date(2026, 8, 1, 12, min);
    utimesSync(join(dir, 'CONSTITUTION.md'), t(0), t(0));
    utimesSync(join(dir, 'notes/a.md'), t(1), t(1));
    utimesSync(join(dir, 'notes/b.txt'), t(2), t(2));
    utimesSync(join(dir, 'deep/x/c.md'), t(3), t(3));
  });

  it('不带 **/ 的模式找全树;结果按修改时间倒序', async () => {
    const out = await run('glob_files', { glob_pattern: '*.md' });
    expect(out).toBe('3 个文件,最近改过的在前:\n- deep/x/c.md\n- notes/a.md\n- CONSTITUTION.md');
  });

  it('目录前缀、target_directory 与花括号都能收窄或放宽', async () => {
    expect(await run('glob_files', { glob_pattern: 'deep/**/*.md' })).toBe('1 个文件,最近改过的在前:\n- deep/x/c.md');
    expect(await run('glob_files', { glob_pattern: '*.md', target_directory: 'notes' })).toBe('1 个文件,最近改过的在前:\n- notes/a.md');
    expect(await run('glob_files', { glob_pattern: '*.{md,txt}' })).toContain('4 个文件');
  });

  it('没命中就说没有;目录不对就失败', async () => {
    expect(await run('glob_files', { glob_pattern: '*.json' })).toBe('没有匹配 *.json 的文件');
    expect(await run('glob_files', { glob_pattern: '*.md', target_directory: 'nope' })).toContain('[glob failed]');
    expect(await run('glob_files', { glob_pattern: '' })).toContain('[glob failed]');
  });

  it('globToRegExp:** 跨目录、* 不跨、? 单字、{} 择一', () => {
    const m = (g: string, s: string): boolean => globToRegExp(g).test(s);
    expect(m('**/*.md', 'a/b/c.md')).toBe(true);
    expect(m('**/*.md', 'c.md')).toBe(true);
    expect(m('*.md', 'a/c.md')).toBe(false);
    expect(m('a/?.md', 'a/c.md')).toBe(true);
    expect(m('a/?.md', 'a/cc.md')).toBe(false);
    expect(m('**/{目标,地图}.md', 'minecraft/worlds/33/目标.md')).toBe(true);
    expect(m('**/{目标,地图}.md', 'minecraft/worlds/33/蓝图.md')).toBe(false);
  });
});

describe('grep_files:按内容搜', () => {
  beforeEach(() => {
    put('notes/a.md', '第一行 铃兰\n第二行\n第三行 铃兰花\n');
    put('notes/b.md', '没有\n');
    put('deep/c.md', '铃兰\n');
    put('notes/d.md', 'Hello\n');
  });

  it('缺省交回 路径:行号: 那一行,抬头数命中与文件', async () => {
    const out = await run('grep_files', { pattern: '铃兰' });
    expect(out.split('\n')[0]).toBe('3 处命中,2 个文件:');
    expect(out).toContain('deep/c.md:1: 铃兰');
    expect(out).toContain('notes/a.md:1: 第一行 铃兰');
    expect(out).toContain('notes/a.md:3: 第三行 铃兰花');
    expect(out).not.toContain('notes/b.md');
  });

  it('ignore_case、context、path、glob 各管一头', async () => {
    expect(await run('grep_files', { pattern: 'hello' })).toBe('没有匹配 /hello/ 的内容');
    expect(await run('grep_files', { pattern: 'hello', ignore_case: true })).toContain('notes/d.md:1: Hello');
    const ctx = await run('grep_files', { pattern: '第二行', context: 1 });
    expect(ctx).toContain('notes/a.md-1- 第一行 铃兰');
    expect(ctx).toContain('notes/a.md:2: 第二行');
    expect(ctx).toContain('notes/a.md-3- 第三行 铃兰花');
    expect(await run('grep_files', { pattern: '铃兰', path: 'deep' })).toBe('1 处命中,1 个文件:\ndeep/c.md:1: 铃兰');
    expect(await run('grep_files', { pattern: '铃兰', path: 'notes/a.md' })).toContain('2 处命中,1 个文件');
    expect(await run('grep_files', { pattern: '铃兰', glob: 'deep/**' })).not.toContain('notes/a.md');
  });

  it('files_with_matches 与 count 两种输出', async () => {
    expect(await run('grep_files', { pattern: '铃兰', output_mode: 'files_with_matches' }))
      .toBe('2 个文件命中,共 3 处:\ndeep/c.md(1 处)\nnotes/a.md(2 处)');
    expect(await run('grep_files', { pattern: '铃兰', output_mode: 'count' }))
      .toBe('2 个文件命中,共 3 处:\ndeep/c.md: 1\nnotes/a.md: 2');
  });

  it('head_limit 截断时抬头说只交回了前几处', async () => {
    const out = await run('grep_files', { pattern: '铃兰', head_limit: 1 });
    expect(out.split('\n')[0]).toBe('3 处命中,2 个文件,只交回前 1 处:');
    expect(out.split('\n')).toHaveLength(2);
  });

  it('正则无效、路径不存在、空模式各自失败', async () => {
    expect(await run('grep_files', { pattern: '(' })).toContain('正则无效');
    expect(await run('grep_files', { pattern: 'x', path: 'nope' })).toContain('不存在');
    expect(await run('grep_files', { pattern: '' })).toContain('[grep failed]');
  });
});
