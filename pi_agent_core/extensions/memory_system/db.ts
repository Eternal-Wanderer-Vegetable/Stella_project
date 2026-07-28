import Database from 'better-sqlite3';
import { UserProfile, ShortTermContext, LongTermMemory } from './types';

export class MemoryRepository {
  private db: Database.Database;

  constructor(dbPath: string = 'agent_memory.db') {
    this.db = new Database(dbPath);
    this.initTables();
  }

  private initTables() {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS user_profiles (
        user_id TEXT PRIMARY KEY,
        nickname TEXT,
        personality_traits TEXT,
        agent_attitude TEXT,
        interaction_count INTEGER DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS short_term_context (
        group_id TEXT PRIMARY KEY,
        active_summary TEXT,
        pending_topic TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS long_term_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id TEXT,
        user_id TEXT,
        summary TEXT NOT NULL,
        importance INTEGER DEFAULT 5,
        access_count INTEGER DEFAULT 0,
        last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
      );
    `);
  }

  // 1. 获取指定用户的画像卡片
  getUserProfile(userId: string): UserProfile | null {
    const row = this.db.prepare('SELECT * FROM user_profiles WHERE user_id = ?').get(userId) as any;
    if (!row) return null;
    return {
      userId: row.user_id,
      nickname: row.nickname,
      personalityTraits: row.personality_traits,
      agentAttitude: row.agent_attitude,
      interactionCount: row.interaction_count,
      updatedAt: row.updated_at,
    };
  }

  // 2. 获取当前群的短期上下文
  getShortTermContext(groupId: string): ShortTermContext | null {
    const row = this.db.prepare('SELECT * FROM short_term_context WHERE group_id = ?').get(groupId) as any;
    if (!row) return null;
    return {
      groupId: row.group_id,
      activeSummary: row.active_summary,
      pendingTopic: row.pending_topic,
      updatedAt: row.updated_at,
    };
  }

  // 3. 检索长期记忆 (基于关键词/近况简单的模糊匹配，后期可接入 sqlite-vec 向量检索)
  searchLongTermMemory(query: string, userId?: string, groupId?: string, limit: number = 3): LongTermMemory[] {
    // 带有艾宾浩斯衰减与 Access Count 的简易排序算法示例
    const stmt = this.db.prepare(`
      SELECT *, 
        (importance * (1 + LOG(access_count + 1))) AS weight
      FROM long_term_memories
      WHERE (user_id = ? OR group_id = ? OR summary LIKE ?)
      ORDER BY weight DESC, last_accessed_at DESC
      LIMIT ?
    `);

    const rows = stmt.all(userId || '', groupId || '', `%${query}%`, limit) as any[];

    // 更新被检索到的记录的访问频次与时间
    const updateStmt = this.db.prepare(`
      UPDATE long_term_memories 
      SET access_count = access_count + 1, last_accessed_at = CURRENT_TIMESTAMP 
      WHERE id = ?
    `);

    return rows.map(r => {
      updateStmt.run(r.id);
      return {
        id: r.id,
        groupId: r.group_id,
        userId: r.user_id,
        summary: r.summary,
        importance: r.importance,
        accessCount: r.access_count + 1,
        lastAccessedAt: new Date().toISOString(),
      };
    });
  }

  // 在 MemoryRepository 类中补充：

upsertUserProfile(profile: { userId: string; nickname?: string; personalityTraits: string; agentAttitude: string }) {
  const stmt = this.db.prepare(`
    INSERT INTO user_profiles (user_id, nickname, personality_traits, agent_attitude, interaction_count, updated_at)
    VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id) DO UPDATE SET
      nickname = COALESCE(EXCLUDED.nickname, user_profiles.nickname),
      personality_traits = EXCLUDED.personality_traits,
      agent_attitude = EXCLUDED.agent_attitude,
      interaction_count = user_profiles.interaction_count + 1,
      updated_at = CURRENT_TIMESTAMP
  `);
  stmt.run(profile.userId, profile.nickname || '', profile.personalityTraits, profile.agentAttitude);
}

upsertShortTermContext(context: { groupId: string; activeSummary: string; pendingTopic: string }) {
  const stmt = this.db.prepare(`
    INSERT INTO short_term_context (group_id, active_summary, pending_topic, updated_at)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(group_id) DO UPDATE SET
      active_summary = EXCLUDED.active_summary,
      pending_topic = EXCLUDED.pending_topic,
      updated_at = CURRENT_TIMESTAMP
  `);
  stmt.run(context.groupId, context.activeSummary, context.pendingTopic);
}

addLongTermMemory(memory: { groupId?: string; userId?: string; summary: string; importance: number }) {
  const stmt = this.db.prepare(`
    INSERT INTO long_term_memories (group_id, user_id, summary, importance, access_count, last_accessed_at)
    VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
  `);
  stmt.run(memory.groupId || null, memory.userId || null, memory.summary, memory.importance);
}
}