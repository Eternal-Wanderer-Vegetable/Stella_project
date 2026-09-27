import { renderHandoffNote as render } from '../../bots/cormini/persona/handoffNote.ts';
import type { ChatMessage } from '../core/fixture-types.ts';

import { records } from '../core/fixture-protocol.ts';
export * from '../../bots/cormini/persona/handoffNote.ts';
export function renderHandoffNote(snapshot: ChatMessage[], options: Parameters<typeof render>[1]): ReturnType<typeof render> {
  return render(records(snapshot), options);
}
