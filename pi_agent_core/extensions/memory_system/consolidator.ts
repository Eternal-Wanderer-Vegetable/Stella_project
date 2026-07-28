import { MemoryRepository } from './db';
import { ILLMProvider, LLMMessage } from './llm_provider';
import { MEMORY_ANALYSIS_SYSTEM_PROMPT } from './consolidator_prompt';

export class MemoryConsolidator {
  private repo: MemoryRepository;
  private llm: ILLMProvider;

  constructor(repo: MemoryRepository, llmProvider: ILLMProvider) {
    this.repo = repo;
    this.llm = llmProvider;
  }

  /**
   * 异步批处理：对一段无序聊天记录进行分析并落库
   */
  async processChatBatch(groupId: string, rawMessages: { userId: string; nickname?: string; text: string }[]) {
    if (rawMessages.length === 0) return;

    // 1. 拼装待分析文本
    const chatText = rawMessages
      .map(m => `[User: ${m.userId}${m.nickname ? `(${m.nickname})` : ''}]: ${m.text}`)
      .join('\n');

    const messages: LLMMessage[] = [
      { role: 'system', content: MEMORY_ANALYSIS_SYSTEM_PROMPT },
      { role: 'user', content: `请分析以下来自群组 [${groupId}] 的对话记录：\n\n${chatText}` }
    ];

    try {
      // 2. 调用配置的 LLM（无论是本地 SLM 还是在线 LLM）
      const rawResult = await this.llm.generate(messages, { responseFormatJson: true });
      
      // 清理可能存在的 markdown 代码块包裹
      const cleanJsonStr = rawResult.replace(/```json/g, '').replace(/```/g, '').trim();
      const analysis = JSON.parse(cleanJsonStr);

      // 3. 落库：更新用户画像 (user_profiles)
      if (Array.isArray(analysis.user_profile_updates)) {
        for (const userUpdate of analysis.user_profile_updates) {
          this.repo.upsertUserProfile({
            userId: userUpdate.user_id,
            nickname: userUpdate.nickname,
            personalityTraits: userUpdate.personality_traits,
            agentAttitude: userUpdate.agent_attitude,
          });
        }
      }

      // 4. 落库：更新短期焦点 (short_term_context)
      if (analysis.short_term_context) {
        this.repo.upsertShortTermContext({
          groupId,
          activeSummary: analysis.short_term_context.active_summary,
          pendingTopic: analysis.short_term_context.pending_topic,
        });
      }

      // 5. 落库：追加长期记忆 (long_term_memories)
      if (Array.isArray(analysis.long_term_memories)) {
        for (const memory of analysis.long_term_memories) {
          if (memory.importance >= 5) { // 过滤掉低重要度信息
            this.repo.addLongTermMemory({
              groupId: memory.group_id || groupId,
              userId: memory.user_id || undefined,
              summary: memory.summary,
              importance: memory.importance,
            });
          }
        }
      }

      console.log(`✅ [Memory Consolidator] 借助 [${this.llm.name}] 成功完成批处理与数据落库`);

    } catch (error) {
      console.error(`❌ [Memory Consolidator] 异步整理记忆失败:`, error);
    }
  }
}