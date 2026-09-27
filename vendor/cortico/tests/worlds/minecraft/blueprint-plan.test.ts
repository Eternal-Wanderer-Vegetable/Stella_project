import { describe, expect, it } from 'vitest';
import {
  normalizeBlueprint,
  type NormalizedBlueprint,
  type PositionXYZ,
} from '../../../src/worlds/minecraft/blueprint.ts';
import {
  BLUEPRINT_MAX_OUTPUT_CHARS,
  acceptBlueprint,
  billForSteps,
  blueprintOutputChars,
  blueprintProgress,
  classifyReadback,
  compileBlueprint,
  diffBlueprint,
  layerSpans,
  stepCountThroughLayer,
  stepToBuildCall,
  summarizeReadback,
  toWorld,
  validateBlueprintLimits,
  type BlockNameReader,
} from '../../../src/worlds/minecraft/blueprint-plan.ts';

const AIR = 'minecraft:air';
const STONE = 'minecraft:stone';
const DOOR_LOW = 'minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]';
const DOOR_UP = 'minecraft:oak_door[facing=north,half=upper,hinge=left,open=false,powered=false]';
const BED_FOOT = 'minecraft:white_bed[facing=south,occupied=false,part=foot]';
const BED_HEAD = 'minecraft:white_bed[facing=south,occupied=false,part=head]';

/** 3×3 石地板 + 中间一扇门(下半格在 y=1、上半格在 y=2) */
function houseWithDoor(): NormalizedBlueprint {
  return normalizeBlueprint({
    site_mode: 'retrofit',
    size_xyz: [3, 3, 3],
    axis_order: 'YZX',
    palette: [AIR, STONE, DOOR_LOW, DOOR_UP],
    layers: [
      [[1, 1, 1], [1, 1, 1], [1, 1, 1]],
      [[0, 2, 0], [0, 0, 0], [0, 0, 0]],
      [[0, 3, 0], [0, 0, 0], [0, 0, 0]],
    ],
  });
}

/** 世界取格函数:给一张 `x,y,z → 方块名` 的表,表外一律空气 */
function readerOf(world: Record<string, string>, unknownAt: string[] = []): BlockNameReader {
  return (x, y, z) => {
    const key = `${x},${y},${z}`;
    if (unknownAt.includes(key)) return null;
    return world[key] ?? 'air';
  };
}

describe('尺寸与体量上限', () => {
  it('长条项目不再受单边限制', () => {
    const length = 96;
    const blueprint = normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [length, 1, 1] as PositionXYZ,
      layers: [[Array.from({ length }, () => STONE)]],
    });
    expect(blueprintOutputChars(blueprint)).toBeLessThan(BLUEPRINT_MAX_OUTPUT_CHARS);
    expect(validateBlueprintLimits(blueprint)).toEqual([]);
  });

  it('超过旧非空气格上限仍可受理', () => {
    const layers = Array.from({ length: 9 }, () =>
      Array.from({ length: 32 }, () => Array.from({ length: 32 }, () => STONE)));
    const blueprint = normalizeBlueprint({ site_mode: 'retrofit', size_xyz: [32, 9, 32], layers });
    expect(blueprintOutputChars(blueprint)).toBeLessThan(BLUEPRINT_MAX_OUTPUT_CHARS);
    expect(validateBlueprintLimits(blueprint)).toEqual([]);
  });

  it('只按 palette 编码后的总输出长度拒绝', () => {
    const length = BLUEPRINT_MAX_OUTPUT_CHARS;
    const blueprint = normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [length, 1, 1],
      palette: [STONE],
      layers: [[Array.from({ length }, () => 0)]],
    });
    const failures = validateBlueprintLimits(blueprint);
    expect(failures).toHaveLength(1);
    expect(failures[0].path).toBe('layers');
    expect(failures[0].reason).toContain(`总输出上限 ${BLUEPRINT_MAX_OUTPUT_CHARS} 字符`);
  });

  it('空气格不算进体量', () => {
    const layers = Array.from({ length: 32 }, () =>
      Array.from({ length: 32 }, () => Array.from({ length: 32 }, () => AIR)));
    expect(validateBlueprintLimits(normalizeBlueprint({ site_mode: 'retrofit', size_xyz: [32, 32, 32], layers }))).toEqual([]);
  });
});

