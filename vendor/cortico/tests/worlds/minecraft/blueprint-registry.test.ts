import { describe, expect, it } from 'vitest';
import { normalizeBlueprint, type NormalizedBlueprint } from '../../../src/worlds/minecraft/blueprint.ts';
import {
  blockStateItem,
  blueprintNeedsTilledSoil,
  blueprintPlacementMethod,
  blueprintSupportRules,
  blueprintSupportViolation,
  completeBlockStateDefaults,
  validateBlueprintPlaceability,
  validateBlueprintRegistry,
} from '../../../src/worlds/minecraft/blueprint-registry.ts';

function strip(states: string[]): NormalizedBlueprint {
  return normalizeBlueprint({ site_mode: 'retrofit', size_xyz: [states.length, 1, 1], layers: [[states]] });
}

function failuresOf(states: string[]) {
  return validateBlueprintRegistry(strip(states)).failures;
}

describe('registry 校验', () => {
  it('认不出的方块 id 点名拒绝', () => {
    const [failure] = failuresOf(['minecraft:not_a_real_block']);
    expect(failure).toMatchObject({ path: 'layers[0][0][0]', state: 'minecraft:not_a_real_block' });
    expect(failure.reason).toContain('没有 minecraft:not_a_real_block');
  });

  it('别的命名空间不收', () => {
    expect(failuresOf(['example:oak_planks'])[0].reason).toContain('只收 minecraft');
  });

  it.each([
    ['门', 'minecraft:oak_door[facing=north,half=lower,hinge=left,open=false]', 'powered'],
    ['楼梯', 'minecraft:oak_stairs[facing=north,half=bottom,waterlogged=false]', 'shape'],
  ])('%s 属性没写全时点名说缺哪个', (_name, state, missing) => {
    expect(failuresOf([state])[0].reason).toContain(`缺属性:${missing}`);
  });

  it.each([
    ['枚举', 'minecraft:oak_stairs[facing=up,half=bottom,shape=straight,waterlogged=false]', 'facing=up'],
    ['布尔', 'minecraft:oak_door[facing=north,half=lower,hinge=left,open=no,powered=false]', 'open=no'],
    ['整数', 'minecraft:redstone_wire[east=none,north=none,power=16,south=none,west=none]', 'power=16'],
  ])('%s 属性值不合法时点名', (_kind, state, bad) => {
    expect(failuresOf([state])[0].reason).toContain(bad);
  });

  it('多出来的属性也点名', () => {
    const [failure] = failuresOf([
      'minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false,foo=bar]',
    ]);
    expect(failure.reason).toContain('多了不存在的属性:foo');
  });

  it('完整的 1.20.6 状态照收,空气无属性也收', () => {
    const result = validateBlueprintRegistry(strip([
      'minecraft:air',
      'minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]',
      'minecraft:oak_stairs[facing=east,half=top,shape=inner_left,waterlogged=true]',
    ]));
    expect(result.valid).toBe(true);
    expect(result.minecraft_version).toBe('1.20.6');
    expect(result.unique_states).toBe(3);
  });

  it('同一状态只校验一次,报错报第一处', () => {
    const result = validateBlueprintRegistry(strip([
      'minecraft:air', 'minecraft:air', 'minecraft:stone',
    ]));
    expect(result.unique_states).toBe(2);
  });
});

describe('默认状态补齐', () => {
  it('漏写的属性按官方默认状态补上', () => {
    expect(completeBlockStateDefaults('minecraft:white_bed[facing=south,part=foot]')).toEqual({
      state: 'minecraft:white_bed[facing=south,occupied=false,part=foot]',
      added: { occupied: 'false' },
    });
  });

  it('写全了就一条不动', () => {
    const state = 'minecraft:stone';
    expect(completeBlockStateDefaults(state)).toEqual({ state, added: {} });
  });

  it('认不出的方块原样返回,交给 registry 校验点名', () => {
    expect(completeBlockStateDefaults('minecraft:not_a_real_block').added).toEqual({});
  });
});

