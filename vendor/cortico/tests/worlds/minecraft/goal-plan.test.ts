import { describe, expect, it } from 'vitest';
import {
  MINECRAFT_TOOL_DECLS, applyGoal, parseGoal,
  type GoalStamp, type GoalTable,
} from '../../../src/worlds/minecraft/world.ts';
import {
  completedGoalSteps, coordinateGoalPlan, goalPlanDoneIssue, parseGoalPlan,
  recordGoalJudgment, reopenGoalJudgment,
  type GoalEntityReading, type GoalItemReading, type GoalPlan, type GoalProbeContext,
} from '../../../src/worlds/minecraft/goal-plan.ts';
import type { CheckCell, CheckWorld } from '../../../src/worlds/minecraft/check.ts';

interface MutableWorld {
  loaded: boolean;
  cells: Map<string, CheckCell>;
  inventory: Map<string, number>;
  position: [number, number, number];
  health: number;
  food: number;
  oxygen: number;
  burning: boolean;
  entities: GoalEntityReading[];
  items: GoalItemReading[];
  generation: number;
}

function mutableWorld(): MutableWorld {
  return {
    loaded: true,
    cells: new Map(),
    inventory: new Map(),
    position: [0, 64, 0],
    health: 20,
    food: 20,
    oxygen: 20,
    burning: false,
    entities: [],
    items: [],
    generation: 3,
  };
}

function context(state: MutableWorld): GoalProbeContext {
  const world: CheckWorld = {
    cell: (x, y, z) => state.loaded
      ? state.cells.get(`${x},${y},${z}`) ?? { state: 'air', solid: false }
      : null,
    inventory: () => state.inventory,
    site: () => null,
    mark: () => null,
  };
  return {
    observedAt: Date.now(),
    connectionGeneration: state.generation,
    realm: 'test-world',
    dimension: 'minecraft:overworld',
    world,
    position: () => state.position,
    status: () => ({
      health: state.health, food: state.food, oxygen: state.oxygen, burning: state.burning,
    }),
    entities: () => state.entities,
    items: () => state.items,
  };
}

function plan(raw: unknown): GoalPlan {
  const parsed = parseGoalPlan(raw);
  if ('error' in parsed) throw new Error(parsed.error);
  return parsed;
}

describe('mc_goal plan 输入合同', () => {
  it.each(['盖房', { text: '盖房' }, { text: '盖房', plan: null }, { text: '盖房', plan: [] }])(
    'add 拒绝没有有效 plan 的输入 %j', (add) => {
      expect(parseGoal({ add })).toHaveProperty('error');
    },
  );

  it('拒绝未知操作字段', () => {
    expect(parseGoal({ progress: { slot: 1, add: 3 } })).toMatchObject({ error: expect.stringContaining('未知字段') });
  });

  it('schema 展开每种 probe 字段，并要求新 add 带 plan', () => {
    const goal = MINECRAFT_TOOL_DECLS.find((tool) => tool.name === 'mc_goal')!;
    const properties = goal.parameters.properties as Record<string, Record<string, unknown>>;
    const add = properties.add;
    expect(add.required).toEqual(['text', 'plan']);
    const planSchema = (add.properties as Record<string, Record<string, unknown>>).plan;
    const step = planSchema.items as Record<string, unknown>;
    const verify = (step.properties as Record<string, Record<string, unknown>>).verify;
    expect(Object.keys(verify.properties as object)).toEqual(expect.arrayContaining([
      'source', 'at', 'is', 'item', 'type', 'count', 'key', 'loaded', 'matched',
      'region', 'dimension', 'field', 'equals',
    ]));
  });

  it('每步恰有 verify 或 judgment，未知字段不会被静默丢掉', () => {
    expect(parseGoalPlan([{ do: '找箱子' }])).toEqual(expect.objectContaining({ error: expect.stringContaining('恰好') }));
    expect(parseGoalPlan([{ do: '找箱子', verify: { source: 'block', at: [0, 64, 0], is: 'chest' }, judgment: '好看' }]))
      .toEqual(expect.objectContaining({ error: expect.stringContaining('恰好') }));
    expect(parseGoalPlan([{ do: '找箱子', verify: { source: 'block', at: [0, 64, 0], is: 'chest', count: 1 } }]))
      .toEqual(expect.objectContaining({ error: expect.stringContaining('不属于 block') }));
    expect(parseGoal({ add: { text: '盖房', plan: [{ do: '验收', judgment: '整体观感' }], typo: true } }))
      .toEqual(expect.objectContaining({ error: expect.stringContaining('未知字段') }));
  });


  it('region 超限给可直接照做的口径:上限折成边长,并报出这次的三条边', () => {
    const r = parseGoalPlan([{
      do: '到家',
      verify: {
        source: 'position',
        region: [[0, 0, 0], [10, 40, 10]],
        dimension: 'minecraft:overworld',
      },
    }]) as { error: string };
    expect(r.error).toContain('4096 格 ≈ 16×16×16');
    expect(r.error).toContain('你这次是 11×41×11');
  });

  it('区域探针必须写维度，status 字段是封闭枚举', () => {
    expect(parseGoalPlan([{ do: '到家', verify: { source: 'position', region: [[0, 0, 0], [1, 1, 1]] } }]))
      .toEqual(expect.objectContaining({ error: expect.stringContaining('dimension') }));
    expect(parseGoalPlan([{ do: '天气好', verify: { source: 'status', field: 'weather', equals: true } }]))
      .toEqual(expect.objectContaining({ error: expect.stringContaining('health/food/oxygen/burning') }));
  });
});

