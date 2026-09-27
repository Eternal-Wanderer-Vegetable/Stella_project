import { describe, expect, it } from 'vitest';
import {
  BlueprintValidationError,
  blockIdOf,
  canonicalizeBlockState,
  isAirState,
  multiPartRole,
  normalizeBlockName,
  normalizeBlueprint,
  renderLayerMap,
  tryNormalizeBlueprint,
  validateBlueprintLabel,
  voxelMetrics,
} from '../../../src/worlds/minecraft/blueprint.ts';

const STONE = 'minecraft:stone';
const AIR = 'minecraft:air';

describe('palette 解析', () => {
  it('把索引矩阵展开成完整状态串', () => {
    expect(normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [2, 1, 1],
      axis_order: 'YZX',
      palette: [AIR, 'minecraft:oak_log[axis=y]'],
      layers: [[[1, 0]]],
    })).toEqual({
      size_xyz: [2, 1, 1],
      site_mode: 'retrofit',
      layers: [[['minecraft:oak_log[axis=y]', AIR]]],
    });
  });

  it('收 {Name, Properties} 写法并规范化属性顺序', () => {
    expect(canonicalizeBlockState(
      'minecraft:oak_stairs[waterlogged=false,shape=straight,half=bottom,facing=north]',
    )).toBe('minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]');

    const normalized = normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [2, 1, 1],
      palette: [AIR, { Name: 'minecraft:oak_log', Properties: { axis: 'y' } }],
      layers: [[[1, 0]]],
    });
    expect(normalized.layers).toEqual([[['minecraft:oak_log[axis=y]', AIR]]]);
  });

  it('没有 palette 字段时按逐格状态串读', () => {
    expect(normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [1, 1, 2],
      layers: [[[STONE], [AIR]]],
    }).layers).toEqual([[[STONE], [AIR]]]);
  });

  it.each([
    {
      name: '没写 site_mode',
      value: { size_xyz: [1, 1, 1], palette: [AIR], layers: [[[0]]] },
      path: 'site_mode',
    },
    {
      name: '层数不对',
      value: { site_mode: 'retrofit', size_xyz: [1, 2, 1], palette: [AIR], layers: [[[0]]] },
      path: 'layers',
    },
    {
      name: '行数不对',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 2], palette: [AIR], layers: [[[0]]] },
      path: 'layers[0]',
    },
    {
      name: '行长不对',
      value: { site_mode: 'retrofit', size_xyz: [2, 1, 1], palette: [AIR], layers: [[[0]]] },
      path: 'layers[0][0]',
    },
    {
      name: 'palette 索引越界',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: [AIR], layers: [[[1]]] },
      path: 'layers[0][0][0]',
    },
    {
      name: '这一格不是整数',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: [AIR], layers: [[['minecraft:stone']]] },
      path: 'layers[0][0][0]',
    },
    {
      name: 'palette 条目不带命名空间',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: ['stone'], layers: [[[0]]] },
      path: 'palette[0]',
    },
    {
      name: '属性写了两遍',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: ['minecraft:oak_log[axis=x,axis=y]'], layers: [[[0]]] },
      path: 'palette[0]',
    },
    {
      name: '轴序不是 YZX',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 1], axis_order: 'XYZ', palette: [AIR], layers: [[[0]]] },
      path: 'axis_order',
    },
    {
      // 大小写不一致归宽容层管,严格口径一字不差
      name: '轴序大小写不一致',
      value: { site_mode: 'retrofit', size_xyz: [1, 1, 1], axis_order: 'yzx', palette: [AIR], layers: [[[0]]] },
      path: 'axis_order',
    },
    {
      name: '尺寸不是三个正整数',
      value: { site_mode: 'retrofit', size_xyz: [1, 0, 1], palette: [AIR], layers: [[[0]]] },
      path: 'size_xyz[1]',
    },
    {
      name: '矩阵里有空洞',
      value: { site_mode: 'retrofit', size_xyz: [2, 1, 1], palette: [AIR], layers: [[[0, ,]]] },
      path: 'layers[0][0][1]',
    },
  ])('点名拒绝:$name', ({ value, path }) => {
    expect(() => normalizeBlueprint(value)).toThrow(BlueprintValidationError);
    const result = tryNormalizeBlueprint(value);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.path).toBe(path);
  });

  it('核对声明尺寸', () => {
    expect(() => normalizeBlueprint(
      { site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: [AIR], layers: [[[0]]] },
      { expectedSize: [2, 1, 1] },
    )).toThrow('[2,1,1]');
  });
});

