import { describe, expect, it } from 'vitest';
import { acceptBlueprint } from '../../../src/worlds/minecraft/blueprint-plan.ts';
import {
  BlueprintResourceLedger, blueprintContentHash, createBlueprintVersion,
} from '../../../src/worlds/minecraft/blueprint-resource.ts';

function floor(material = 'minecraft:cobblestone') {
  const accepted = acceptBlueprint({
    key: 'home', site_mode: 'new', size_xyz: [2, 1, 2], axis_order: 'YZX',
    palette: [material], layers: [[[0, 0], [0, 0]]],
  });
  if (!accepted.ok || !accepted.blueprint || !accepted.plan) throw new Error('测试蓝图没通过');
  return { blueprint: accepted.blueprint, plan: accepted.plan };
}

describe('蓝图版本身份', () => {
  it('内容 hash 只随规范化矩阵变化；相同内容的两次保存仍有不同 version id', () => {
    const stone = floor();
    const same = floor();
    const wood = floor('minecraft:oak_planks');
    expect(blueprintContentHash(stone.blueprint)).toBe(blueprintContentHash(same.blueprint));
    expect(blueprintContentHash(stone.blueprint)).not.toBe(blueprintContentHash(wood.blueprint));
    expect(createBlueprintVersion(stone.blueprint).versionId)
      .not.toBe(createBlueprintVersion(stone.blueprint).versionId);
  });
});

