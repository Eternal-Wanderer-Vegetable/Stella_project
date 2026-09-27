import type { OutputItem, Response, StreamEvent } from './index.ts';
import { STREAM_EVENT_TYPES } from './generated.ts';

export class ResponseProtocolError extends Error {
  constructor(message: string) { super(message); this.name = 'ResponseProtocolError'; }
}

type Part = { type: string; text?: string; refusal?: string; annotations?: unknown[] };
type MutableItem = { id: string; type: string; status?: string; call_id?: string; name?: string; arguments?: string; content?: Part[]; summary?: Part[] };

function check(condition: unknown, message: string): asserts condition {
  if (!condition) throw new ResponseProtocolError(message);
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

/** One attempt's standard event stream. Transport termination is checked by finish(). */
export class ResponseAccumulator {
  private response: Response | null = null;
  private readonly items = new Map<number, OutputItem>();
  private readonly ids = new Set<string>();
  private readonly closed = new Set<number>();
  private readonly closedParts = new Set<string>();
  private lastSequence = -1;
  private terminal = false;

  accept(event: StreamEvent): void {
    check(event && STREAM_EVENT_TYPES.has(event.type), 'Unknown Open Responses event type');
    check(!this.terminal, 'Event after terminal response');
    check(Number.isInteger(event.sequence_number) && event.sequence_number > this.lastSequence, 'Non-increasing event sequence');
    this.lastSequence = event.sequence_number;
    if (event.type === 'response.created') {
      check(this.response === null, 'Duplicate response.created');
      this.response = structuredClone(event.response);
      return;
    }
    check(this.response !== null, 'Event before response.created');
    if ('response' in event) {
      check(event.response.id === this.response.id, 'Response identity changed');
      const terminal = ['response.completed', 'response.incomplete', 'response.failed'].includes(event.type);
      if (terminal) {
        check(event.response.status === event.type.slice('response.'.length), 'Response terminal status disagrees with event');
        check(event.response.output.length === this.items.size, 'Terminal response contains unannounced output items');
        for (const [index, item] of this.items) {
          const final = event.response.output[index];
          check(final?.id === item.id, 'Terminal response changed output order');
          if (this.closed.has(index)) check(canonical(item) === canonical(final), 'Terminal response changed a closed item');
        }
        this.terminal = true;
      }
      this.response = structuredClone(event.response);
      return;
    }
    if (event.type === 'error') return;
    if (event.type === 'response.output_item.added') {
      check(event.item !== null, 'Missing output item');
      check(Number.isInteger(event.output_index) && event.output_index >= 0, 'Invalid output index');
      check(!this.items.has(event.output_index) && !this.ids.has(event.item.id), 'Duplicate output item');
      this.items.set(event.output_index, structuredClone(event.item));
      this.ids.add(event.item.id);
      return;
    }
    const item = this.items.get(event.output_index) as MutableItem | undefined;
    check(item, 'Event refers to an unknown output item');
    check(!this.closed.has(event.output_index), 'Update after output_item.done');
    if (event.type === 'response.output_item.done') {
      check(event.item !== null, 'Missing output item');
      check(event.item.id === item.id && event.item.type === item.type, 'Item identity changed');
      if (item.type === 'function_call') {
        check(event.item.type === 'function_call' && event.item.arguments === item.arguments, 'Final function arguments disagree with deltas');
        check(event.item.call_id === item.call_id && event.item.name === item.name, 'Final function identity changed');
      }
      for (const field of ['content', 'summary'] as const) {
        if (item[field]?.length) check(canonical(item[field]) === canonical((event.item as MutableItem)[field]), `Final ${field} disagrees with deltas`);
      }
      check(!('status' in event.item) || event.item.status !== 'in_progress', 'Done item is still in progress');
      this.items.set(event.output_index, structuredClone(event.item));
      this.closed.add(event.output_index);
      return;
    }
    check(event.item_id === item.id, 'Item ID disagrees with output index');
    if (event.type === 'response.function_call_arguments.delta') {
      check(item.type === 'function_call', 'Arguments on a non-function item');
      check(!this.closedParts.has(`${item.id}/arguments`), 'Arguments after arguments.done');
      item.arguments = (item.arguments ?? '') + event.delta;
      return;
    }
    if (event.type === 'response.function_call_arguments.done') {
      check(item.type === 'function_call' && item.arguments === event.arguments, 'Final function arguments disagree with deltas');
      const key = `${item.id}/arguments`;
      check(!this.closedParts.has(key), 'Duplicate arguments.done');
      this.closedParts.add(key);
      return;
    }
    const summary = 'summary_index' in event;
    const index = summary ? event.summary_index : 'content_index' in event ? event.content_index : -1;
    check(Number.isInteger(index) && index >= 0, 'Invalid content index');
    const parts = summary ? (item.summary ??= []) : (item.content ??= []);
    const key = `${item.id}/${summary ? 'summary' : 'content'}/${index}`;
    check(!this.closedParts.has(key), 'Update after content part completion');
    if (event.type === 'response.content_part.added' || event.type === 'response.reasoning_summary_part.added') {
      check(parts[index] === undefined, 'Duplicate content part');
      parts[index] = structuredClone(event.part) as Part;
      return;
    }
    const part = parts[index];
    check(part, 'Delta before content part');
    if (event.type === 'response.content_part.done' || event.type === 'response.reasoning_summary_part.done') {
      check(canonical(part) === canonical(event.part), 'Final content part disagrees with deltas');
      this.closedParts.add(key);
      return;
    }
    if (event.type === 'response.output_text.annotation.added') {
      (part.annotations ??= []).push(structuredClone(event.annotation));
      return;
    }
    const field = event.type.startsWith('response.refusal.') ? 'refusal' : 'text';
    const textKey = `${key}/${field}`;
    if ('delta' in event) {
      check(!this.closedParts.has(textKey), 'Text delta after text.done');
      part[field] = (part[field] ?? '') + event.delta;
    } else {
      const final = 'text' in event ? event.text : 'refusal' in event ? event.refusal : undefined;
      check(final !== undefined && part[field] === final, 'Final text disagrees with deltas');
      check(!this.closedParts.has(textKey), 'Duplicate text.done');
      this.closedParts.add(textKey);
    }
  }

  snapshot(): Response | null {
    if (!this.response) return null;
    if (this.terminal) return structuredClone(this.response);
    return { ...structuredClone(this.response), output: [...this.items.entries()].sort(([a], [b]) => a - b).map(([, item]) => structuredClone(item)) };
  }

  finish(): Response {
    check(this.terminal, 'Transport ended before a terminal response');
    return this.snapshot()!;
  }
}