describe('IR 编译', () => {
  it('层内同状态贪心并成长方体,层序自底向上', () => {
    const plan = compileBlueprint(houseWithDoor());
    expect(plan.failures).toEqual([]);
    expect(plan.steps).toHaveLength(2);
    expect(plan.steps[0]).toMatchObject({
      index: 0, state: STONE, item: 'stone', from: [0, 0, 0], to: [2, 0, 2], cells: 9, y: 0,
    });
    expect(plan.steps[1]).toMatchObject({
      index: 1, state: DOOR_LOW, item: 'oak_door', from: [1, 1, 0], to: [1, 1, 0], cells: 1, y: 1,
    });
    expect(plan.placeCells).toBe(10);
  });

  it('从部件不出步,记成主部件那一步的回读核对格', () => {
    const plan = compileBlueprint(houseWithDoor());
    expect(plan.checks).toEqual([
      { pos: [1, 2, 0], state: DOOR_UP, mainPos: [1, 1, 0], mainStep: 1 },
    ]);
  });

  it('床按 facing 认床头,床头也是核对格', () => {
    const plan = compileBlueprint(normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 1, 2],
      palette: [BED_FOOT, BED_HEAD],
      layers: [[[0], [1]]],
    }));
    expect(plan.steps).toHaveLength(1);
    expect(plan.steps[0]).toMatchObject({ state: BED_FOOT, item: 'white_bed', cells: 1 });
    expect(plan.checks).toEqual([
      { pos: [0, 0, 1], state: BED_HEAD, mainPos: [0, 0, 0], mainStep: 0 },
    ]);
  });

  it('并块不跨层——一柱石头出三步,层序才说得清', () => {
    const plan = compileBlueprint(normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 3, 1],
      layers: [[[STONE]], [[STONE]], [[STONE]]],
    }));
    expect(plan.steps.map((step) => step.y)).toEqual([0, 1, 2]);
    expect(plan.steps.every((step) => step.from[1] === step.to[1])).toBe(true);
  });

  it('长边与大平面在 IR 内切成可执行的小步', () => {
    const length = 600;
    const plan = compileBlueprint(normalizeBlueprint({
      site_mode: 'new',
      size_xyz: [length, 1, 1],
      layers: [[Array.from({ length }, () => STONE)]],
    }));
    expect(plan.failures).toEqual([]);
    expect(plan.steps.map((step) => step.cells)).toEqual([256, 256, 88]);
    expect(plan.steps.at(-1)?.to).toEqual([599, 0, 0]);
    expect(plan.placeCells).toBe(length);
  });

  it('层内扫描线:先往东吃满一行,再整行往南推', () => {
    const plan = compileBlueprint(normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [3, 1, 2],
      palette: [AIR, STONE, 'minecraft:oak_planks'],
      layers: [[[1, 1, 2], [1, 1, 2]]],
    }));
    expect(plan.steps.map((step) => [step.state, step.from, step.to])).toEqual([
      [STONE, [0, 0, 0], [1, 0, 1]],
      ['minecraft:oak_planks', [2, 0, 0], [2, 0, 1]],
    ]);
  });

  it('孤立的从部件按精确路径点名', () => {
    const plan = compileBlueprint(normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 2, 1],
      palette: [AIR, DOOR_UP],
      layers: [[[0]], [[1]]],
    }));
    expect(plan.steps).toEqual([]);
    expect(plan.failures).toHaveLength(1);
    expect(plan.failures[0].path).toBe('layers[1][0][0]');
    expect(plan.failures[0].reason).toContain('主部件该在 0,0,0');
  });

  it('过程态在编译期点名', () => {
    const plan = compileBlueprint(normalizeBlueprint({
      site_mode: 'retrofit', size_xyz: [1, 1, 1], layers: [[['minecraft:water[level=1]']]],
    }));
    expect(plan.steps).toEqual([]);
    expect(plan.failures[0]).toMatchObject({ path: 'layers[0][0][0]' });
  });
});

