import { unknownMeters, type TokenMeters } from '../../core/generation.ts';

/** A meter the provider did not report as a finite number stays unknown; the raw usage is kept beside it. */
function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** Native Chat Completions usage, including DeepSeek's explicit cache distribution. */
export function chatMeters(raw: Record<string, any> | null | undefined): TokenMeters {
  if (!raw) return unknownMeters();
  const input = number(raw.prompt_tokens);
  const output = number(raw.completion_tokens);
  const cachedInput = number(raw.prompt_cache_hit_tokens ?? raw.prompt_tokens_details?.cached_tokens);
  const uncachedInput = number(raw.prompt_cache_miss_tokens) ?? (input !== null && cachedInput !== null ? input - cachedInput : null);
  return { input, output, total: number(raw.total_tokens) ?? (input !== null && output !== null ? input + output : null),
    cachedInput, uncachedInput, reasoning: number(raw.completion_tokens_details?.reasoning_tokens), native: structuredClone(raw) };
}

export function responseMeters(raw: Record<string, any> | null | undefined): TokenMeters {
  if (!raw) return unknownMeters();
  const input = number(raw.input_tokens);
  const output = number(raw.output_tokens);
  const cachedInput = number(raw.input_tokens_details?.cached_tokens);
  const uncachedInput = input !== null && cachedInput !== null ? input - cachedInput : null;
  return { input, output, total: number(raw.total_tokens) ?? (input !== null && output !== null ? input + output : null),
    cachedInput, uncachedInput, reasoning: number(raw.output_tokens_details?.reasoning_tokens), native: structuredClone(raw) };
}
