import type { EventEnvelope } from '../../core/types.ts';

export interface Conv {
  kind: 'group' | 'private';
  id: number;
}

export function parseConversationAddress(raw: unknown): Conv | null {
  if (typeof raw !== 'string') return null;
  const match = /^(group|private):(\d+)$/i.exec(raw.trim());
  if (!match) return null;
  return {
    kind: match[1].toLowerCase() as Conv['kind'],
    id: Number(match[2]),
  };
}

export function sameConversation(left: Conv, right: Conv): boolean {
  return left.kind === right.kind && Number(left.id) === Number(right.id);
}

export function eventInConversation(event: EventEnvelope, conversation: Conv): boolean {
  const value = event.meta?.conv as Partial<Conv> | undefined;
  return (
    value?.kind === conversation.kind &&
    Number(value.id) === conversation.id
  );
}
