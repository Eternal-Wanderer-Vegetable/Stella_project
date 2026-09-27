import type { Schemas } from './generated.ts';
export { OPEN_RESPONSES_VERSION, OPEN_RESPONSES_SCHEMA_SHA256 } from './generated.ts';
export type { Schemas, StreamEvent } from './generated.ts';

export type Response = Schemas['ResponseResource'];
export type Request = Schemas['CreateResponseBody'];
export type InputItem = Schemas['ItemParam'];
export type OutputItem = Schemas['ItemField'];
export type Usage = Schemas['Usage'];
export type FunctionCall = Schemas['FunctionCall'];

/** Initial response fields for adapters whose native API has no response resource. */
export function createResponse(id: string, request: Request, now = Date.now()): Response {
  return {
    id, object: 'response', created_at: Math.floor(now / 1000), completed_at: null,
    status: 'in_progress', incomplete_details: null, model: request.model ?? '',
    previous_response_id: request.previous_response_id ?? null,
    instructions: request.instructions ?? null, output: [], error: null,
    tools: (request.tools ?? []) as Response['tools'],
    tool_choice: (request.tool_choice ?? 'auto') as Response['tool_choice'],
    truncation: request.truncation ?? 'disabled', parallel_tool_calls: request.parallel_tool_calls ?? false,
    text: (request.text ?? { format: { type: 'text' } }) as Response['text'],
    top_p: request.top_p ?? 1, presence_penalty: request.presence_penalty ?? 0,
    frequency_penalty: request.frequency_penalty ?? 0, top_logprobs: request.top_logprobs ?? 0,
    temperature: request.temperature ?? 1,
    reasoning: request.reasoning ? { effort: request.reasoning.effort ?? null, summary: request.reasoning.summary ?? null } : null,
    usage: null,
    max_output_tokens: request.max_output_tokens ?? null, max_tool_calls: request.max_tool_calls ?? null,
    store: request.store ?? false, background: request.background ?? false,
    service_tier: request.service_tier ?? 'default', metadata: request.metadata ?? null,
    safety_identifier: request.safety_identifier ?? null, prompt_cache_key: request.prompt_cache_key ?? null,
  };
}
