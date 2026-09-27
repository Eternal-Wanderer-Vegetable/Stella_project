/**
 * 仓内 World 目录。启动器把它与扩展装进来的 World 并成一张表,经 `withWorlds()` 交给 bot 定义;
 * bot 只声明它为之设计的渠道,哪些真挂由部署的 `worlds.<id>.enabled` 决定。
 * `console-fixture` 是控制台边界的验收件,不在这里。
 */
import type { WorldDefinition, WorldSection } from '../world.ts';
import { TERMINAL } from './terminal/definition.ts';
import { QQ } from './qq/definition.ts';
import { BILIBILI } from './bilibili/definition.ts';
import { MINECRAFT } from './minecraft/definition.ts';
import { WEBSEARCH } from './websearch/definition.ts';

export const BUILTIN_WORLDS: readonly WorldDefinition<WorldSection>[] = [
  TERMINAL, QQ, BILIBILI, MINECRAFT, WEBSEARCH,
] as WorldDefinition<WorldSection>[];