describe('mc_goal 独立世界旁证', () => {
  it('AND 步骤从现读方块、背包、位置、状态、实体和掉落物一次求值', () => {
    const state = mutableWorld();
    state.cells.set('0,64,0', { state: 'minecraft:stone', solid: true });
    state.inventory.set('slime_ball', 27);
    state.health = 8;
    state.entities.push({ type: 'zombie', position: [1, 64, 1] });
    state.items.push({ item: 'arrow', count: 2, position: [2, 64, 2] });
    const p = plan([{
      do: '带着战利品在安全区站稳',
      verify: [
        { source: 'block', at: [0, 64, 0], is: 'stone' },
        { source: 'inventory', item: 'slime_ball', count: '>=27' },
        { source: 'position', region: [[-2, 60, -2], [3, 70, 3]], dimension: 'minecraft:overworld' },
        { source: 'status', field: 'health', equals: '>=8' },
        { source: 'entity', type: 'zombie', count: 1, region: [[-2, 60, -2], [3, 70, 3]], dimension: 'minecraft:overworld' },
        { source: 'item', item: 'arrow', count: 2, region: [[-2, 60, -2], [3, 70, 3]], dimension: 'minecraft:overworld' },
      ],
    }]);
    const result = coordinateGoalPlan(p, context(state));
    expect(result.ready).toBe(true);
    expect(completedGoalSteps(p)).toBe(1);
    const evidence = p.steps[0].evidence;
    expect(evidence && 'connectionGeneration' in evidence ? evidence.connectionGeneration : null).toBe(3);
    expect(evidence && 'results' in evidence ? evidence.results : []).toHaveLength(6);
  });

  it('区域没完整加载时 count=0 仍是 unknown，不把未跟踪冒充不存在', () => {
    const state = mutableWorld();
    state.loaded = false;
    const p = plan([{
      do: '确认村民都已撤离',
      verify: {
        source: 'entity', type: 'villager', count: 0,
        region: [[0, 60, 0], [8, 70, 8]], dimension: 'minecraft:overworld',
      },
    }]);
    const result = coordinateGoalPlan(p, context(state));
    expect(result.ready).toBe(false);
    expect(completedGoalSteps(p)).toBe(0);
    expect(p.steps[0].evidence).toEqual(expect.objectContaining({ verdict: 'unknown' }));
  });

  it('前沿资源丢失会回退，最终 AND 会在 ready 后继续复核', () => {
    const state = mutableWorld();
    state.position = [100, 64, 100];
    state.inventory.set('slime_ball', 27);
    const p = plan([
      { do: '收齐 27 个史莱姆球', verify: { source: 'inventory', item: 'slime_ball', count: '>=27' } },
      {
        do: '把 27 个史莱姆球带回出生点',
        verify: [
          { source: 'position', region: [[-3, 60, -3], [3, 70, 3]], dimension: 'minecraft:overworld' },
          { source: 'inventory', item: 'slime_ball', count: '>=27' },
        ],
      },
    ]);
    expect(coordinateGoalPlan(p, context(state)).completed).toBe(1);
    state.inventory.set('slime_ball', 0);
    const lost = coordinateGoalPlan(p, context(state));
    expect(lost.transitions).toEqual(expect.arrayContaining([expect.objectContaining({ kind: 'regress', to: 0 })]));

    state.inventory.set('slime_ball', 27);
    state.position = [0, 64, 0];
    expect(coordinateGoalPlan(p, context(state)).ready).toBe(true);
    expect(goalPlanDoneIssue(p)).toBeNull();
    state.inventory.set('slime_ball', 0);
    expect(coordinateGoalPlan(p, context(state)).ready).toBe(false);
    expect(goalPlanDoneIssue(p)).toContain('下一步');
  });

  it('被下一里程碑承接的消耗品冻结，不因后来消耗而退回', () => {
    const state = mutableWorld();
    state.inventory.set('oak_boat', 1);
    state.position = [0, 64, 0];
    const p = plan([
      { do: '备好船', verify: { source: 'inventory', item: 'oak_boat', count: '>=1' } },
      {
        do: '乘船到村庄',
        verify: { source: 'position', region: [[100, 60, 100], [110, 70, 110]], dimension: 'minecraft:overworld' },
      },
      { do: '观察交易站是否合用', judgment: '布局与动线需要现场判断' },
    ]);
    expect(coordinateGoalPlan(p, context(state)).completed).toBe(1);
    state.inventory.set('oak_boat', 0);
    state.position = [105, 64, 105];
    expect(coordinateGoalPlan(p, context(state)).completed).toBe(2);
    expect(p.steps[0].state).toBe('verified');
  });

  it('主观后继已承接时冻结更早的机械旁证', () => {
    const state = mutableWorld();
    state.inventory.set('oak_boat', 1);
    const p = plan([
      { do: '备好船', verify: { source: 'inventory', item: 'oak_boat', count: '>=1' } },
      { do: '现场确认航线可用', judgment: '水路连通性需要现场判断' },
    ]);
    expect(coordinateGoalPlan(p, context(state)).completed).toBe(1);
    expect(recordGoalJudgment(p, 2, '已沿航线复看，通道可用', Date.now()))
      .toEqual(expect.objectContaining({ ok: true, completed: 2 }));

    state.inventory.set('oak_boat', 0);
    const result = coordinateGoalPlan(p, context(state));
    expect(result.ready).toBe(true);
    expect(result.transitions.some((transition) => transition.kind === 'regress')).toBe(false);
    expect(p.steps[0].state).toBe('verified');
  });
});