describe('支撑与附着', () => {
  const STEM = 'minecraft:melon_stem[age=0]';
  const FENCE_GATE = 'minecraft:oak_fence_gate[facing=north]';

  it('门画在栅栏门正上方:图内撑不住,当场点名', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 3, 1],
      palette: [STONE, FENCE_GATE, DOOR_LOW],
      layers: [[[0]], [[1]], [[2]]],
    });
    expect(result.ok).toBe(false);
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0]).toMatchObject({ path: 'layers[2][0][0]', state: DOOR_LOW });
    expect(result.failures[0].reason).toContain('栅栏门的上表面不完整');
  });

  it('门画在实心方块上照过', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 3, 1],
      palette: [STONE, DOOR_LOW, DOOR_UP],
      layers: [[[0]], [[1]], [[2]]],
    });
    expect(result.ok).toBe(true);
    expect(result.plan?.advisories).toEqual([]);
  });

  it('瓜茎下面画的不是耕地:点名说清那一格是什么', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 2, 1],
      palette: ['minecraft:grass_block[snowy=false]', STEM],
      layers: [[[0]], [[1]]],
    });
    expect(result.ok).toBe(false);
    expect(result.failures[0]).toMatchObject({ path: 'layers[1][0][0]', state: STEM });
    expect(result.failures[0].reason).toContain('要种在耕地上');
    expect(result.failures[0].reason).toContain('minecraft:grass_block');
  });

  it('瓜茎画在自带的耕地层上照过', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 2, 1],
      palette: ['minecraft:farmland[moisture=0]', STEM],
      layers: [[[0]], [[1]]],
    });
    expect(result.ok).toBe(true);
    expect(result.plan?.advisories).toEqual([]);
  });

  it('支撑格在图外不拦受理,归并成一条提醒交给她核现场', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [3, 1, 1],
      palette: [STEM],
      layers: [[[0, 0, 0]]],
    });
    expect(result.ok).toBe(true);
    expect(result.failures).toEqual([]);
    expect(result.plan?.advisories).toEqual([{
      path: 'layers[0][0][0]',
      state: STEM,
      reason: '要种在耕地上;支撑那一格不在图里,施工前现场必须已经满足',
      cells: 3,
    }]);
  });

  it('画成 structure_void 的支撑格也是现场事实,同样只提醒', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 2, 1],
      palette: ['minecraft:structure_void', STEM],
      layers: [[[0]], [[1]]],
    });
    expect(result.ok).toBe(true);
    expect(result.plan?.advisories).toHaveLength(1);
  });

  it('火把悬空、壁挂火把没墙都点名', () => {
    const standing = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 2, 1],
      palette: [AIR, 'minecraft:torch'],
      layers: [[[0]], [[1]]],
    });
    expect(standing.ok).toBe(false);
    expect(standing.failures[0].reason).toContain('图里那一格是空的');

    // wall_torch 的 facing 从墙指向火把:facing=east 的墙在西边那一格
    const onAir = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [2, 1, 1],
      palette: [AIR, 'minecraft:wall_torch[facing=east]'],
      layers: [[[0, 1]]],
    });
    expect(onAir.ok).toBe(false);
    const onWall = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [2, 1, 1],
      palette: [STONE, 'minecraft:wall_torch[facing=east]'],
      layers: [[[0, 1]]],
    });
    expect(onWall.ok).toBe(true);
  });

  it('床脚底下要托得住;床头悬空不拦——放得下去的是床脚那一步', () => {
    const floating = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 2, 2],
      palette: [AIR, BED_FOOT, BED_HEAD],
      layers: [[[0], [0]], [[1], [2]]],
    });
    expect(floating.ok).toBe(false);
    expect(floating.failures[0]).toMatchObject({ state: BED_FOOT });

    const headOverAir = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [1, 2, 2],
      palette: [AIR, STONE, BED_FOOT, BED_HEAD],
      layers: [[[1], [0]], [[2], [3]]],
    });
    expect(headOverAir.ok).toBe(true);
  });

  it('同一条毛病多格只报第一处,格数带在理由里', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [2, 2, 1],
      palette: [FENCE_GATE, DOOR_LOW],
      layers: [[[0, 0]], [[1, 1]]],
    });
    expect(result.ok).toBe(false);
    expect(result.failures).toHaveLength(1);
    expect(result.failures[0].path).toBe('layers[1][0][0]');
    expect(result.failures[0].reason).toContain('同样的还有 1 格');
  });
});

