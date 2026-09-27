/**
 * 写权限矩阵,机械硬拦。
 *
 * 一句话纪律:意识写笔记和备忘,只有梦重写。拒绝理由是一句话,会作为工具回执
 * 返回给 agent——写清楚为什么,以及该走什么路径。
 */
import { normalizeWorkspacePath } from '../../cormini/persona/memory.ts';

/** 这份人格实现的两条认知路径,同时也是它向 core 声明的两个 session id。 */
export type PersonaRole = 'main' | 'dream';

export const PERSONA_ROLES: readonly PersonaRole[] = ['main', 'dream'];

/** 未知 session id 一律按权限较窄的主意识处理。 */
export function asPersonaRole(sessionId: string): PersonaRole {
  return sessionId === 'dream' ? 'dream' : 'main';
}

export type FileOp = 'read' | 'write' | 'append' | 'rename' | 'delete';

export type AccessResult = { ok: true } | { ok: false; reason: string };

export type Zone = 'note' | 'memo' | 'people' | 'worldview' | 'constitution' | 'external' | 'other';

/** 区域判定按路径前缀。自建目录归"other",与 note/ 同权。 */
export function zoneOf(relPath: string): Zone {
  const p = normalizeWorkspacePath(relPath);
  const lower = p.toLowerCase();
  if (lower === 'constitution.md') return 'constitution';
  if (lower === 'worldview.md') return 'worldview';
  if (lower === 'note' || lower.startsWith('note/')) return 'note';
  if (lower === 'memo' || lower.startsWith('memo/')) return 'memo';
  if (lower === 'people' || lower.startsWith('people/')) return 'people';
  if (lower === 'external' || lower.startsWith('external/')) return 'external';
  return 'other';
}

const deny = (reason: string): AccessResult => ({ ok: false, reason });
const ALLOW: AccessResult = { ok: true };

export function checkAccess(role: PersonaRole, op: FileOp, relPath: string): AccessResult {
  if (op === 'read') return ALLOW; // 两个角色全区域可读

  const zone = zoneOf(relPath);

  if (role === 'main') {
    switch (zone) {
      case 'note':
      case 'memo':
      case 'other':
        if (op === 'write' || op === 'append' || op === 'rename') return ALLOW;
        return deny('Delete is not permitted; the dream clears the workspace. To relocate a file, use move_file.');
      case 'external':
        return ALLOW; // external/ 是你自己的工具抽屉:增删改名清理都归你
      case 'people':
        if (op === 'append') return ALLOW;
        if (op === 'write') return deny('people/ is append-only; use append_file.');
        return deny('people/ files cannot be renamed or deleted here; use append_file to add content.');
      case 'worldview':
        return deny('WORLDVIEW.md is maintained by the dream; read-only here.');
      case 'constitution':
        return deny('CONSTITUTION.md is read-only while awake; the dream revises it.');
    }
  }

  // dream
  if (zone === 'constitution' && (op === 'rename' || op === 'delete')) {
    return deny('CONSTITUTION.md cannot be renamed or deleted; revision only edits its content.');
  }
  return ALLOW;
}
