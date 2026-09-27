import { describe, expect, it } from 'vitest';
import { createResponse, type FunctionCall, type Response, type StreamEvent } from '../../src/protocol/open-responses/index.ts';
import { ResponseAccumulator } from '../../src/protocol/open-responses/stream.ts';

function stream() {
  const accumulator = new ResponseAccumulator();
  const response = createResponse('r1', { model: 'fixture' }, 0);
  let seq = 0;
  const send = (event: Omit<StreamEvent, 'sequence_number'> | Record<string, unknown>) =>
    accumulator.accept({ ...event, sequence_number: seq++ } as StreamEvent);
  send({ type: 'response.created', response });
  return { accumulator, response, send };
}

describe('Open Responses stream lifecycle', () => {
  it('rejects an event outside the pinned protocol before changing Items', () => {
    const { accumulator, send } = stream();
    expect(() => send({ type: 'response.reasoning_text.delta', output_index: 0, content_index: 0, delta: 'x' })).toThrow('Unknown Open Responses event');
    expect(accumulator.snapshot()?.output).toEqual([]);
  });
  it('keeps interleaved item order, phase, reasoning and final response usage', () => {
    const { accumulator, response, send } = stream();
    const call: FunctionCall = { type: 'function_call', id: 'fc1', call_id: 'c1', name: 'read', arguments: '', status: 'in_progress' };
    const reasoning = { type: 'reasoning', id: 'rs1', summary: [], encrypted_content: 'opaque' } as const;
    send({ type: 'response.output_item.added', output_index: 0, item: reasoning });
    send({ type: 'response.output_item.added', output_index: 1, item: call });
    send({ type: 'response.function_call_arguments.delta', output_index: 1, item_id: 'fc1', delta: '{"path":' });
    send({ type: 'response.output_item.done', output_index: 0, item: reasoning });
    send({ type: 'response.function_call_arguments.delta', output_index: 1, item_id: 'fc1', delta: '"a"}' });
    const completeCall = { ...call, arguments: '{"path":"a"}', status: 'completed' as const };
    send({ type: 'response.function_call_arguments.done', output_index: 1, item_id: 'fc1', arguments: completeCall.arguments });
    send({ type: 'response.output_item.done', output_index: 1, item: completeCall });
    const message = { type: 'message', id: 'm1', role: 'assistant', status: 'in_progress', phase: 'commentary', content: [] };
    send({ type: 'response.output_item.added', output_index: 2, item: message });
    send({ type: 'response.content_part.added', output_index: 2, item_id: 'm1', content_index: 0, part: { type: 'output_text', text: '', annotations: [] } });
    send({ type: 'response.output_text.delta', output_index: 2, item_id: 'm1', content_index: 0, delta: 'Read it' });
    send({ type: 'response.output_text.done', output_index: 2, item_id: 'm1', content_index: 0, text: 'Read it' });
    const part = { type: 'output_text', text: 'Read it', annotations: [] };
    send({ type: 'response.content_part.done', output_index: 2, item_id: 'm1', content_index: 0, part });
    const completeMessage = { ...message, status: 'completed', content: [part] };
    send({ type: 'response.output_item.done', output_index: 2, item: completeMessage });
    const final = { ...response, status: 'completed', completed_at: 1, output: [reasoning, completeCall, completeMessage], usage: { input_tokens: 10, output_tokens: 4, total_tokens: 14, input_tokens_details: { cached_tokens: 2 }, output_tokens_details: { reasoning_tokens: 1 } } } as Response;
    send({ type: 'response.completed', response: final });
    expect(accumulator.finish()).toEqual(final);
  });

  it('preserves incomplete arguments without pretending transport EOF completed them', () => {
    const { accumulator, response, send } = stream();
    const item = { type: 'function_call', id: 'f', call_id: 'c', name: 'read', status: 'in_progress', arguments: '' };
    send({ type: 'response.output_item.added', output_index: 0, item });
    send({ type: 'response.function_call_arguments.delta', output_index: 0, item_id: 'f', delta: '{' });
    expect(() => accumulator.finish()).toThrow('before a terminal response');
    const partial = { ...item, status: 'incomplete', arguments: '{' };
    send({ type: 'response.output_item.done', output_index: 0, item: partial });
    send({ type: 'response.incomplete', response: { ...response, status: 'incomplete', incomplete_details: { reason: 'max_output_tokens' }, output: [partial] } });
    expect(accumulator.finish()).toMatchObject({ status: 'incomplete', incomplete_details: { reason: 'max_output_tokens' }, output: [{ arguments: '{', status: 'incomplete' }] });
  });

  it('rejects final argument disagreement before a tool can be dispatched', () => {
    const { send } = stream();
    const item = { type: 'function_call', id: 'f', call_id: 'c', name: 'read', arguments: '', status: 'in_progress' };
    send({ type: 'response.output_item.added', output_index: 0, item });
    send({ type: 'response.function_call_arguments.delta', output_index: 0, item_id: 'f', delta: '{"x":1}' });
    expect(() => send({ type: 'response.output_item.done', output_index: 0, item: { ...item, arguments: '{"x":2}', status: 'completed' } })).toThrow('arguments disagree');
  });

  it('rejects a second done and a terminal response that changes a completed item', () => {
    const { response, send } = stream();
    const item = { type: 'function_call', id: 'f', call_id: 'c', name: 'read', arguments: '{}', status: 'completed' };
    send({ type: 'response.output_item.added', output_index: 0, item });
    send({ type: 'response.output_item.done', output_index: 0, item });
    expect(() => send({ type: 'response.output_item.done', output_index: 0, item })).toThrow('after output_item.done');
    expect(() => send({ type: 'response.completed', response: { ...response, status: 'completed', output: [{ ...item, name: 'write' }] } })).toThrow('changed a closed item');
  });

  it('retains failed response usage and isolates snapshots from consumers', () => {
    const { accumulator, response, send } = stream();
    const usage = { input_tokens: 10, output_tokens: 3, total_tokens: 13, input_tokens_details: { cached_tokens: 0 }, output_tokens_details: { reasoning_tokens: 3 } };
    send({ type: 'response.failed', response: { ...response, status: 'failed', error: { type: 'model_error', code: 'overloaded', message: 'busy', param: null }, usage } });
    const read = accumulator.finish();
    read.usage!.input_tokens = 0;
    expect(accumulator.finish().usage).toEqual(usage);
    expect(() => send({ type: 'response.in_progress', response })).toThrow('after terminal');
  });
});
