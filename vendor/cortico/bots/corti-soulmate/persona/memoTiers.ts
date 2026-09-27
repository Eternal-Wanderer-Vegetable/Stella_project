/**
 * MEMORY 2 三级结构的只读视图 + 容量常量。
 *
 *   memo/顶层(常驻,前缀全文,容量residentCap)
 *   memo/active/(前缀只列文件名,容量activeCap)
 *   memo/archived/(前缀只显示数量,正文由agent主动翻)
 *
 * agent 使用通用文件工具(write_file/move_file/…)移动条目;`memoCapGuard` 在写入时
 * 强制容量上限。本类提供各层文件成员关系,供前缀拼装与容量检查使用。
 */
import { readdirSync, statSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import type { GitWorkspaceMemory } from '../../cormini/persona/memory.ts';

export interface MemoCaps {
  residentCap: number;
  activeCap: number;
}

export class MemoTiers {
  constructor(readonly ws: GitWorkspaceMemory, readonly caps: MemoCaps) {}

  /** 目录内的memo文件,按mtime升序(最旧在前;时间序纯机械) */
  private entries(relDir: string): Array<{ name: string; mtime: number }> {
    let abs: string;
    try {
      abs = this.ws.resolveSafe(relDir);
    } catch {
      return [];
    }
    if (!existsSync(abs)) return [];
    return readdirSync(abs, { withFileTypes: true })
      // 所有文件均计入容量，不限扩展名；排除临时与隐藏文件。
      .filter((e) => e.isFile() && !e.name.startsWith('.') && !e.name.includes('.tmp-'))
      .map((e) => ({ name: e.name, mtime: statSync(join(abs, e.name)).mtimeMs }))
      .sort((a, b) => a.mtime - b.mtime || a.name.localeCompare(b.name));
  }

  /** 常驻文件名,mtime升序 */
  residentFiles(): string[] {
    return this.entries('memo').map((x) => x.name);
  }

  /** active文件名,mtime升序 */
  activeFiles(): string[] {
    return this.entries('memo/active').map((x) => x.name);
  }

  archivedCount(): number {
    return this.entries('memo/archived').length;
  }
}
