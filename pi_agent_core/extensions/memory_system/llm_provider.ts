export interface LLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface LLMOptions {
  temperature?: number;
  responseFormatJson?: boolean;
}

export interface ILLMProvider {
  name: string;
  generate(messages: LLMMessage[], options?: LLMOptions): Promise<string>;
}

/**
 * 1. 在线 API 提供者 (通用 OpenAI 兼容接口，可接 DeepSeek / GPT-4o / Claude Agent 等)
 */
export class OnlineOpenAILMProvider implements ILLMProvider {
  name = 'Online-LLM';
  private apiKey: string;
  private baseUrl: string;
  private model: string;

  constructor(apiKey: string, baseUrl: string = 'https://api.openai.com/v1', model: string = 'gpt-4o-mini') {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl;
    this.model = model;
  }

  async generate(messages: LLMMessage[], options?: LLMOptions): Promise<string> {
    const response = await fetch(`${this.baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages,
        temperature: options?.temperature ?? 0.3,
        ...(options?.responseFormatJson ? { response_format: { type: 'json_object' } } : {}),
      }),
    });

    if (!response.ok) {
      throw new Error(`[OnlineLLM] API 请求失败: ${response.statusText}`);
    }

    const data = await response.json();
    return data.choices[0]?.message?.content || '';
  }
}

/**
 * 2. 本地 SLM 提供者 (通过 LM Studio / Ollama 的 OpenAI 兼容端口)
 */
export class LocalSLMProvider implements ILLMProvider {
  name = 'Local-SLM';
  private endpoint: string;

  constructor(endpoint: string = 'http://localhost:1234/v1/chat/completions') {
    this.endpoint = endpoint;
  }

  async generate(messages: LLMMessage[], options?: LLMOptions): Promise<string> {
    const response = await fetch(this.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages,
        temperature: options?.temperature ?? 0.2,
      }),
    });

    if (!response.ok) {
      throw new Error(`[LocalSLM] 本地推理失败: ${response.statusText}`);
    }

    const data = await response.json();
    return data.choices[0]?.message?.content || '';
  }
}