describe('信封字段', () => {
  it('收合法键与可选人话名字', () => {
    expect(validateBlueprintLabel({ key: 'home-v2', name: ' 新家 ' })).toEqual({
      key: 'home-v2',
      name: '新家',
    });
    expect(validateBlueprintLabel({ key: 'shed' })).toEqual({ key: 'shed', name: null });
  });

  it('拒绝大写与超长的键', () => {
    expect(() => validateBlueprintLabel({ key: 'Home' })).toThrow('key');
    expect(() => validateBlueprintLabel({ key: 'x'.repeat(33) })).toThrow('key');
  });
});

describe('空气族与方块名', () => {
  it.each(['minecraft:air', 'minecraft:cave_air', 'minecraft:void_air', 'minecraft:structure_void'])(
    '%s 算空气',
    (state) => expect(isAirState(state)).toBe(true),
  );

  it('带属性的方块不会被当成空气', () => {
    expect(isAirState('minecraft:oak_stairs[facing=north]')).toBe(false);
    expect(blockIdOf('minecraft:oak_stairs[facing=north]')).toBe('minecraft:oak_stairs');
  });

  it('世界读回来的裸名字补上命名空间', () => {
    expect(normalizeBlockName('stone')).toBe(STONE);
    expect(normalizeBlockName('minecraft:stone')).toBe(STONE);
  });
});

describe('多部件方块', () => {
  it('门与高草按上下两格,上半格是从部件', () => {
    expect(multiPartRole('minecraft:oak_door[facing=north,half=lower,hinge=left,open=false,powered=false]'))
      .toEqual({ role: 'main', secondaryOffset: [0, 1, 0] });
    expect(multiPartRole('minecraft:oak_door[facing=north,half=upper,hinge=left,open=false,powered=false]'))
      .toEqual({ role: 'secondary', mainOffset: [0, -1, 0] });
    expect(multiPartRole('minecraft:tall_grass[half=upper]'))
      .toEqual({ role: 'secondary', mainOffset: [0, -1, 0] });
  });

  it('床按 facing 横向两格,床头是从部件', () => {
    expect(multiPartRole('minecraft:white_bed[facing=south,occupied=false,part=foot]'))
      .toEqual({ role: 'main', secondaryOffset: [0, 0, 1] });
    expect(multiPartRole('minecraft:white_bed[facing=south,occupied=false,part=head]'))
      .toEqual({ role: 'secondary', mainOffset: [0, 0, -1] });
  });

  it('楼梯活板门的 half=top/bottom 不会被误判成两格', () => {
    expect(multiPartRole('minecraft:oak_stairs[facing=north,half=top,shape=straight,waterlogged=false]'))
      .toEqual({ role: 'single' });
    expect(multiPartRole('minecraft:oak_slab[type=top,waterlogged=false]'))
      .toEqual({ role: 'single' });
  });
});

describe('体素指标与逐层图', () => {
  const blueprint = normalizeBlueprint({
    site_mode: 'retrofit',
    size_xyz: [2, 2, 2],
    palette: [AIR, STONE, 'minecraft:oak_planks'],
    layers: [
      [[1, 1], [1, 2]],
      [[0, 0], [0, 2]],
    ],
  });

  it('数格子并给非空气包围盒', () => {
    const metrics = voxelMetrics(blueprint);
    expect(metrics.totalCells).toBe(8);
    expect(metrics.nonAirCells).toBe(5);
    expect(metrics.airCells).toBe(3);
    expect(metrics.fillRate).toBe(0.63);
    expect(metrics.uniqueBlockStates).toBe(3);
    expect(metrics.blockIdHistogram).toEqual({
      'minecraft:stone': 3,
      'minecraft:air': 3,
      'minecraft:oak_planks': 2,
    });
    expect(metrics.nonAirBounds).toEqual({ min: [0, 0, 0], max: [1, 1, 1], size: [2, 2, 2] });
  });

  it('逐层图按格数分配字符,空气固定是点', () => {
    const map = renderLayerMap(blueprint);
    expect(map.legend).toEqual([
      { char: 'A', state: STONE, cells: 3 },
      { char: 'B', state: 'minecraft:oak_planks', cells: 2 },
    ]);
    expect(map.layers[0]).toEqual({ y: 0, nonAirCells: 4, rows: ['AA', 'AB'] });
    expect(map.layers[1]).toEqual({ y: 1, nonAirCells: 1, rows: ['..', '.B'] });
  });

  it('整份空气时没有包围盒', () => {
    const empty = normalizeBlueprint({ site_mode: 'retrofit', size_xyz: [1, 1, 1], palette: [AIR], layers: [[[0]]] });
    expect(voxelMetrics(empty).nonAirBounds).toBeNull();
  });
});
