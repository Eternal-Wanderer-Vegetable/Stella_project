/**
 * OpenRouterVLMClient:QQ World 所有的辅助视觉客户端，使用 OpenRouter 的 OpenAI 兼容
 * `/chat/completions`；模型与端点不进入 core 契约。
 * 以下外部接口行为是对 OpenRouter 的实测结论(非文档承诺),改这个客户端时别按文档想当然:
 * - reasoning 关闭用 OpenRouter 统一参数 { reasoning: { enabled: false } },被接受且生效
 *   (响应message无reasoning字段,usage无reasoning_tokens计数)
 * - data URL 图片输入(image_url.url = "data:image/png;base64,...")可用
 * - 多轮会话可用:assistant回复(纯文本)接回messages再追问,模型能引用上一轮内容
 * - usage 只有 prompt_tokens/completion_tokens(无DeepSeek的cache字段)→ cache计数填0
 */
import type { Logger, LLMUsage } from '../../core/types.ts';
import { nullLogger } from '../../core/util.ts';

/** OpenAI兼容多模态内容块(带图的user消息用数组形式content) */
export type VLMContentPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } };

export interface VLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string | VLMContentPart[];
}

/**
 * 辅助小VLM客户端(依赖注入点:测试用FakeVLM替换)。
 * 模型/baseUrl/maxTokens/thinking关闭等参数在构造时固定,chat只管对话。
 */
export interface VLMClient {
  chat(messages: VLMMessage[]): Promise<{ text: string; usage: LLMUsage }>;
}

export class VLMError extends Error {
  status: number;
  body: string;
  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = 'VLMError';
    this.status = status;
    this.body = body;
  }
}

interface VLMClientOptions {
  baseUrl: string;
  model: string;
  maxTokens: number;
  timeoutMs: number;
}

/** 纯函数:拼请求体(单测覆盖;reasoning固定关闭,多模态content数组原样透传) */
export function buildVLMRequestBody(
  model: string,
  maxTokens: number,
  messages: VLMMessage[],
): Record<string, unknown> {
  return {
    model,
    messages,
    max_tokens: maxTokens,
    reasoning: { enabled: false },
  };
}

interface RawUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
}

/** OpenRouter响应无DeepSeek的cache字段→填0;usage整体缺失→全0 */
export function mapVLMUsage(u: RawUsage | undefined): LLMUsage {
  return {
    promptTokens: u?.prompt_tokens ?? 0,
    completionTokens: u?.completion_tokens ?? 0,
    cacheHitTokens: 0,
    cacheMissTokens: 0,
  };
}

const RETRY_DELAYS_MS = [1000, 4000, 10000];

export class OpenRouterVLMClient implements VLMClient {
  private apiKey: string;
  private cfg: VLMClientOptions;
  private log: Logger;

  constructor(apiKey: string, cfg: VLMClientOptions, log: Logger = nullLogger()) {
    this.apiKey = apiKey;
    this.cfg = { ...cfg, baseUrl: cfg.baseUrl.replace(/\/+$/, '') };
    this.log = log;
  }

  async chat(messages: VLMMessage[]): Promise<{ text: string; usage: LLMUsage }> {
    const body = JSON.stringify(buildVLMRequestBody(this.cfg.model, this.cfg.maxTokens, messages));
    let lastErr: unknown;
    for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt++) {
      if (attempt > 0) {
        const delay = RETRY_DELAYS_MS[attempt - 1];
        this.log.warn(`VLM请求重试 #${attempt},等待${delay}ms`, { err: String(lastErr) });
        await new Promise((r) => setTimeout(r, delay));
      }
      const ac = new AbortController();
      const timer = setTimeout(() => ac.abort(), this.cfg.timeoutMs);
      try {
        const res = await fetch(`${this.cfg.baseUrl}/chat/completions`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${this.apiKey}`,
          },
          body,
          signal: ac.signal,
        });
        const text = await res.text();
        if (!res.ok) {
          const err = new VLMError(`VLM API ${res.status}`, res.status, text);
          // 429/5xx可重试;其他4xx直接抛
          if (res.status === 429 || res.status >= 500) {
            lastErr = err;
            continue;
          }
          throw err;
        }
        const data = JSON.parse(text) as {
          choices?: Array<{ message?: { content?: string | null } }>;
          usage?: RawUsage;
        };
        const raw = data.choices?.[0]?.message;
        if (!raw) throw new VLMError('VLM响应缺choices[0].message', res.status, text.slice(0, 2000));
        return { text: raw.content ?? '', usage: mapVLMUsage(data.usage) };
      } catch (e) {
        if (e instanceof VLMError && e.status !== 429 && e.status < 500) throw e;
        // 网络错误/超时/可重试的VLMError
        lastErr = e;
        continue;
      } finally {
        clearTimeout(timer);
      }
    }
    if (lastErr instanceof VLMError) throw lastErr;
    throw new VLMError(`VLM请求失败(重试${RETRY_DELAYS_MS.length}次后放弃): ${String(lastErr)}`, 0, '');
  }
}
