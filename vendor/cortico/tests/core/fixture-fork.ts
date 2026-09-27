import { runForkLoop as run, type ForkLoopOptions } from '../../src/core/fork.ts';
import { adaptClient, records, messages, type FixtureClient } from './fixture-protocol.ts';
import type { ChatMessage } from './fixture-types.ts';

export async function runForkLoop(options: Omit<ForkLoopOptions, 'llm' | 'messages' | 'observeMessages'> & {
  llm: FixtureClient | ForkLoopOptions['llm']; messages: ChatMessage[]; observeMessages?: (messages: ChatMessage[]) => void;
}): Promise<string> {
  return run({ ...options, llm: adaptClient(options.llm), messages: records(options.messages),
    observeMessages: entries => options.observeMessages?.(messages(entries)) });
}
