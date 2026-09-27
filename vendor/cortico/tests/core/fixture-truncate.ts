import * as actual from '../../src/core/truncate.ts';
import { messages, records } from './fixture-protocol.ts';
import type { ChatMessage } from './fixture-types.ts';

export { FOLD_THRESHOLD } from '../../src/core/truncate.ts';
export { FOLD_PLACEHOLDER, FOLD_ARGS_PLACEHOLDER, OVERSIZE_PLACEHOLDER } from '../../src/core/markers.ts';
export function rebuildTail(entries: ChatMessage[], budget: number): ChatMessage[] { return messages(actual.rebuildTail(records(entries), budget)); }
export function fixPairing(entries: ChatMessage[]): ChatMessage[] { return messages(actual.fixPairing(records(entries))); }
export function validatePairing(entries: ChatMessage[]): string[] { return actual.validatePairing(records(entries)); }
export function closeDanglingCalls(entries: ChatMessage[]): ChatMessage[] { return messages(actual.closeDanglingCalls(records(entries))); }