describe('状态 → 物品', () => {
  it.each([
    ['minecraft:stone', 'stone'],
    ['minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]', 'oak_stairs'],
    ['minecraft:oak_door[facing=north,half=upper,hinge=left,open=false,powered=false]', 'oak_door'],
    ['minecraft:white_bed[facing=south,occupied=false,part=head]', 'white_bed'],
  ])('%s 用同名物品放', (state, item) => {
    expect(blockStateItem(state)).toEqual({ item });
  });

  it.each([
    ['minecraft:wall_torch[facing=north]', 'torch'],
    ['minecraft:oak_wall_sign[facing=north,waterlogged=false]', 'oak_sign'],
    ['minecraft:white_wall_banner[facing=north]', 'white_banner'],
  ])('壁挂变体 %s 用去掉 wall_ 的那个物品', (state, item) => {
    expect(blockStateItem(state)).toEqual({ item });
  });

  it('红石线用红石粉', () => {
    expect(blockStateItem('minecraft:redstone_wire[east=none,north=none,power=0,south=none,west=none]'))
      .toEqual({ item: 'redstone' });
  });

  it.each([
    ['minecraft:water[level=0]', '没有能直接放出'],
    ['minecraft:lava[level=0]', '没有能直接放出'],
    ['minecraft:fire[age=0,east=false,north=false,south=false,up=false,west=false]', '没有能直接放出'],
    ['minecraft:nether_portal[axis=x]', '没有能直接放出'],
    ['minecraft:carrots[age=0]', '没有能直接放出'],
  ])('%s 放不出来,点名拒绝', (state, reason) => {
    const lookup = blockStateItem(state);
    expect(lookup.item).toBeNull();
    if (lookup.item === null) expect(lookup.reason).toContain(reason);
  });

  it.each([
    ['minecraft:farmland[moisture=0]', '锄头'],
    ['minecraft:dirt_path', '锹'],
    ['minecraft:wheat[age=0]', '种子'],
  ])('%s 有同名物品但放不出这个方块,理由写明', (state, reason) => {
    const lookup = blockStateItem(state);
    expect(lookup.item).toBeNull();
    if (lookup.item === null) expect(lookup.reason).toContain(reason);
  });

  it('空气格不用放东西', () => {
    expect(blockStateItem('minecraft:air')).toEqual({ item: null, reason: '空气格不用放东西' });
  });
});

describe('支撑与附着规则表', () => {
  const rule = (state: string) => blueprintSupportRules(state)[0];

  it.each([
    ['门', 'minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]'],
    ['作物', 'minecraft:melon_stem[age=0]'],
    ['火把', 'minecraft:torch'],
    ['床脚', 'minecraft:white_bed[facing=south,occupied=false,part=foot]'],
  ])('%s 要下面那一格撑住', (_kind, state) => {
    expect(rule(state).offset).toEqual([0, -1, 0]);
  });

  it('壁挂火把的支撑格在 facing 的反方向:facing=east 的墙在西边', () => {
    expect(rule('minecraft:wall_torch[facing=east]').offset).toEqual([-1, 0, 0]);
    expect(rule('minecraft:wall_torch[facing=north]').offset).toEqual([0, 0, 1]);
  });

  it('从部件不要支撑——它跟着主部件一起长出来', () => {
    expect(blueprintSupportRules(
      'minecraft:oak_door[facing=north,half=upper,hinge=left,open=false,powered=false]',
    )).toEqual([]);
    expect(blueprintSupportRules(
      'minecraft:white_bed[facing=south,occupied=false,part=head]',
    )).toEqual([]);
  });

  it('地狱疣认灵魂沙,不认耕地,也就不用锄', () => {
    expect(rule('minecraft:nether_wart[age=0]').requirement)
      .toEqual({ kind: 'block', id: 'minecraft:soul_sand' });
    expect(blueprintNeedsTilledSoil('minecraft:nether_wart[age=0]')).toBe(false);
    expect(blueprintNeedsTilledSoil('minecraft:melon_stem[age=0]')).toBe(true);
    expect(blueprintNeedsTilledSoil('minecraft:stone')).toBe(false);
  });

  it('规则表点不到的方块一条要求都不提', () => {
    expect(blueprintSupportRules('minecraft:stone')).toEqual([]);
    expect(blueprintSupportRules('minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]'))
      .toEqual([]);
  });

  describe('支撑格够不够格', () => {
    const door = rule('minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]');
    const torch = rule('minecraft:torch');
    const stem = rule('minecraft:melon_stem[age=0]');

    it.each([
      ['栅栏门', 'minecraft:oak_fence_gate[facing=north,in_wall=false,open=false,powered=false]', '栅栏门的上表面不完整'],
      ['栅栏', 'minecraft:oak_fence[east=false,north=false,south=false,waterlogged=false,west=false]', '栅栏的顶面不是完整一格'],
      ['下半砖', 'minecraft:oak_slab[type=bottom,waterlogged=false]', '下半砖的顶面只到半格高'],
      ['空气', 'minecraft:air', '图里那一格是空的'],
    ])('门放不到 %s 上', (_kind, support, why) => {
      expect(blueprintSupportViolation(door, support)).toContain(why);
    });

    it('门放实心方块、上半砖上没话说', () => {
      expect(blueprintSupportViolation(door, 'minecraft:stone')).toBeNull();
      expect(blueprintSupportViolation(door, 'minecraft:oak_slab[type=top,waterlogged=false]')).toBeNull();
    });

    it('栅栏撑得住火把,撑不住门——两档要求不一样', () => {
      const fence = 'minecraft:oak_fence[east=false,north=false,south=false,waterlogged=false,west=false]';
      expect(blueprintSupportViolation(torch, fence)).toBeNull();
      expect(blueprintSupportViolation(door, fence)).not.toBeNull();
      expect(blueprintSupportViolation(torch, 'minecraft:torch')).toContain('火把顶上托不住东西');
    });

    it('作物只认那一种土', () => {
      expect(blueprintSupportViolation(stem, 'minecraft:farmland[moisture=7]')).toBeNull();
      expect(blueprintSupportViolation(stem, 'minecraft:dirt')).toContain('minecraft:dirt');
      expect(blueprintSupportViolation(stem, 'minecraft:air')).toContain('空的');
    });
  });

});

