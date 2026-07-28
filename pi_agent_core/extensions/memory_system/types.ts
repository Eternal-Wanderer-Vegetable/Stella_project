export interface UserProfile {
  userId: string;
  nickname?: string;
  personalityTraits: string; // 性格特点与标签
  agentAttitude: string;     // Bot 对该用户的态度/关系定位
  interactionCount: number;
  updatedAt: string;
}

export interface ShortTermContext {
  groupId: string;
  activeSummary: string;     // 已确认的近期摘要
  pendingTopic: string;      // 跨边界/进行中的话题
  updatedAt: string;
}

export interface LongTermMemory {
  id: number;
  groupId?: string;
  userId?: string;
  summary: string;
  importance: number;        // 1~10 重要程度
  accessCount: number;
  lastAccessedAt: string;
}