describe('judgment 顺序与 done 门控', () => {
  const stamp: GoalStamp = { day: 1, realTime: '2026-08-26T12:00:00-05:00', at: Date.now() };

  it('judgment 只能填写当前步，reopen 只撤回显式判断', () => {
    const p = plan([
      { do: '收材料', verify: { source: 'inventory', item: 'stone', count: '>=1' } },
      { do: '复看外观', judgment: '审美目标不可机械核验' },
    ]);
    expect(recordGoalJudgment(p, 2, '看起来完整', Date.now()))
      .toEqual(expect.objectContaining({ ok: false, error: expect.stringContaining('不能越过') }));
    const state = mutableWorld();
    state.inventory.set('stone', 1);
    coordinateGoalPlan(p, context(state));
    expect(recordGoalJudgment(p, 2, '现场复看后比例协调', Date.now()))
      .toEqual(expect.objectContaining({ ok: true, completed: 2 }));
    expect(reopenGoalJudgment(p, 2)).toEqual(expect.objectContaining({ ok: true, completed: 1 }));
    expect(reopenGoalJudgment(p, 1)).toEqual(expect.objectContaining({ ok: false }));
  });

  /**
   * 拒绝 judgment 代填时，说明该步骤登记的条件、自动核验方式及允许登记判断的步骤。
   */
  it('judgment 被拒时说清这一步实际要什么,以及哪一步才能登记判断', () => {
    const p = plan([
      { do: '收材料', verify: { source: 'inventory', item: 'cooked_cod', count: '>=8' } },
      { do: '复看外观', judgment: '审美目标不可机械核验' },
    ]);
    const wrongKind = recordGoalJudgment(p, 1, '河边箱熟鳕 13 已超目标', Date.now()) as { error: string };
    expect(wrongKind.error).toContain('机械核验');
    expect(wrongKind.error).toContain('包里 cooked_cod >=8');
    expect(wrongKind.error).toContain('它会自己判定');
    expect(wrongKind.error).toContain('能登记判断的是第 2 步');

    const outOfOrder = recordGoalJudgment(p, 2, '看起来完整', Date.now()) as { error: string };
    expect(outOfOrder.error).toContain('不能越过');
    expect(outOfOrder.error).toContain('第 1 步是「收材料」');
    expect(outOfOrder.error).toContain('包里 cooked_cod >=8');
  });

  it('applyGoal 在 pending 时保留目标，独立现读 ready 后才删除', () => {
    const parsed = parseGoal({
      add: {
        text: '带回史莱姆球',
        current: 0, total: 27, unit: '个',
        plan: [{ do: '收齐', verify: { source: 'inventory', item: 'slime_ball', count: '>=27' } }],
      },
    });
    if ('error' in parsed || parsed.kind !== 'add') throw new Error('plan parse failed');
    const table: GoalTable = { list: [] };
    applyGoal(table, parsed, stamp);
    expect(applyGoal(table, { kind: 'done', slot: 1 }, stamp)).toContain('还不能结案');
    expect(table.list).toHaveLength(1);

    const state = mutableWorld();
    state.inventory.set('slime_ball', 27);
    coordinateGoalPlan(table.list[0].plan, context(state));
    expect(table.list[0].progress).toEqual({ current: 0, total: 27, unit: '个' });
    expect(applyGoal(table, { kind: 'done', slot: 1 }, stamp)).toContain('完成了');
    expect(table.list).toHaveLength(0);
  });
});