describe('可放置性校验', () => {
  it('放得出来的全过', () => {
    const result = validateBlueprintPlaceability(strip([
      'minecraft:air', 'minecraft:stone', 'minecraft:wall_torch[facing=north]',
      'minecraft:water[level=0]', 'minecraft:farmland[moisture=7]', 'minecraft:wheat[age=0]',
    ]));
    expect(result.valid).toBe(true);
  });

  it('没有施工口径的过程状态按第一次出现的位置点名', () => {
    const result = validateBlueprintPlaceability(strip([
      'minecraft:stone', 'minecraft:nether_portal[axis=x]',
      'minecraft:water[level=1]', 'minecraft:wheat[age=7]',
      'minecraft:pitcher_crop[age=0,half=lower]',
    ]));
    expect(result.valid).toBe(false);
    expect(result.failures.map((entry) => entry.path)).toEqual([
      'layers[0][0][1]',
      'layers[0][0][2]',
      'layers[0][0][3]',
      'layers[0][0][4]',
    ]);
    expect(result.failures.at(-1)?.reason).toContain('从一格变两格');
  });

  it('可交互的功能状态按目标值校正，铁门打开态不假装能徒手完成', () => {
    const lever = completeBlockStateDefaults('minecraft:lever[powered=false]').state;
    const repeater = completeBlockStateDefaults('minecraft:repeater[delay=1]').state;
    const comparator = completeBlockStateDefaults('minecraft:comparator[mode=compare]').state;
    const door = completeBlockStateDefaults('minecraft:oak_door[half=lower,open=false]').state;
    expect(blueprintPlacementMethod(lever)).toMatchObject({
      kind: 'place', postUse: { property: 'powered', value: 'false' },
    });
    expect(blueprintPlacementMethod(repeater)).toMatchObject({
      kind: 'place', postUse: { property: 'delay', value: '1' },
    });
    expect(blueprintPlacementMethod(comparator)).toMatchObject({
      kind: 'place', postUse: { property: 'mode', value: 'compare' },
    });
    expect(blueprintPlacementMethod(door)).toMatchObject({
      kind: 'place', postUse: { property: 'open', value: 'false' },
    });
    const iron = blueprintPlacementMethod(completeBlockStateDefaults(
      'minecraft:iron_door[half=lower,open=true]',
    ).state);
    expect(iron.item).toBeNull();
    if (iron.item === null) expect(iron.reason).toContain('不能徒手切到 open=true');
  });
});