describe('IR 步 → build 调用', () => {
  it('锚点折算成绝对坐标的 box', () => {
    const plan = compileBlueprint(houseWithDoor());
    expect(stepToBuildCall(plan.steps[0], [100, 64, -20])).toEqual({
      skill: 'build',
      shape: 'box',
      fill: 'solid',
      anchors: [[100, 64, -20], [102, 64, -18]],
      material: 'stone',
    });
    expect(toWorld([100, 64, -20], [1, 1, 0])).toEqual([101, 65, -20]);
  });
});

describe('受理管线', () => {
  it('干净的提交直接过,并给出体素指标与 IR', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit',
      size_xyz: [3, 3, 3],
      axis_order: 'YZX',
      palette: [AIR, STONE, DOOR_LOW, DOOR_UP],
      layers: [
        [[1, 1, 1], [1, 1, 1], [1, 1, 1]],
        [[0, 2, 0], [0, 0, 0], [0, 0, 0]],
        [[0, 3, 0], [0, 0, 0], [0, 0, 0]],
      ],
    });
    expect(result.ok).toBe(true);
    expect(result.repair.strictValid).toBe(true);
    expect(result.repair.applied).toBe(false);
    expect(result.plan?.steps).toHaveLength(2);
    expect(result.metrics?.nonAirCells).toBe(11);
  });

  it('漏属性的走宽容层补齐后过', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 1, 1],
      palette: ['minecraft:oak_stairs[facing=north,half=bottom,waterlogged=false]'],
      layers: [[[0]]],
    });
    expect(result.ok).toBe(true);
    expect(result.repair.applied).toBe(true);
    expect(result.repair.actions.map((action) => action.code)).toEqual(['default-state-completion']);
    expect(result.blueprint?.layers[0][0][0]).toContain('shape=straight');
  });

  it('轴序小写 + 参差矩阵靠宽容层救回', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit',
      size_xyz: [2, 1, 1],
      axis_order: 'yzx',
      palette: [AIR, STONE],
      layers: [[[1, 1]], [[1]]],
    });
    expect(result.ok).toBe(true);
    expect(result.repair.strictValid).toBe(false);
    expect(result.repair.strictError).toContain('axis_order');
    expect(result.repair.actions.map((action) => action.code)).toEqual([
      'axis-order-normalization',
      'declared-size-normalization',
      'dense-grid-fit',
    ]);
    expect(result.blueprint?.size_xyz).toEqual([2, 2, 1]);
  });

  it('修不好的按精确错误路径拒绝', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: [AIR], layers: [[[7]]],
    });
    expect(result.ok).toBe(false);
    expect(result.failures[0].path).toBe('layers[0][0][0]');
    expect(result.failures[0].reason).toContain('越界');
  });

  it('流动液体在受理期就点名,不进 IR', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit',
      size_xyz: [2, 1, 1],
      palette: [STONE, 'minecraft:water[level=1]'],
      layers: [[[0, 1]]],
    });
    expect(result.ok).toBe(false);
    expect(result.plan).toBeNull();
    expect(result.failures.map((entry) => entry.path)).toEqual(['layers[0][0][1]']);
    expect(result.failures[0].reason).toContain('level=0');
  });

  it('长边不掩盖 registry 的问题', () => {
    const result = acceptBlueprint({
      site_mode: 'retrofit',
      size_xyz: [33, 1, 1],
      palette: ['minecraft:not_a_real_block'],
      layers: [[Array.from({ length: 33 }, () => 0)]],
    });
    expect(result.ok).toBe(false);
    expect(result.failures.map((entry) => entry.path)).toEqual(['layers[0][0][0]']);
  });

  it('耕地、水源、幼苗与红石功能状态都能编译', () => {
    const result = acceptBlueprint({
      site_mode: 'new',
      size_xyz: [4, 1, 1],
      palette: [
        'minecraft:farmland[moisture=7]',
        'minecraft:water[level=0]',
        'minecraft:wheat[age=0]',
        'minecraft:repeater[delay=4,facing=north,locked=false,powered=false]',
      ],
      layers: [[[0, 1, 2, 3]]],
    });
    expect(result.ok).toBe(true);
    expect(result.plan?.steps.map((step) => step.method)).toEqual([
      // 豁免集包含锄头能产出耕地的全部源方块；[0] 用于账单与补基材。
      {
        kind: 'use', item: 'hoe', target: 'self', reusable: true,
        baseItem: ['dirt', 'grass_block', 'dirt_path', 'farmland'],
      },
      {
        kind: 'use', item: 'water_bucket', target: 'below',
        verify: { property: 'level', value: '0' },
      },
      { kind: 'use', item: 'wheat_seeds', target: 'below' },
      {
        kind: 'place', item: 'repeater',
        postUse: { property: 'delay', value: '4', maxUses: 4 },
      },
    ]);
    expect(billForSteps(result.plan!.steps).lines.map((line) => [line.item, line.need]))
      .toEqual(expect.arrayContaining([
        ['dirt', 1], ['hoe', 1], ['water_bucket', 1], ['wheat_seeds', 1], ['repeater', 1],
      ]));
  });

  it('核对声明尺寸的口子留着', () => {
    const result = acceptBlueprint(
      { site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: [STONE], layers: [[[0]]] },
      { expectedSize: [2, 1, 1] },
    );
    expect(result.ok).toBe(false);
    expect(result.failures[0].path).toBe('size_xyz');
  });
});

