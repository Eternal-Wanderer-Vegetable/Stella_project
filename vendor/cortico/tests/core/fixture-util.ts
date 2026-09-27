export * from '../../src/core/util.ts';
import * as actual from '../../src/core/util.ts';
import type { ChatMessage } from './fixture-types.ts';

import type { ContextRecord } from '../../src/protocol/open-responses/context.ts';
import { records } from './fixture-protocol.ts';
export function estimateMessagesTokens(entries: readonly ChatMessage[] | readonly ContextRecord[]): number { return actual.estimateMessagesTokens(records(entries)); }
export function prefixFingerprint(entries: readonly ChatMessage[] | readonly ContextRecord[], count?: number): string { return actual.prefixFingerprint(records(entries), count); }