describe('蓝图剩余材料 reserve', () => {
  it('普通垫路可用库存盈余，触到 reserve 即收口；临时覆盖按实际消耗扣预算并标记补料', () => {
    const { plan } = floor('minecraft:glass');
    const ledger = new BlueprintResourceLedger();
    ledger.sync([{ key: 'home', versionId: 'bpv_test', remaining: plan.steps }]);
    expect(ledger.reserve()).toEqual({ glass: 4 });

    ledger.observe({ glass: 42 }, 100);
    expect(ledger.collapsedItems({ glass: 42 }, 100)).toEqual([]);
    expect(ledger.orderScaffoldCandidates(['dirt', 'glass'], { glass: 42 }, 100))
      .toEqual(['dirt', 'glass']);
    expect(ledger.placementDecision('glass', { glass: 42 }, 100))
      .toEqual({ ok: true, source: 'surplus' });
    expect(ledger.placementDecision('torch', { torch: 8 }, 100))
      .toEqual({ ok: true, source: 'unreserved' });
    expect(ledger.observe({ glass: 4 }, 101).retune).toBe(true);
    expect(ledger.collapsedItems({ glass: 4 }, 101)).toEqual(['glass']);
    // 收口只降位不删除:硬否决全在 placementDecision 一处
    expect(ledger.orderScaffoldCandidates(['dirt', 'glass'], { glass: 4 }, 101))
      .toEqual(['dirt', 'glass']);
    expect(ledger.placementDecision('glass', { glass: 4 }, 101)).toEqual({
      ok: false,
      reason: 'glass 的蓝图 reserve 是 4,随身只有 4;要动它先用 mc_blueprint 的 reserve_override',
    });

    const lease = ledger.openOverride({ reason: '两血脱困', ttlMs: 30_000, maxBlocks: 2 }, 102);
    expect(ledger.collapsedItems({ glass: 4 }, 102)).toEqual([]);
    expect(ledger.placementDecision('glass', { glass: 4 }, 102))
      .toEqual({ ok: true, source: 'override' });
    expect(ledger.observe({ glass: 3 }, 103).borrowed).toEqual({ glass: 1 });
    const spent = ledger.observe({ glass: 2 }, 104);
    expect(spent.borrowed).toEqual({ glass: 1 });
    expect(spent.retune).toBe(true);
    expect(ledger.activeOverride(104)).toBeNull();
    expect(ledger.collapsedItems({ glass: 2 }, 104)).toEqual(['glass']);
    expect(ledger.orderScaffoldCandidates(['glass'], { glass: 2 }, 104)).toEqual(['glass']);
    expect(ledger.placementDecision('glass', { glass: 2 }, 104)).toMatchObject({ ok: false });
    expect(ledger.restockMarkers().at(-1)).toMatchObject({
      overrideId: lease.id, reason: '两血脱困', maxBlocks: 2,
      borrowed: { glass: 2 },
    });
    expect(ledger.sync([{ key: 'home', versionId: 'bpv_test', remaining: [] }])).toBe(true);
    expect(ledger.collapsedItems({ glass: 2 }, 105)).toEqual([]);
  });

  it('被蓝图预留收口的垫脚候选只降到末位,名单永不被扣空', () => {
    const { plan } = floor('minecraft:glass');
    const ledger = new BlueprintResourceLedger();
    ledger.sync([{ key: 'home', versionId: 'bpv_test', remaining: plan.steps }]);

    // 收口的排最后,可用的保持原顺序(优先级即顺序)
    expect(ledger.orderScaffoldCandidates(['glass', 'dirt', 'cobblestone'], { glass: 4, dirt: 3 }, 10))
      .toEqual(['dirt', 'cobblestone', 'glass']);
    // 名单里只有收口的那一样时也照给:空数组只该出自她自己关掉 scaffold
    expect(ledger.orderScaffoldCandidates(['glass'], { glass: 4 }, 10)).toEqual(['glass']);
    expect(ledger.orderScaffoldCandidates([], { glass: 4 }, 10)).toEqual([]);
    // 有盈余时不动顺序
    expect(ledger.orderScaffoldCandidates(['glass', 'dirt'], { glass: 42 }, 10))
      .toEqual(['glass', 'dirt']);
  });

  it('豁免名单跟着当前生效的垫脚名单走,不再硬编码泥土圆石木板', () => {
    const materials = ['dirt', 'cobblestone', 'oak_planks', 'sandstone'];
    const projects = materials.map((item) => ({
      key: item,
      versionId: `bpv_${item}`,
      remaining: floor(`minecraft:${item}`).plan.steps,
    }));

    // 她把垫脚料改成砂岩:砂岩不再进 reserve,没在名单里的木板反倒该锁住
    let scaffold: string[] = ['dirt', 'cobblestone', 'sandstone'];
    const ledger = new BlueprintResourceLedger({ scaffold: () => scaffold });
    ledger.sync(projects);
    expect(ledger.reserve()).toEqual({ oak_planks: 4 });
    for (const item of ['dirt', 'cobblestone', 'sandstone']) {
      expect(ledger.placementDecision(item, { [item]: 0 })).toEqual({ ok: true, source: 'unreserved' });
    }
    expect(ledger.placementDecision('oak_planks', { oak_planks: 4 })).toMatchObject({ ok: false });

    // 名单是现读的:改回默认那份,同一批工程的 reserve 当场换一套
    scaffold = ['dirt', 'cobblestone'];
    expect(ledger.reserve()).toEqual({ oak_planks: 4, sandstone: 4 });

    // 取舍:主料恰好在名单里的蓝图整份不进 reserve
    scaffold = ['dirt', 'cobblestone', 'oak_planks', 'sandstone'];
    expect(ledger.reserve()).toEqual({});
  });

  it('照明名单与垫脚名单同路豁免:policy 说能插的火把不被蓝图 reserve 锁走', () => {
    // 照明名单中的物品不进入蓝图 reserve。
    const projects = ['torch', 'oak_planks'].map((item) => ({
      key: item,
      versionId: `bpv_${item}`,
      remaining: floor(`minecraft:${item}`).plan.steps,
    }));
    let light: string[] = ['torch'];
    const ledger = new BlueprintResourceLedger({ light: () => light });
    ledger.sync(projects);
    expect(ledger.reserve()).toEqual({ oak_planks: 4 });
    expect(ledger.placementDecision('torch', { torch: 2 })).toEqual({ ok: true, source: 'unreserved' });

    // 名单是现读的:她把照明关掉([]),火把当场回到 reserve
    light = [];
    expect(ledger.reserve()).toEqual({ oak_planks: 4, torch: 4 });
    expect(ledger.placementDecision('torch', { torch: 2 })).toMatchObject({ ok: false });
  });

  it('箱子里囤够的部分不再锁随身;不够时按差额收口', () => {
    const { plan } = floor('minecraft:glass');
    let stored: Record<string, number> = {};
    const ledger = new BlueprintResourceLedger({ stored: () => stored });
    ledger.sync([{ key: 'home', versionId: 'bpv_test', remaining: plan.steps }]);
    expect(ledger.reserve()).toEqual({ glass: 4 });

    // 箱子囤满 4 格所需:背包里那 4 块玻璃可以随便垫
    stored = { glass: 4 };
    expect(ledger.reserve()).toEqual({});
    expect(ledger.collapsedItems({ glass: 4 }, 10)).toEqual([]);
    expect(ledger.orderScaffoldCandidates(['glass', 'dirt'], { glass: 4 }, 10)).toEqual(['glass', 'dirt']);
    expect(ledger.placementDecision('glass', { glass: 4 }, 10)).toEqual({ ok: true, source: 'unreserved' });

    // 箱子只有 3 块:差额 1 仍收口,随身 1 块不够盈余
    stored = { glass: 3 };
    expect(ledger.reserve()).toEqual({ glass: 1 });
    expect(ledger.placementDecision('glass', { glass: 1 }, 10)).toMatchObject({ ok: false });
    // 放置可用性仍只看随身:箱子里有 3 块也补不了手里的空
    expect(ledger.placementDecision('glass', { glass: 2 }, 10)).toEqual({ ok: true, source: 'surplus' });
  });

  it('TTL 到点后候选恢复保护', () => {
    const { plan } = floor('minecraft:glass');
    const ledger = new BlueprintResourceLedger();
    ledger.sync([{ key: 'home', versionId: 'bpv_test', remaining: plan.steps }]);
    ledger.observe({ glass: 4 }, 10);
    ledger.openOverride({ reason: '过窄侧岸', ttlMs: 20, maxBlocks: 8 }, 10);
    expect(ledger.collapsedItems({ glass: 4 }, 29)).toEqual([]);
    expect(ledger.collapsedItems({ glass: 4 }, 30)).toEqual(['glass']);
  });

  it('同一材料的 reserve 数量下降会触发同步，并重新放行新出现的库存盈余', () => {
    const { plan } = floor('minecraft:glass');
    const ledger = new BlueprintResourceLedger();
    ledger.observe({ glass: 4 }, 10);
    expect(ledger.sync([{
      key: 'home', versionId: 'bpv_a', remaining: [{ ...plan.steps[0], cells: 5 }],
    }])).toBe(true);
    expect(ledger.collapsedItems({ glass: 4 }, 10)).toEqual(['glass']);

    expect(ledger.sync([{
      key: 'home', versionId: 'bpv_a', remaining: [{ ...plan.steps[0], cells: 3 }],
    }])).toBe(true);
    expect(ledger.reserve()).toEqual({ glass: 3 });
    expect(ledger.collapsedItems({ glass: 4 }, 11)).toEqual([]);
  });

  it('临时覆盖未借出材料就到期时不创建需补料标记', () => {
    const { plan } = floor('minecraft:glass');
    const ledger = new BlueprintResourceLedger();
    ledger.sync([{ key: 'home', versionId: 'bpv_test', remaining: plan.steps }]);
    ledger.observe({ glass: 4 }, 10);
    ledger.openOverride({ reason: '试探侧岸', ttlMs: 20, maxBlocks: 2 }, 10);

    expect(ledger.restockMarkers()).toEqual([]);
    expect(ledger.activeOverride(30)).toBeNull();
    expect(ledger.restockMarkers()).toEqual([]);
  });
});