describe('世界对账', () => {
  const blueprint = houseWithDoor();
  const plan = compileBlueprint(blueprint);
  const anchor: PositionXYZ = [0, 0, 0];

  it('全空的地基:一步没完成,游标 0', () => {
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf({}));
    expect(diff.total).toBe(10);
    expect(diff.matched).toBe(0);
    expect(diff.missing).toBe(10);
    expect(diff.cursor).toBe(0);
    expect(diff.remaining).toHaveLength(2);
  });

  it('地板已铺好:第一步折算成已完成,游标推到 1', () => {
    const world: Record<string, string> = {};
    for (let x = 0; x < 3; x++) for (let z = 0; z < 3; z++) world[`${x},0,${z}`] = 'stone';
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf(world));
    expect(diff.matched).toBe(9);
    expect(diff.doneSteps).toEqual([0]);
    expect(diff.cursor).toBe(1);
    expect(diff.remaining.map((step) => step.index)).toEqual([1]);
  });

  /**
   * 锄头对草方块与泥土产出相同耕地，两者都属于耕地转换的清场豁免集。
   */
  it('耕地画在草方块上不算冲突:锄头对草与泥土产出的耕地是同一样东西', () => {
    const farm = normalizeBlueprint({
      site_mode: 'new', size_xyz: [1, 1, 1], layers: [[['minecraft:farmland[moisture=0]']]],
    });
    const farmPlan = compileBlueprint(farm);
    const conflictsOn = (name: string): number => {
      const diff = diffBlueprint(farm, farmPlan, anchor, readerOf({ '0,0,0': name }));
      return diff.conflictCounts['wrong-block'];
    };
    expect(conflictsOn('grass_block')).toBe(0);
    expect(conflictsOn('dirt')).toBe(0);
    expect(conflictsOn('dirt_path')).toBe(0);
    // 锄不出耕地的照样是冲突
    expect(conflictsOn('cobblestone')).toBe(1);
  });

  it('只比 type,state 漂了照样算已建', () => {
    const stairs = normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 1, 1],
      layers: [[['minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]']]],
    });
    const stairPlan = compileBlueprint(stairs);
    const diff = diffBlueprint(stairs, stairPlan, anchor, readerOf({ '0,0,0': 'oak_stairs' }));
    expect(diff.matched).toBe(1);
    expect(diff.cursor).toBe(1);
  });

  it('液源核对 level=0,流动水不冒充已完成的水源', () => {
    const source = normalizeBlueprint({
      site_mode: 'new',
      size_xyz: [1, 1, 1],
      layers: [[['minecraft:water[level=0]']]],
    });
    const sourcePlan = compileBlueprint(source);
    const flowing = diffBlueprint(
      source, sourcePlan, anchor, readerOf({ '0,0,0': 'water[level=1]' }),
    );
    expect(flowing).toMatchObject({ matched: 0, missing: 1, cursor: 0 });
    const still = diffBlueprint(
      source, sourcePlan, anchor, readerOf({ '0,0,0': 'water[level=0]' }),
    );
    expect(still).toMatchObject({ matched: 1, missing: 0, cursor: 1 });
  });

  it('该放东西的地方是别的方块 → wrong-block', () => {
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf({ '0,0,0': 'dirt' }));
    expect(diff.conflictCounts['wrong-block']).toBe(1);
    expect(diff.conflicts[0]).toMatchObject({
      pos: [0, 0, 0], local: [0, 0, 0], expect: STONE, actual: 'minecraft:dirt', kind: 'wrong-block',
    });
  });

  it('该空着的地方有东西 → should-be-air,可以关掉', () => {
    const world = { '0,1,0': 'grass_block' };
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf(world));
    expect(diff.conflictCounts['should-be-air']).toBe(1);
    const off = diffBlueprint(blueprint, plan, anchor, readerOf(world), { checkAir: false });
    expect(off.conflictCounts['should-be-air']).toBe(0);
  });

  it('structure_void 保留现场,不算该清空的冲突', () => {
    const preserve = normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [2, 1, 1],
      palette: ['minecraft:structure_void', AIR],
      layers: [[[0, 1]]],
    });
    const diff = diffBlueprint(
      preserve,
      compileBlueprint(preserve),
      anchor,
      readerOf({ '0,0,0': 'oak_log', '1,0,0': 'dirt' }),
    );
    expect(diff.conflictCounts['should-be-air']).toBe(1);
    expect(diff.conflicts[0].pos).toEqual([1, 0, 0]);
  });

  it('读不到的格算"还不知道",既不是已建也不是冲突', () => {
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf({}, ['0,0,0']));
    expect(diff.unknown).toBe(1);
    expect(diff.conflictCounts['wrong-block']).toBe(0);
    expect(diff.doneSteps).toEqual([]);
  });

  it('锚点参与折算', () => {
    const world: Record<string, string> = {};
    for (let x = 0; x < 3; x++) for (let z = 0; z < 3; z++) world[`${100 + x},64,${-20 + z}`] = 'stone';
    const diff = diffBlueprint(blueprint, plan, [100, 64, -20], readerOf(world));
    expect(diff.doneSteps).toEqual([0]);
  });

  it('冲突样本按上限截断,计数照全', () => {
    const world: Record<string, string> = {};
    for (let x = 0; x < 3; x++) for (let z = 0; z < 3; z++) world[`${x},0,${z}`] = 'dirt';
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf(world), { sampleLimit: 2 });
    expect(diff.conflicts).toHaveLength(2);
    expect(diff.conflictCounts['wrong-block']).toBe(9);
  });

  it('可转换基材(耕地底下的泥土)是待加工不是冲突,别的方块照算', () => {
    const farm = normalizeBlueprint({
      site_mode: 'new',
      size_xyz: [1, 1, 1],
      layers: [[['minecraft:farmland']]],
    });
    const farmPlan = compileBlueprint(farm);
    // 泥土原地锄一下就是耕地——挖掉再放回是浪费,续建时还会挖掉上一趟刚铺的基材
    const onDirt = diffBlueprint(farm, farmPlan, anchor, readerOf({ '0,0,0': 'dirt' }));
    expect(onDirt).toMatchObject({ matched: 0, missing: 1 });
    expect(onDirt.conflictCounts['wrong-block']).toBe(0);
    expect(onDirt.conflicts).toEqual([]);
    const onStone = diffBlueprint(farm, farmPlan, anchor, readerOf({ '0,0,0': 'stone' }));
    expect(onStone.conflictCounts['wrong-block']).toBe(1);
  });

  it('门的从部件不对时主步骤不算完成，占位方块进清场冲突', () => {
    const world: Record<string, string> = {};
    for (let x = 0; x < 3; x++) for (let z = 0; z < 3; z++) world[`${x},0,${z}`] = 'stone';
    world['1,1,0'] = DOOR_LOW;
    world['1,2,0'] = 'dirt';
    const diff = diffBlueprint(blueprint, plan, anchor, readerOf(world));
    expect(diff.doneSteps).toEqual([0]);
    expect(diff.remaining.map((step) => step.index)).toEqual([1]);
    expect(diff.conflictCounts['wrong-block']).toBe(1);
    expect(diff.conflicts[0]).toMatchObject({ pos: [1, 2, 0], expect: 'minecraft:oak_door' });
  });
});

