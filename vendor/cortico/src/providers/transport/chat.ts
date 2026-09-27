import type { ModelSpec, ToolSchema, Logger } from '../../core/types.ts';
import type { NativeChatMessage } from './native-types.ts';
import { BaseProvider } from '../base.ts';
import type { Request } from '../../protocol/open-responses/index.ts';
import { GenerationError, type GenerateOptions, type Generation, type ResponseClient } from '../../core/generation.ts';
import { generate } from './response-http.ts';
import { ChatResponseAssembly, parseChatResponse, type ResponseAssembly } from './response-assembly.ts';
import { nativeChatInput, requestSpec, requestTools } from './native-input.ts';

const INFLIGHT_ALERT_WINDOW_MS = 60_000;
const INFLIGHT_ALERT_MIN = 2;

export interface StreamFailureInfo {
  model: string;
  /** 调用方的 session 声明 id;调用方没报就缺席。 */
  role?: string;
  /** 同一 (model, role) 上连续第几次在途生成失败(成功即清零)。 */
  streak: number;
  /** Elapsed time from stream start to failure, in milliseconds. */
  elapsedMs: number;
  /** LLMError.status;0 = 流内失败,不是 HTTP 码。 */
  status: number;
  requestId: string | null;
  /** 完整的上游失败事件，用于诊断。 */
  body: string;
  message: string;
  diagnose: ResponseClient['respond'];
}

/** 传输适配器对流内失败的处理决定。 */
export interface StreamFailureVerdict {
  /** false 表示停止重试并抛出本次错误。 */
  retry: boolean;
  /** 可选的诊断说明，追加到通用断流日志。 */
  note?: string;
}
export abstract class OpenAIHttpClient extends BaseProvider {
  protected buildResponseBody(request: Request, options: GenerateOptions): Record<string, unknown> {
    const body = this.buildBody(requestSpec(request, options), nativeChatInput(request, options), requestTools(request), options.sessionId);
    for (const key of ['top_p', 'presence_penalty', 'frequency_penalty', 'parallel_tool_calls'] as const) if (request[key] !== undefined) body[key] = request[key];
    if (request.tool_choice != null) {
      const choice = request.tool_choice;
      if (typeof choice === 'string') body.tool_choice = choice;
      else if (choice.type === 'function') body.tool_choice = { type: 'function', function: { name: choice.name } };
      else throw new Error('Native Chat provider cannot map this tool_choice');
    }
    if (request.text?.format) {
      const format = request.text.format;
      body.response_format = format.type === 'json_schema' ? { type: 'json_schema', json_schema: { name: format.name, schema: format.schema, description: format.description, strict: format.strict } } : format;
    }
    if (options.onEvent) this.applyStreamFlags(body);
    return body;
  }

  protected responseAssembly(request: Request): ResponseAssembly { return new ChatResponseAssembly(request); }

  protected parseResponse(raw: unknown, request: Request): ReturnType<typeof parseChatResponse> { return parseChatResponse(raw, request); }

  async respond(request: Request, options: GenerateOptions = {}): Promise<Generation> {
    const origin = options.origin ?? { instance: this.constructor.name, module: this.constructor.name,
      model: request.model ?? '', compatibilityDomain: this.baseUrl };
    const key = OpenAIHttpClient.streakKey(request.model ?? '', options.role);
    return generate(request, options, origin, {
      url: `${this.baseUrl}${this.chatPath}`, body: this.buildResponseBody(request, options),
      headers: () => this.headers(), refresh: () => this.onAuthError(),
      assembly: () => this.responseAssembly(request), parse: raw => this.parseResponse(raw, request), log: this.log,
      succeeded: () => { if (!options.diagnostic) this.inflightStreak.delete(key); },
      failure: async (info, record) => {
        const streak = (this.inflightStreak.get(key) ?? 0) + 1;
        this.inflightStreak.set(key, streak);
        this.noteInflightFailure({ ...info, streak });
        const verdict = await this.judgeStreamFailure({ ...info, streak, diagnose: async (probe, probeOptions) => {
          try {
            const signals = [options.signal, probeOptions?.signal].filter((signal): signal is AbortSignal => Boolean(signal));
            const result = await this.respond(probe, { ...options, onEvent: undefined, context: undefined, ...probeOptions,
              signal: signals.length ? AbortSignal.any(signals) : undefined, diagnostic: true });
            record(result.attempts);
            return result;
          } catch (error) {
            if (error instanceof GenerationError) record(error.attempts);
            throw error;
          }
        } });
        this.log.warn('LLM 生成阶段中断：连续失败 ' + streak + ' 次，开流后 ' + (info.elapsedMs / 1000).toFixed(1) + ' 秒' + (verdict.note ? ';' + verdict.note : ''), info);
        return verdict.retry;
      },
    });
  }
  protected baseUrl: string;
  protected log: Logger;
  /** 相对 baseUrl 的端点路径，可由适配器覆盖。 */
  protected chatPath = '/chat/completions';
  /** 同一 (model, role) 上的连续在途生成失败数;成功即清零。 */
  private inflightStreak = new Map<string, number>();
  /** 在途生成失败的时刻表,只用于频次告警(见 noteInflightFailure)。 */
  private inflightFailAt: number[] = [];

  constructor(baseUrl: string, log: Logger) {
    super();
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.log = log;
  }

  private static streakKey(model: string, role?: string): string {
    return `${model}::${role ?? ''}`;
  }

  /** 流内失败后调用；适配器可禁用该次重试，默认允许。 */
  protected async judgeStreamFailure(_info: StreamFailureInfo): Promise<StreamFailureVerdict> {
    return { retry: true };
  }

  /**
   * 记录在途生成失败，窗口内达到密度门槛时发送操作员告警；仅观察，不自动处置上游或会话。
   */
  private noteInflightFailure(info: Omit<StreamFailureInfo, 'diagnose'>): void {
    const now = Date.now();
    this.inflightFailAt.push(now);
    const cutoff = now - INFLIGHT_ALERT_WINDOW_MS;
    while (this.inflightFailAt.length > 0 && this.inflightFailAt[0] < cutoff) this.inflightFailAt.shift();
    if (this.inflightFailAt.length < INFLIGHT_ALERT_MIN) return;
    this.log.warn(
      `[告警] ${INFLIGHT_ALERT_WINDOW_MS / 1000} 秒内第 ${this.inflightFailAt.length} 次在途生成失败` +
        `；请检查请求错误与上游状态`,
      {
        model: info.model,
        ...(info.role ? { role: info.role } : {}),
        status: info.status,
        ...(info.requestId ? { requestId: info.requestId } : {}),
      },
    );
  }

  /** 方言请求体(不含 stream 字段;流式路径自行追加)。 */
  protected abstract buildBody(
    spec: ModelSpec,
    messages: NativeChatMessage[],
    tools?: ToolSchema[],
    sessionId?: string,
  ): Record<string, unknown>;

  /** 每次请求的 HTTP 头(含鉴权,若有)。可异步:OAuth 方言在这里等一次临期刷新。 */
  protected abstract headers(): Record<string, string> | Promise<Record<string, string>>;

  /** 401/403 后调用，返回 true 时刷新后重试一次；默认返回 false。 */
  protected async onAuthError(): Promise<boolean> {
    return false;
  }

  /** 请求体上开流的字段。缺省是 OpenAI chat/completions 的写法。 */
  protected applyStreamFlags(body: Record<string, unknown>): void {
    body.stream = true;
    body.stream_options = { include_usage: true };
  }

}
