import type { FixtureMessage } from './fixture-messages.ts';
import type { LLMUsage } from '../../src/core/types.ts';

/** Test scenario notation; production boundaries use standard Items and events. */
export type ChatMessage = FixtureMessage;
export type ToolCallPayload = NonNullable<FixtureMessage['tool_calls']>[number];
export type LLMDelta =
  | { type: 'content'; text: string }
  | { type: 'reasoning'; text: string }
  | { type: 'tool_call.begin'; index: number; id: string; name: string }
  | { type: 'tool_call.delta'; index: number; argsFragment: string }
  | { type: 'tool_call.end'; index: number };
export interface LLMChatOptions {
  onDelta?: (delta: LLMDelta) => void;
  signal?: AbortSignal;
  role?: string;
  sessionId?: string;
}
export interface LLMResult { message: ChatMessage; usage?: LLMUsage; }