describe('三分账单', () => {
  const steps = compileBlueprint(houseWithDoor()).steps;

  it('每种物品分成还缺/随身/在箱', () => {
    const bill = billForSteps(steps, { carried: { stone: 4 }, stored: { oak_door: 1 } });
    expect(bill.lines).toEqual([
      { item: 'stone', need: 9, carried: 4, stored: 0, missing: 5 },
      { item: 'oak_door', need: 1, carried: 0, stored: 1, missing: 0 },
    ]);
    expect(bill.totalNeed).toBe(10);
    expect(bill.totalMissing).toBe(5);
  });

  it('从头连着能盖完前几步——只算随身的料', () => {
    expect(billForSteps(steps, { carried: { stone: 4 } }).reachableSteps).toBe(0);
    expect(billForSteps(steps, { carried: { stone: 9 } }).reachableSteps).toBe(1);
    expect(billForSteps(steps, { carried: { stone: 9, oak_door: 1 } })).toMatchObject({
      reachableSteps: 2, reachableCells: 10,
    });
  });

  it('后面那步够料也不跳步——口径就是盖到料尽', () => {
    const bill = billForSteps(steps, { carried: { oak_door: 1 } });
    expect(bill.reachableSteps).toBe(0);
  });

  it('箱里的取来能多盖几步,单独一栏', () => {
    const bill = billForSteps(steps, { carried: { stone: 9 }, stored: { oak_door: 1 } });
    expect(bill.reachableSteps).toBe(1);
    expect(bill.reachableStepsWithStored).toBe(2);
  });

  it('什么都没有时账单照出', () => {
    const bill = billForSteps(steps);
    expect(bill.totalMissing).toBe(10);
    expect(bill.reachableSteps).toBe(0);
  });

  it('作物那一步把锄算进账单:播种前那一下锄地也是这一步的活', () => {
    const stems = compileBlueprint(normalizeBlueprint({
      site_mode: 'new',
      size_xyz: [4, 1, 1],
      palette: ['minecraft:melon_stem[age=0]'],
      layers: [[[0, 0, 0, 0]]],
    })).steps;
    const bill = billForSteps(stems, { carried: { melon_seeds: 4 } });
    expect(bill.lines).toEqual([
      { item: 'hoe', need: 1, carried: 0, stored: 0, missing: 1 },
      { item: 'melon_seeds', need: 4, carried: 4, stored: 0, missing: 0 },
    ]);
    expect(bill.reachableSteps).toBe(0);
    expect(billForSteps(stems, { carried: { melon_seeds: 4, iron_hoe: 1 } })).toMatchObject({
      totalMissing: 0, reachableSteps: 1,
    });
  });

  it('工具族名认任意一把,耗材不吃模糊后缀', () => {
    const farm = compileBlueprint(normalizeBlueprint({
      site_mode: 'new',
      size_xyz: [1, 2, 1],
      palette: ['minecraft:farmland', 'minecraft:carrots[age=0]'],
      layers: [[[0]], [[1]]],
    })).steps;
    // golden_carrot 不是能种的胡萝卜、dirt_path 不是基材泥土;wooden_hoe 算一把锄
    const fuzzy = billForSteps(farm, {
      carried: { golden_carrot: 5, dirt_path: 3, wooden_hoe: 1 },
    });
    expect(fuzzy.lines).toEqual(expect.arrayContaining([
      { item: 'carrot', need: 1, carried: 0, stored: 0, missing: 1 },
      { item: 'dirt', need: 1, carried: 0, stored: 0, missing: 1 },
      { item: 'hoe', need: 1, carried: 1, stored: 0, missing: 0 },
    ]));
    expect(fuzzy.reachableSteps).toBe(0);
    const exact = billForSteps(farm, { carried: { carrot: 1, dirt: 1, stone_hoe: 1 } });
    expect(exact.totalMissing).toBe(0);
    expect(exact.reachableSteps).toBe(2);
  });
});

