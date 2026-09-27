/** GitWorkspaceMemory 的路径、读写、遍历与检索；Persona 权限和虚拟文件测试在 tests/corti-soulmate。 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { existsSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { GitWorkspaceMemory, WorkspaceError } from '../../bots/cormini/persona/memory.ts';

describe('工作区记忆的磁盘底层', () => {
  let dir: string;
  let m: GitWorkspaceMemory;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'memory-test-'));
    m = new GitWorkspaceMemory({ memoryDir: dir });
    m.ensureDirs(['', 'note', 'note/playbook', 'note/library', 'people', 'memo', 'memo/active', 'memo/archived']);
  });
  afterEach(() => {
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch {
      // Windows 偶发句柄未释放,不影响断言
    }
  });

  it('ensureDirs 创建工作区骨架', () => {
    for (const d of ['note', 'people', 'memo', 'memo/active', 'memo/archived']) {
      expect(existsSync(join(dir, ...d.split('/')))).toBe(true);
    }
  });

  it('seed 只在文件不在时写,已有的一个字不动', () => {
    m.seed([['CONSTITUTION.md', '出厂宪法\n']]);
    expect(m.readFile('CONSTITUTION.md')).toBe('出厂宪法\n');
    m.seed([['CONSTITUTION.md', '不该覆盖\n']]);
    expect(m.readFile('CONSTITUTION.md')).toBe('出厂宪法\n');
  });

  it('路径逃逸全部被拒:../、绝对路径、盘符', () => {
    expect(() => m.readFile('../outside.md')).toThrow(WorkspaceError);
    expect(() => m.readFile('note/../../outside.md')).toThrow(/\.\.|工作区/);
    expect(() => m.writeFileAtomic('/etc/passwd', 'x')).toThrow(WorkspaceError);
    expect(() => m.writeFileAtomic('C:/evil.md', 'x')).toThrow(WorkspaceError);
    expect(() => m.writeFileAtomic('..\\evil.md', 'x')).toThrow(WorkspaceError);
    expect(() => m.deleteFile('..')).toThrow(WorkspaceError);
  });

  it('insideWorkspace 是工具层那条较松的护栏:解析后落在区内就放行,逃逸照样拦', () => {
    expect(m.insideWorkspace('note/../a.md')).toBe(join(dir, 'a.md'));
    expect(() => m.insideWorkspace('../a.md')).toThrow(/escapes workspace/);
    // 同一条路径在更严的 resolveSafe 那里过不去
    expect(() => m.resolveSafe('note/../a.md')).toThrow(WorkspaceError);
  });

  it('writeFileAtomic 自动建父目录、无tmp残留、可覆写', () => {
    m.writeFileAtomic('note/deep/nested.md', '第一版');
    expect(m.readFile('note/deep/nested.md')).toBe('第一版');
    m.writeFileAtomic('note/deep/nested.md', '第二版');
    expect(m.readFile('note/deep/nested.md')).toBe('第二版');
    const leftovers = readdirSync(join(dir, 'note', 'deep')).filter((f) => f.includes('.tmp-'));
    expect(leftovers).toEqual([]);
  });

  it('appendFile 在无换行结尾的文件后补换行再追加', () => {
    m.writeFileAtomic('people/某人.md', '某人:第一行概括');
    m.appendFile('people/某人.md', '- 07-17 他说了一件事\n');
    expect(m.readFile('people/某人.md')).toBe('某人:第一行概括\n- 07-17 他说了一件事\n');
  });

  it('renameFile 目标已存在时拒绝', () => {
    m.writeFileAtomic('note/a.md', 'a');
    m.writeFileAtomic('note/b.md', 'b');
    expect(() => m.renameFile('note/a.md', 'note/b.md')).toThrow(/已存在/);
    m.renameFile('note/a.md', 'note/c.md');
    expect(m.exists('note/a.md')).toBe(false);
    expect(m.readFile('note/c.md')).toBe('a');
  });

  it('renameFile 拒绝移动目录', () => {
    m.writeFileAtomic('note/子目录/a.md', 'a');
    expect(() => m.renameFile('note/子目录', 'note/改名后')).toThrow(/只能移动文件/);
    expect(m.readFile('note/子目录/a.md')).toBe('a');
  });

  it('deleteFile 只删文件不删目录', () => {
    m.writeFileAtomic('note/x.md', 'x');
    m.deleteFile('note/x.md');
    expect(m.exists('note/x.md')).toBe(false);
    expect(() => m.deleteFile('note')).toThrow(/目录/);
    expect(() => m.deleteFile('note/nothing.md')).toThrow(/不存在/);
  });

  it('exists / isDir 分得清文件与目录,逃逸一律 false', () => {
    m.writeFileAtomic('note/x.md', 'x');
    expect(m.exists('note/x.md')).toBe(true);
    expect(m.isDir('note/x.md')).toBe(false);
    expect(m.isDir('note')).toBe(true);
    expect(m.exists('../x.md')).toBe(false);
    expect(m.isDir('../')).toBe(false);
  });

  it('tree 渲染目录层级且文件名齐全', () => {
    m.writeFileAtomic('note/2026-07-17-第一天的观察.md', 'x');
    m.writeFileAtomic('people/阿明-12345.md', 'x');
    m.writeFileAtomic('memo/active/搁置的事.md', 'x');
    const t = m.tree();
    expect(t).toContain('persona/');
    expect(t).toContain('note/');
    expect(t).toContain('2026-07-17-第一天的观察.md');
    expect(t).toContain('阿明-12345.md');
    expect(t).toContain('搁置的事.md');
    expect(t).toMatch(/├── |└── /);
  });

  it('treeShallow 只渲染最外层直接子项、不递归', () => {
    m.writeFileAtomic('note/2026-07-17-第一天的观察.md', 'x');
    m.writeFileAtomic('memo/active/搁置的事.md', 'x');
    m.writeFileAtomic('顶层文件.md', 'x');
    const t = m.treeShallow();
    expect(t.split('\n')[0]).toBe('persona/');
    // 顶层目录带斜杠、顶层文件如实
    expect(t).toContain('note/');
    expect(t).toContain('memo/');
    expect(t).toContain('顶层文件.md');
    // 目录在前、文件在后
    expect(t.indexOf('note/')).toBeLessThan(t.indexOf('顶层文件.md'));
    // 深层内容一律不出现
    expect(t).not.toContain('2026-07-17-第一天的观察.md');
    expect(t).not.toContain('active/');
    expect(t).not.toContain('搁置的事.md');
    // 无树枝符号(不是递归树)
    expect(t).not.toMatch(/├── |└── /);
  });

  it('listDir 目录在前带斜杠、文件在后', () => {
    m.writeFileAtomic('memo/一条备忘.md', 'x');
    expect(m.listDir('memo')).toEqual(['active/', 'archived/', '一条备忘.md']);
    expect(() => m.listDir('memo/一条备忘.md')).toThrow(/是文件/);
    expect(() => m.listDir('没有这个目录')).toThrow(/不存在/);
  });

  it('walkFiles 交回相对路径,可只走某个子目录', () => {
    m.writeFileAtomic('note/a.md', 'x');
    m.writeFileAtomic('note/deep/b.md', 'x');
    m.writeFileAtomic('顶层.md', 'x');
    expect(m.walkFiles()).toEqual(expect.arrayContaining(['note/a.md', 'note/deep/b.md', '顶层.md']));
    expect(m.walkFiles('note')).toEqual(['note/a.md', 'note/deep/b.md']);
  });

  it('listing 指定的目录全量,其余子目录折叠成一行计数', () => {
    for (let i = 0; i < 12; i++) m.writeFileAtomic(`note/library/n${i}.md`, 'x');
    const root = m.listing();
    expect(root).toContain('note/library/n0.md');
    expect(root).toContain('共 12 项');
    const full = m.listing('note/library');
    expect(full).toContain('note/library/n11.md');
    expect(full).not.toContain('共 12 项');
    expect(m.listing('没有这个目录')).toBe('[not found] 没有这个目录');
  });

  it('globFiles 匹配整条相对路径,最近改过的在前', () => {
    m.writeFileAtomic('note/a.md', 'x');
    m.writeFileAtomic('note/b.txt', 'x');
    m.writeFileAtomic('note/deep/c.md', 'x');
    expect(m.globFiles('*.md').sort()).toEqual(['note/a.md', 'note/deep/c.md']);
    expect(m.globFiles('*.md', 'note/deep')).toEqual(['note/deep/c.md']);
    expect(m.globFiles('*.json')).toEqual([]);
  });

  it('grep 逐行判定,交回整份行表与命中行号;可只搜某个文件', () => {
    m.writeFileAtomic('note/t.md', 'Hello World\n第二行\nhello again');
    const hits = m.grep({ match: (l) => l.toLowerCase().includes('hello') });
    expect(hits).toHaveLength(1);
    expect(hits[0].path).toBe('note/t.md');
    expect(hits[0].hits).toEqual([0, 2]);
    expect(hits[0].lines[0]).toBe('Hello World');
    // dir 缩小范围:people/ 下没有命中
    expect(m.grep({ match: (l) => l.includes('Hello'), path: 'people' })).toEqual([]);
    // 单个文件也走得通
    expect(m.grep({ match: (l) => l.includes('Hello'), path: 'note/t.md' })).toHaveLength(1);
  });

  it('grep 跳过二进制文件(含NUL字节)与原子写临时文件,文本文件照常命中', () => {
    writeFileSync(join(dir, 'note', 'sticker.png'), Buffer.from('KEYWORD\0\x01\x02binary', 'binary'));
    writeFileSync(join(dir, 'note', 'plain.md.tmp-abc123'), 'KEYWORD 还没落地', 'utf8');
    m.writeFileAtomic('note/plain.md', 'KEYWORD in text');
    const hits = m.grep({ match: (l) => l.includes('KEYWORD') });
    expect(hits.map((h) => h.path)).toEqual(['note/plain.md']);
  });

  it('grep 的 filter 只放行路径匹配的文件', () => {
    m.writeFileAtomic('note/a.md', '铃兰');
    m.writeFileAtomic('people/b.md', '铃兰');
    const hits = m.grep({ match: (l) => l.includes('铃兰'), filter: /^people\// });
    expect(hits.map((h) => h.path)).toEqual(['people/b.md']);
  });
});
