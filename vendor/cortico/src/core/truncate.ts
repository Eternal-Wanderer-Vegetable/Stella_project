/** Context compaction retains Item identity and repairs function-call pairing across response boundaries. */
import { functionResult, withText, type ContextRecord } from '../protocol/open-responses/context.ts';
import { hasRole, textOf } from '../protocol/open-responses/context-helpers.ts';
import {
  FOLD_ARGS_PLACEHOLDER,
  FOLD_PLACEHOLDER,
  MISSING_RESULT,
  OVERSIZE_PLACEHOLDER,
  PENDING_IN_MAIN_THREAD,
} from './markers.ts';
import { estimateMessagesTokens } from './util.ts';

/** 回执与入参超过这么多字符就折叠成记号 */
export const FOLD_THRESHOLD = 600;

function responseKey(entry: ContextRecord): string | null {
  return entry.context.responseId ?? null;
}

export function rebuildTail(
  tail: readonly ContextRecord[],
  budgetTokens: number,
  estimate: (records: readonly ContextRecord[]) => number = estimateMessagesTokens,
): ContextRecord[] {
  if (!tail.length) return [];
  const calls = new Set(tail.flatMap(({ item }) => item.type === 'function_call' ? [item.call_id] : []));
  const folded = tail.map(entry => {
    const item = entry.item;
    if (item.type === 'function_call' && item.arguments.length > FOLD_THRESHOLD) {
      return { ...entry, item: { ...item, arguments: FOLD_ARGS_PLACEHOLDER } };
    }
    if (item.type === 'function_call_output' && calls.has(item.call_id) && textOf(entry).length > FOLD_THRESHOLD) {
      return withText(entry, FOLD_PLACEHOLDER);
    }
    return entry;
  });
  const oversized = new Set<number>();
  let total = 0;
  let budgetStart = 0;
  for (let index = folded.length - 1; index >= 0; index--) {
    const tokens = estimate([folded[index]]);
    if (tokens > budgetTokens && index < folded.length - 1) { oversized.add(index); continue; }
    if (total + tokens > budgetTokens && total > 0) { budgetStart = index + 1; break; }
    total += tokens;
  }
  let start = folded.findIndex((entry, index) => index >= budgetStart && hasRole(entry, 'user'));
  if (start < 0) start = budgetStart;
  // A retained response begins at its first Item, including reasoning before its calls.
  const key = responseKey(folded[start]);
  while (start > 0 && key !== null && responseKey(folded[start - 1]) === key) start--;
  const kept = folded.slice(start).map((entry, offset) => {
    if (!oversized.has(start + offset)) return entry;
    const item = entry.item;
    if (item.type === 'message' || item.type === 'function_call_output') return withText(entry, OVERSIZE_PLACEHOLDER);
    if (item.type === 'reasoning') return { ...entry, item: { type: 'reasoning' as const, id: item.id ?? 'rs_folded', summary: [{ type: 'summary_text' as const, text: OVERSIZE_PLACEHOLDER }] } };
    return entry;
  });
  return fixPairing(kept);
}

/** Multiple calls, reasoning Items and commentary within one response share a pairing scope. */
export function fixPairing(records: readonly ContextRecord[]): ContextRecord[] {
  const out: ContextRecord[] = [];
  const open = new Set<string>();
  let group: string | null = null;
  const close = (): void => {
    for (const id of open) out.push(functionResult(id, MISSING_RESULT));
    open.clear();
  };
  for (const entry of records) {
    const item = entry.item;
    if (item.type === 'function_call_output') {
      if (open.delete(item.call_id)) out.push(entry);
      continue;
    }
    const key = responseKey(entry);
    if (hasRole(entry, 'user') || hasRole(entry, 'system') || hasRole(entry, 'developer') || (key !== null && group !== null && key !== group)) close();
    if (key !== null) group = key;
    out.push(entry);
    if (item.type === 'function_call') open.add(item.call_id);
  }
  close();
  return out;
}

export function validatePairing(records: readonly ContextRecord[]): string[] {
  const problems: string[] = [];
  const open = new Set<string>();
  const seen = new Set<string>();
  let group: string | null = null;
  const close = (): void => {
    if (open.size) problems.push(`Unanswered function calls: ${[...open].join(',')}`);
    open.clear();
  };
  records.forEach((entry, index) => {
    const item = entry.item;
    if (item.type === 'function_call_output') {
      if (!open.delete(item.call_id)) problems.push(`#${index} orphan function output: ${item.call_id}`);
      return;
    }
    const key = responseKey(entry);
    if (hasRole(entry, 'user') || hasRole(entry, 'system') || hasRole(entry, 'developer') || (key !== null && group !== null && key !== group)) close();
    if (key !== null) group = key;
    if (item.type === 'function_call') {
      if (seen.has(item.call_id)) problems.push(`#${index} duplicate call_id: ${item.call_id}`);
      seen.add(item.call_id);
      open.add(item.call_id);
    }
  });
  close();
  return problems;
}

export function closeDanglingCalls(records: readonly ContextRecord[]): ContextRecord[] {
  const open = new Set<string>();
  for (const { item } of records) {
    if (item.type === 'function_call') open.add(item.call_id);
    if (item.type === 'function_call_output') open.delete(item.call_id);
  }
  return [...records, ...[...open].map(id => functionResult(id, PENDING_IN_MAIN_THREAD))];
}