describe('进度与按层分段', () => {
  const steps = compileBlueprint(normalizeBlueprint({
    site_mode: 'retrofit',
    size_xyz: [2, 3, 1],
    palette: [AIR, STONE, 'minecraft:oak_planks'],
    layers: [[[1, 2]], [[1, 1]], [[0, 0]]],
  })).steps;

  it('每层从第几步到第几步', () => {
    expect(layerSpans(steps)).toEqual([
      { y: 0, firstStep: 0, endStep: 2, steps: 2, cells: 2 },
      { y: 1, firstStep: 2, endStep: 3, steps: 1, cells: 2 },
    ]);
  });

  it('stopAfter 按层停:盖到第 n 层为止对应第几步', () => {
    expect(stepCountThroughLayer(steps, 0)).toBe(2);
    expect(stepCountThroughLayer(steps, 1)).toBe(3);
    // 整层空气的第 2 层没有步,取到最近的一层
    expect(stepCountThroughLayer(steps, 2)).toBe(3);
    expect(stepCountThroughLayer(steps, -1)).toBe(0);
  });

  it('游标折算成步数、格数与当前层', () => {
    expect(blueprintProgress(steps, 0)).toEqual({
      steps: { done: 0, total: 3 },
      cells: { done: 0, total: 4 },
      layer: { y: 0, done: 0, total: 2 },
      ratio: 0,
    });
    expect(blueprintProgress(steps, 2)).toMatchObject({
      steps: { done: 2, total: 3 },
      cells: { done: 2, total: 4 },
      layer: { y: 1, done: 0, total: 1 },
      ratio: 0.5,
    });
    expect(blueprintProgress(steps, 3)).toMatchObject({
      layer: { y: null, done: 0, total: 0 },
      ratio: 1,
    });
  });

  it('游标越界按边界夹住', () => {
    expect(blueprintProgress(steps, 99).steps).toEqual({ done: 3, total: 3 });
    expect(blueprintProgress(steps, -5).steps).toEqual({ done: 0, total: 3 });
  });
});

