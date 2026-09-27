import { describe, expect, it } from 'vitest';
import { normalizeBlueprint } from '../../../src/worlds/minecraft/blueprint.ts';
import {
  completeBlueprintStateDefaults,
  createRepairReport,
  recoverVisibleSubmission,
  repairSubmissionShape,
} from '../../../src/worlds/minecraft/blueprint-repair.ts';

const AIR = 'minecraft:air';
const KEEP = 'minecraft:structure_void';
const STONE = 'minecraft:stone';

describe('正文里的提交回收', () => {
  it('只有唯一一份可辨认的完整提交时才认', () => {
    const recovered = recoverVisibleSubmission(
      '```json\n{"name":"mc_blueprint","parameters":'
      + '{"size_xyz":[1,1,1],"axis_order":"YZX","palette":["minecraft:stone"],"layers":[[[0]]]}}\n```',
      'mc_blueprint',
    );
    expect(recovered).toMatchObject({ size_xyz: [1, 1, 1], axis_order: 'YZX' });
  });

  it('两份不一样的就不认(歧义宁可不救)', () => {
    const text = '```json\n{"size_xyz":[1,1,1],"palette":["minecraft:stone"],"layers":[[[0]]]}\n```'
      + '\n```json\n{"size_xyz":[2,1,1],"palette":["minecraft:stone"],"layers":[[[0,0]]]}\n```';
    expect(recoverVisibleSubmission(text, 'mc_blueprint')).toBeNull();
  });

  it('工具名对不上不认', () => {
    const text = '```json\n{"name":"别的工具","parameters":{"size_xyz":[1,1,1]}}\n```';
    expect(recoverVisibleSubmission(text, 'mc_blueprint')).toBeNull();
  });
});

describe('矩阵形状修复', () => {
  it('轴序缺失或大小写不一致时补成 YZX', () => {
    const repaired = repairSubmissionShape({
      size_xyz: [1, 1, 1], axis_order: 'yzx', palette: [STONE], layers: [[[0]]],
    });
    expect(repaired.submission.axis_order).toBe('YZX');
    expect(repaired.actions.map((action) => action.code)).toEqual(['axis-order-normalization']);
  });

  it('显式尺寸写偏时按实际画出的矩阵登记', () => {
    const repaired = repairSubmissionShape({
      size_xyz: [2, 1, 1],
      axis_order: 'YZX',
      palette: [KEEP, STONE],
      layers: [
        [[1, 1]],
        [[1]],
      ],
    });
    expect(repaired.submission.size_xyz).toEqual([2, 2, 1]);
    expect(repaired.submission.layers).toEqual([[[1, 1]], [[1, 0]]]);
    expect(repaired.actions.map((action) => action.code)).toEqual([
      'declared-size-normalization',
      'dense-grid-fit',
    ]);
  });

  it('参差矩阵只补到实际内容需要的最小长方体', () => {
    const repaired = repairSubmissionShape({
      size_xyz: [2, 2, 1], axis_order: 'YZX', palette: [KEEP, STONE], layers: [[[1, 1]], [[1]]],
    });
    expect(repaired.submission.size_xyz).toEqual([2, 2, 1]);
    expect(repaired.submission.layers).toEqual([[[1, 1]], [[1, 0]]]);
    expect(repaired.actions.map((action) => action.code)).toEqual(['dense-grid-fit']);
  });

  it('palette 里没有 structure_void 时追加一条再补,不拿 air 冒充缺格', () => {
    const repaired = repairSubmissionShape({
      size_xyz: [2, 2, 1], axis_order: 'YZX', palette: [AIR, STONE], layers: [[[1, 1]], [[1]]],
    });
    expect(repaired.submission.palette).toEqual([AIR, STONE, KEEP]);
    expect(repaired.submission.layers).toEqual([[[1, 1]], [[1, 2]]]);
    expect(repaired.actions.map((action) => action.code)).toEqual(['dense-grid-fit']);
  });

  it('尺寸字段缺失时可从完整矩阵读出', () => {
    const repaired = repairSubmissionShape({
      axis_order: 'YZX', palette: [STONE], layers: [[[0, 0]]],
    });
    expect(repaired.submission.size_xyz).toEqual([2, 1, 1]);
    expect(repaired.actions.map((action) => action.code)).toEqual(['declared-size-normalization']);
  });

  it('层里不是数组就原样退回,不猜', () => {
    const repaired = repairSubmissionShape({
      size_xyz: [1, 1, 1], palette: [STONE], layers: 'oops',
    });
    expect(repaired.submission.layers).toBe('oops');
  });
});

describe('默认属性补齐(整份)', () => {
  it('逐格补上漏写的属性并计数', () => {
    const blueprint = normalizeBlueprint({
      site_mode: 'retrofit',
      size_xyz: [2, 1, 1],
      layers: [[['minecraft:white_bed[facing=south,part=foot]', 'minecraft:white_bed[facing=south,part=head]']]],
    });
    const repaired = completeBlueprintStateDefaults(blueprint);
    expect(repaired.blueprint.layers[0][0]).toEqual([
      'minecraft:white_bed[facing=south,occupied=false,part=foot]',
      'minecraft:white_bed[facing=south,occupied=false,part=head]',
    ]);
    expect(repaired.action).toMatchObject({ code: 'default-state-completion', count: 2 });
  });

  it('一条都不用补时 action 是 null', () => {
    const blueprint = normalizeBlueprint({ site_mode: 'retrofit', size_xyz: [1, 1, 1], layers: [[[STONE]]] });
    expect(completeBlueprintStateDefaults(blueprint).action).toBeNull();
  });
});

describe('修复报告', () => {
  it('初始报告是"什么都没动"', () => {
    expect(createRepairReport()).toMatchObject({ strictValid: false, applied: false, actions: [] });
  });
});
