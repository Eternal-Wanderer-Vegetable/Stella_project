import type { WorldDefinition } from 'cortico/world.ts';
import { EXAMPLE_DEFAULTS, type ExampleConfigSection } from './config.ts';
import { ExampleWorld } from './world.ts';

export const EXAMPLE: WorldDefinition<ExampleConfigSection> = {
  id: 'example',
  label: 'Example',
  defaults: () => ({ ...EXAMPLE_DEFAULTS }),
  // `ctx.cfg` 是 `worlds.example` 的活引用:热改的键现读即生效。
  create: (ctx) => new ExampleWorld({ cfg: ctx.cfg, timezone: ctx.timezone }),
};
