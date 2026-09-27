import { SessionLog as StandardSession } from '../../src/core/session.ts';
import type { ChatMessage } from './fixture-types.ts';

import type { ContextRecord } from '../../src/protocol/open-responses/context.ts';
import { messages, records } from './fixture-protocol.ts';

export class SessionLog extends StandardSession {
  get messages(): ChatMessage[] { return messages(this.records); }
  override append(entry: ChatMessage | ContextRecord): void { for (const record of records([entry] as ChatMessage[] | ContextRecord[])) super.append(record); }
  override reset(entries: readonly ChatMessage[] | readonly ContextRecord[]): void { super.reset(records(entries)); }
}
