import { Core as StandardHarness, type CoreDeps } from '../../src/core/core.ts';
import type { CoreConfig } from '../../src/core/types.ts';
import type { LoadedConfig } from '../../src/core/config.ts';
import { SessionLog } from './fixture-session.ts';
import { adaptClient, records, type FixtureClient, type FixtureForkOptions } from './fixture-protocol.ts';
import type { ForkOptions } from '../../src/core/types.ts';
export * from '../../src/core/core.ts';
export class Core<C extends CoreConfig = CoreConfig> extends StandardHarness<C> {
  declare readonly session: SessionLog;
  constructor(loaded: LoadedConfig<C>, deps: Omit<CoreDeps, 'llm'> & { llm?: FixtureClient | CoreDeps['llm'] }) {
    super(loaded, { ...deps, llm: deps.llm ? adaptClient(deps.llm) : undefined });
    Object.setPrototypeOf(this.session, SessionLog.prototype);
  }
  override spawnFork(options: ForkOptions | FixtureForkOptions): Promise<string> { return super.spawnFork({ ...options, messages: records(options.messages) }); }
}
