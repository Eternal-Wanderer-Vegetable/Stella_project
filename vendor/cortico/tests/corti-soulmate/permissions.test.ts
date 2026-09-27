import { describe, it, expect } from 'vitest';
import { asPersonaRole, checkAccess, zoneOf, type FileOp, type PersonaRole } from '../../bots/corti-soulmate/persona/permissions.ts';

const ok = (role: PersonaRole, op: FileOp, path: string) =>
  expect(checkAccess(role, op, path).ok, `${role} ${op} ${path} 应允许`).toBe(true);
const no = (role: PersonaRole, op: FileOp, path: string) => {
  const r = checkAccess(role, op, path);
  expect(r.ok, `${role} ${op} ${path} 应拒绝`).toBe(false);
  if (!r.ok) expect(r.reason.length).toBeGreaterThan(5);
  return r.ok ? '' : r.reason;
};

describe('区域判定 zoneOf', () => {
  it('按路径前缀判区域,自建目录归other', () => {
    expect(zoneOf('note/a.md')).toBe('note');
    expect(zoneOf('memo/active/x.md')).toBe('memo');
    expect(zoneOf('memo/archived/x.md')).toBe('memo');
    expect(zoneOf('people/阿明.md')).toBe('people');
    expect(zoneOf('WORLDVIEW.md')).toBe('worldview');
    expect(zoneOf('CONSTITUTION.md')).toBe('constitution');
    expect(zoneOf('.\\note\\a.md')).toBe('note');
    expect(zoneOf('././WORLDVIEW.md')).toBe('worldview');
    expect(zoneOf('note/./a.md')).toBe('note');
    expect(zoneOf('自建目录/随便.md')).toBe('other');
    expect(zoneOf('notebook.md')).toBe('other'); // 前缀是note但不是note/目录
    expect(zoneOf('external/qq/x.png')).toBe('external');
    expect(zoneOf('external')).toBe('external');
  });
});

describe('写权限矩阵(意识写笔记和备忘,只有梦重写)', () => {
  it('两个角色所有区域可读', () => {
    for (const role of ['main', 'dream'] as PersonaRole[]) {
      for (const p of ['note/a.md', 'memo/b.md', 'people/c.md', 'WORLDVIEW.md', 'CONSTITUTION.md', 'x/y.md']) ok(role, 'read', p);
    }
  });

  it('main:note/memo/其他读写改名(move_file);仍不许delete', () => {
    ok('main', 'write', 'note/a.md');
    ok('main', 'append', 'note/a.md');
    ok('main', 'write', 'memo/b.md');
    ok('main', 'write', 'memo/active/b.md');
    ok('main', 'write', '自建目录/c.md');
    ok('main', 'rename', 'note/a.md');
    ok('main', 'rename', 'memo/b.md');
    ok('main', 'rename', '自建目录/c.md');
    expect(no('main', 'delete', 'memo/b.md')).toContain('move_file');
  });

  it('main:external/ 是自己的工具抽屉,增删改名清理全允许', () => {
    for (const op of ['write', 'append', 'rename', 'delete'] as FileOp[]) ok('main', op, 'external/qq/images/x.png');
  });

  it('main:people/只能追加,拒绝理由指向append与梦', () => {
    ok('main', 'append', 'people/阿明.md');
    expect(no('main', 'write', 'people/阿明.md')).toContain('append_file');
    expect(no('main', 'rename', 'people/阿明.md')).toContain('append_file');
    no('main', 'delete', 'people/阿明.md');
  });

  it('main:WORLDVIEW 与 CONSTITUTION 只读,理由指向梦', () => {
    expect(no('main', 'write', 'WORLDVIEW.md')).toContain('dream');
    expect(no('main', 'append', 'CONSTITUTION.md')).toContain('dream');
  });

  it('dream:全区域读写改名删除;宪法只能改内容,不能改名删除', () => {
    for (const p of ['note/a.md', 'memo/b.md', 'people/c.md', 'WORLDVIEW.md', 'external/x.png', 'x/y.md']) {
      for (const op of ['write', 'append', 'rename', 'delete'] as FileOp[]) ok('dream', op, p);
    }
    ok('dream', 'write', 'CONSTITUTION.md');
    ok('dream', 'append', 'CONSTITUTION.md');
    no('dream', 'rename', 'CONSTITUTION.md');
    no('dream', 'delete', 'CONSTITUTION.md');
  });

  it('未知 session id 按主意识算(权限较窄的一侧)', () => {
    expect(asPersonaRole('cognition')).toBe('main');
    expect(asPersonaRole('dream')).toBe('dream');
  });
});