describe('回读三分类', () => {
  const stairs = 'minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]';
  const drifted = 'minecraft:oak_stairs[facing=north,half=bottom,shape=outer_left,waterlogged=false]';

  it('逐格全同 / type 对 state 漂 / 失败', () => {
    expect(classifyReadback(stairs, stairs)).toBe('exact');
    expect(classifyReadback(stairs, drifted)).toBe('state-drift');
    expect(classifyReadback(stairs, 'minecraft:stone')).toBe('failed');
    expect(classifyReadback(stairs, null)).toBe('failed');
    expect(classifyReadback(STONE, 'stone')).toBe('exact');
  });

  it('汇总顺带说清漂在哪个属性上', () => {
    const summary = summarizeReadback([
      { pos: [0, 0, 0], expected: stairs, actual: stairs },
      { pos: [1, 0, 0], expected: stairs, actual: drifted },
      { pos: [2, 0, 0], expected: stairs, actual: 'minecraft:air' },
      { pos: [3, 0, 0], expected: STONE, actual: null },
    ]);
    expect(summary).toMatchObject({ total: 4, exact: 1, drift: 1, failed: 2 });
    expect(summary.driftProperties).toEqual({ 'minecraft:oak_stairs shape': 1 });
    expect(summary.driftSamples.map((entry) => entry.pos)).toEqual([[1, 0, 0]]);
    expect(summary.failedSamples).toHaveLength(2);
  });

  it('样本按上限截断,计数照全', () => {
    const entries = Array.from({ length: 5 }, (_unused, index) => ({
      pos: [index, 0, 0] as PositionXYZ,
      expected: STONE,
      actual: 'dirt',
    }));
    const summary = summarizeReadback(entries, 2);
    expect(summary.failed).toBe(5);
    expect(summary.failedSamples).toHaveLength(2);
  });
});
