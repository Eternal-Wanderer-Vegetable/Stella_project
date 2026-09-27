import { describe, expect, it } from 'vitest';
import {
  parseAssert, parseChecks, evalAssert, renderChecks, blueprintCheckText,
  CHECK_BOX_CELL_CAP, CHECK_MAX_ASSERTS, CHECK_SEALED_VOLUME_CAP,
  type CheckParsed, type CheckSite, type CheckWorld,
} from '../../../src/worlds/minecraft/check.ts';
import { acceptBlueprint } from '../../../src/worlds/minecraft/blueprint-plan.ts';

/** 碰撞箱占满整格的那几样(测试世界里够用了) */
const SOLID = new Set(['stone', 'oak_planks', 'chest', 'dirt', 'cobblestone', 'oak_log', 'furnace']);

interface FakeWorldOptions {
  /** "x,y,z" → 方块状态串;没写到的格按 fill 算 */
  cells?: Record<string, string>;
  /** 没写到的格是什么;null = 那一带区块没加载 */
  fill?: string | null;
  /** 这几格明确当成没加载 */
  unloaded?: string[];
  inv?: Record<string, number>;
  /** 物品名 → 每一摞各带什么附魔(一摞一条) */
  enchants?: Record<string, Array<Array<{ name: string; level: number }>>>;
  sites?: Record<string, CheckSite>;
  marks?: CheckWorld['mark'];
  known?: string[];
}

function fakeWorld(opts: FakeWorldOptions = {}): CheckWorld {
  const { cells = {}, fill = 'air', unloaded = [] } = opts;
  const off = new Set(unloaded);
  return {
    cell: (x, y, z) => {
      const key = `${x},${y},${z}`;
      if (off.has(key)) return null;
      const state = cells[key] ?? fill;
      if (state === null) return null;
      const id = state.split('[')[0];
      return { state, solid: SOLID.has(id) };
    },
    inventory: () => new Map(Object.entries(opts.inv ?? {})),
    ...(opts.enchants ? { enchantsOf: (item: string) => opts.enchants![item] ?? [] } : {}),
    knowsBlock: opts.known ? (id) => opts.known!.includes(id) : undefined,
    site: (key) => opts.sites?.[key] ?? null,
    mark: opts.marks ?? (() => null),
  };
}

/** 一条断言直接求值:受理失败当场炸,免得断言写错了还看着像"不符" */
function evalOne(raw: unknown, world: CheckWorld): { verdict: string; text: string } {
  const parsed = parseAssert(raw);
  if (!parsed.ok) throw new Error(`受理失败:${parsed.error}`);
  return evalAssert(parsed.assert, world);
}

describe('mc_check · 单格断言 {at, is}', () => {
  it('对上只说是什么,对不上点名两边;id 级比对,朝向不算数', () => {
    const world = fakeWorld({ cells: { '10,64,10': 'chest[facing=north,type=single]' } });
    expect(evalOne({ at: [10, 64, 10], is: 'chest' }, world))
      .toEqual({ verdict: 'ok', text: '(10, 64, 10) 是箱子' });
    expect(evalOne({ at: [10, 64, 10], is: 'furnace' }, world))
      .toEqual({ verdict: 'bad', text: '(10, 64, 10) 该是熔炉,现在是箱子' });
  });

  it('is:"air" = 这格该空着;三种空气都算空着', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'cave_air', '1,0,0': 'stone' } });
    expect(evalOne({ at: [0, 0, 0], is: 'air' }, world).verdict).toBe('ok');
    expect(evalOne({ at: [1, 0, 0], is: 'air' }, world))
      .toEqual({ verdict: 'bad', text: '(1, 0, 0) 该是空气,现在是石头' });
  });

  it('区块没加载自成一档:既不算符合也不算不符', () => {
    const world = fakeWorld({ unloaded: ['5,64,5'] });
    expect(evalOne({ at: [5, 64, 5], is: 'chest' }, world))
      .toEqual({ verdict: 'unknown', text: '(5, 64, 5) 区块没加载,走近再对' });
  });

  it('minecraft: 前缀与大小写都收', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'chest' } });
    expect(evalOne({ at: [0, 0, 0], is: 'minecraft:Chest' }, world).verdict).toBe('ok');
  });
});

describe('mc_check · 区域计数 {box, count}', () => {
  const world = fakeWorld({
    cells: {
      '0,0,0': 'chest', '1,0,0': 'chest',
      '2,0,0': 'torch', '3,0,0': 'torch', '0,0,1': 'torch',
    },
  });
  const box: [number[], number[]] = [[0, 0, 0], [3, 0, 1]];

  it('整数 = 恰好;数够了才算符合', () => {
    expect(evalOne({ box, count: { chest: 2 } }, world).verdict).toBe('ok');
    const short = evalOne({ box, count: { chest: 4 } }, world);
    expect(short.verdict).toBe('bad');
    expect(short.text).toContain('箱子 2(要 4)');
  });

  it('">=N" / "<=N" 是一侧的界', () => {
    expect(evalOne({ box, count: { torch: '>=3' } }, world).verdict).toBe('ok');
    expect(evalOne({ box, count: { torch: '>=8' } }, world).text).toContain('火把 3(要 ≥8)');
    expect(evalOne({ box, count: { torch: '<=2' } }, world).verdict).toBe('bad');
    expect(evalOne({ box, count: { chest: '<=2' } }, world).verdict).toBe('ok');
  });

  it('一条里几样一起数:只有不符的那几样进回执', () => {
    const said = evalOne({ box, count: { chest: 2, torch: '>=8' } }, world);
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('火把 3(要 ≥8)');
    expect(said.text).not.toContain('箱子');
  });

  it('区域里有没加载的格:数得出来的照报,但结论是"数不准"', () => {
    const partial = fakeWorld({ cells: { '0,0,0': 'chest' }, unloaded: ['1,0,0'] });
    const said = evalOne({ box: [[0, 0, 0], [1, 0, 0]], count: { chest: 1 } }, partial);
    expect(said.verdict).toBe('unknown');
    expect(said.text).toContain('1 格没加载,数不准');
  });

  it('数不够的时候也把没加载的格说出来', () => {
    const partial = fakeWorld({ cells: { '0,0,0': 'chest' }, unloaded: ['1,0,0'] });
    const said = evalOne({ box: [[0, 0, 0], [1, 0, 0]], count: { chest: 4 } }, partial);
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('另有 1 格没加载,没对全');
  });
});

describe('mc_check · 区域全同 {box, all} 与全空 {box, air}', () => {
  it('全同:不符的逐格点名,超过样本上限报"还有 N 格"', () => {
    const cells: Record<string, string> = {};
    for (let x = 0; x < 10; x++) cells[`${x},0,0`] = x < 2 ? 'oak_planks' : 'stone';
    const world = fakeWorld({ cells });
    const said = evalOne({ box: [[0, 0, 0], [9, 0, 0]], all: 'oak_planks' }, world);
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('10 格里 8 格不是橡木木板');
    expect(said.text).toContain('(2, 0, 0) 是石头');
    expect(said.text).toContain('还有 2 格');
  });

  it('全同:都对上只报总数', () => {
    const world = fakeWorld({ fill: 'oak_planks' });
    expect(evalOne({ box: [[0, 0, 0], [1, 1, 1]], all: 'oak_planks' }, world))
      .toEqual({ verdict: 'ok', text: '(0, 0, 0)–(1, 1, 1) 8 格都是橡木木板' });
  });

  it('全空:三种空气都算空着,有东西就点名', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'void_air', '1,0,0': 'dirt' } });
    expect(evalOne({ box: [[0, 0, 0], [0, 0, 0]], air: true }, world).verdict).toBe('ok');
    const said = evalOne({ box: [[0, 0, 0], [1, 0, 0]], air: true }, world);
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('2 格里 1 格不是空的:(1, 0, 0) 是泥土');
  });

  it('两个角谁大谁小随便写', () => {
    const world = fakeWorld({ fill: 'stone' });
    expect(evalOne({ box: [[3, 0, 3], [0, 0, 0]], all: 'stone' }, world).verdict).toBe('ok');
  });

  it('全读不到时给的是"没对全",不是"都对上了"', () => {
    const world = fakeWorld({ fill: null });
    const said = evalOne({ box: [[0, 0, 0], [1, 0, 0]], all: 'stone' }, world);
    expect(said.verdict).toBe('unknown');
    expect(said.text).toContain('2 格没加载,没对全');
  });
});

describe('mc_check · 封闭性 {box, sealed}', () => {
  /** 5×5×5 的空心石头盒子:内腔 (1..3)³;`patch` 换掉壳上的某几格 */
  function shell(patch: Record<string, string> = {}, unloaded: string[] = []): CheckWorld {
    const cells: Record<string, string> = {};
    for (let x = 0; x <= 4; x++) {
      for (let y = 0; y <= 4; y++) {
        for (let z = 0; z <= 4; z++) {
          const wall = x === 0 || x === 4 || y === 0 || y === 4 || z === 0 || z === 4;
          cells[`${x},${y},${z}`] = wall ? 'stone' : 'air';
        }
      }
    }
    return fakeWorld({ cells: { ...cells, ...patch }, fill: 'air', unloaded });
  }

  /** 壳上开的洞:那一格换成空气 */
  const holes = (...at: string[]): Record<string, string> =>
    Object.fromEntries(at.map((k) => [k, 'air']));

  const box: [number[], number[]] = [[0, 0, 0], [4, 4, 4]];

  it('壳完整就是封闭:报洪泛走了几格', () => {
    const said = evalOne({ box, sealed: true }, shell());
    expect(said.verdict).toBe('ok');
    expect(said.text).toContain('封闭');
    expect(said.text).toContain('从 (2, 2, 2) 洪泛 27 格');
  });

  it('壳上开一格就是漏:漏口报的是盒内那一格,也就是要堵的那一格本身', () => {
    const said = evalOne({ box, sealed: true }, shell(holes('4,2,2')));
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('不封闭:1 个漏口,最近的在 (4, 2, 2)');
  });

  it('漏口样本封顶三处,总数照报', () => {
    const said = evalOne({ box, sealed: true }, shell(holes('4,1,1', '4,2,2', '4,3,3', '0,1,1')));
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('4 个漏口');
    const samples = said.text.slice(said.text.indexOf('漏口')).match(/\(\d+, \d+, \d+\)/g) ?? [];
    expect(samples).toHaveLength(3);
  });

  it('水按通路算:拿水当墙的那一面不封闭,回执把这个口径说出来', () => {
    const said = evalOne({ box, sealed: true }, shell({ '4,2,2': 'water[level=0]' }));
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('液体按通路算,水会灌进来');
    expect(evalOne({ box, sealed: true }, shell()).verdict).toBe('ok');
  });

  it('from 给了就从那儿起步;不在盒子里当场退回', () => {
    expect(evalOne({ box, sealed: true, from: [1, 1, 1] }, shell()).text)
      .toContain('从 (1, 1, 1) 洪泛');
    const outside = parseAssert({ box, sealed: true, from: [99, 0, 0] });
    expect(outside).toEqual({ ok: false, error: 'from (99, 0, 0) 不在 (0, 0, 0)–(4, 4, 4) 里面' });
  });

  it('盒中心是实心时就近找盒内的空格', () => {
    const cells: Record<string, string> = {};
    for (let x = 0; x <= 4; x++) {
      for (let y = 0; y <= 4; y++) {
        for (let z = 0; z <= 4; z++) cells[`${x},${y},${z}`] = 'stone';
      }
    }
    cells['1,2,2'] = 'air';
    const said = evalOne({ box, sealed: true }, fakeWorld({ cells }));
    expect(said).toEqual({ verdict: 'ok', text: '(0, 0, 0)–(4, 4, 4) 封闭(从 (1, 2, 2) 洪泛 1 格,没走出去)' });
  });

  it('整个盒子实心:没有起步的地方,照实说,不当成"封闭"', () => {
    const said = evalOne({ box, sealed: true }, fakeWorld({ fill: 'stone' }));
    expect(said.verdict).toBe('error');
    expect(said.text).toContain('没有可站的空格');
  });

  it('有格没加载:没找到漏口也只说"没对全",不宣布封闭;读不到的格按坐标去重', () => {
    // (2,2,3) 是内腔的一格,六个方向里有五个是能洪泛到的空气 —— 不去重就会报成 5 格
    const said = evalOne({ box, sealed: true }, shell({}, ['2,2,3']));
    expect(said.verdict).toBe('unknown');
    expect(said.text).toContain('周边 1 格没加载,没对全');
  });

  it('体积超限当场拒算,说清上限', () => {
    const huge = parseAssert({ box: [[0, 0, 0], [63, 63, 63]], sealed: true });
    expect(huge.ok).toBe(false);
    expect((huge as { error: string }).error).toContain(String(CHECK_SEALED_VOLUME_CAP));
  });
});

describe('mc_check · 背包 {inv}', () => {
  const world = fakeWorld({ inv: { torch: 5, bread: 3, oak_planks: 12, birch_planks: 4 } });

  it('措辞注明"包里现有";够了不点名,不够点名', () => {
    expect(evalOne({ inv: { bread: 3 } }, world))
      .toEqual({ verdict: 'ok', text: '包里现有:面包 3(要 3)' });
    const said = evalOne({ inv: { torch: '>=8' } }, world);
    expect(said.verdict).toBe('bad');
    expect(said.text).toBe('包里现有:火把 5(要 ≥8)');
  });

  /**
   * mc_check 按精确物品名对账；核对整族物品时逐项列出，避免把近似名称合计。
   */
  it('名字精确对:裸类别名不再把同族一起算进去', () => {
    expect(evalOne({ inv: { planks: '>=1' } }, world).verdict).toBe('bad');
    expect(evalOne({ inv: { oak_planks: 12, birch_planks: 4 } }, world).verdict).toBe('ok');
  });

  it('一样都没有也是一个读数,不是错', () => {
    expect(evalOne({ inv: { diamond: 1 } }, world))
      .toEqual({ verdict: 'bad', text: '包里现有:钻石 0(要 1)' });
  });

  /** 「我包里哪几件是附了魔的」在快照里看得见,对账通道也得能问 */
  it('值写成 {enchant:…} 就问带这个附魔的有几件,并把包里那几件念出来', () => {
    const w = fakeWorld({
      inv: { diamond_pickaxe: 2 },
      enchants: {
        diamond_pickaxe: [
          [{ name: 'efficiency', level: 4 }, { name: 'unbreaking', level: 3 }],
          [],
        ],
      },
    });
    const hit = evalOne({ inv: { diamond_pickaxe: { enchant: 'efficiency' } } }, w);
    expect(hit.verdict).toBe('ok');
    expect(hit.text).toContain('钻石镐 带效率的 1 件(要 ≥1');
    expect(hit.text).toContain('效率IV·耐久III / 没附魔');

    const miss = evalOne({ inv: { diamond_pickaxe: { enchant: 'fortune' } } }, w);
    expect(miss.verdict).toBe('bad');
    expect(miss.text).toContain('带时运的 0 件');
  });

  it('带 count 就按那个数比', () => {
    const w = fakeWorld({
      inv: { diamond_pickaxe: 1 },
      enchants: { diamond_pickaxe: [[{ name: 'efficiency', level: 4 }]] },
    });
    expect(evalOne({ inv: { diamond_pickaxe: { enchant: 'efficiency', count: 2 } } }, w).verdict).toBe('bad');
  });

  it('读不到附魔的部署如实说读不到,不拿「没有」冒充', () => {
    expect(evalOne({ inv: { diamond_pickaxe: { enchant: 'efficiency' } } }, world).text)
      .toContain('附魔读不到');
  });

  it('enchant 那个对象缺 enchant 名就地报错,不猜她要问什么', () => {
    expect(parseAssert({ inv: { diamond_pickaxe: { count: 1 } } }))
      .toEqual({ ok: false, error: 'inv["diamond_pickaxe"] 那个对象要一个 enchant 附魔名' });
  });
});

describe('mc_check · 蓝图 {blueprint}', () => {
  const design = acceptBlueprint({
    site_mode: 'new',
    size_xyz: [2, 1, 1],
    palette: ['minecraft:oak_planks'],
    layers: [[[0, 0]]],
  });

  function site(anchor: [number, number, number] | null): CheckSite {
    return {
      key: 'home-useful-v2',
      name: null,
      blueprint: design.blueprint!,
      plan: design.plan!,
      anchor,
    };
  }

  it('整张图到位:一句话带过', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'oak_planks', '1,0,0': 'oak_planks' } });
    const said = blueprintCheckText(site([0, 0, 0]), 'home-useful-v2', world);
    expect(said.verdict).toBe('ok');
    expect(said.text).toBe('蓝图「home-useful-v2」对上 2/2 格,整张图都到位了');
  });

  it('缺格点名:什么方块在哪', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'oak_planks' } });
    const said = blueprintCheckText(site([0, 0, 0]), 'home-useful-v2', world);
    expect(said.verdict).toBe('bad');
    expect(said.text).toContain('对上 1/2 格');
    expect(said.text).toContain('缺 1 格(橡木木板 在 (1, 0, 0))');
  });

  it('放错东西的那几格算冲突', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'oak_planks', '1,0,0': 'cobblestone' } });
    const said = blueprintCheckText(site([0, 0, 0]), 'home-useful-v2', world);
    expect(said.text).toContain('冲突 1 格');
  });

  it('没装载 / 没绑锚点都照实说,不拿 0/0 充数', () => {
    const world = fakeWorld();
    expect(blueprintCheckText(null, 'nope', world))
      .toEqual({ verdict: 'error', text: '蓝图「nope」没装载,对不了' });
    const unbound = blueprintCheckText(site(null), 'home-useful-v2', world);
    expect(unbound.verdict).toBe('error');
    expect(unbound.text).toContain('还没绑锚点');
  });

  it('区块没加载:说没对全,不当成缺格', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'oak_planks' }, unloaded: ['1,0,0'] });
    const said = blueprintCheckText(site([0, 0, 0]), 'home-useful-v2', world);
    expect(said.verdict).toBe('unknown');
    expect(said.text).toContain('1 格没加载,没对全');
    expect(said.text).not.toContain('缺 ');
  });

  it('走 {blueprint:key} 这条断言进来是同一份账', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'oak_planks', '1,0,0': 'oak_planks' } });
    const withSite = fakeWorld({
      cells: { '0,0,0': 'oak_planks', '1,0,0': 'oak_planks' },
      sites: { 'home-useful-v2': site([0, 0, 0]) },
    });
    expect(evalOne({ blueprint: 'home-useful-v2' }, withSite))
      .toEqual(blueprintCheckText(site([0, 0, 0]), 'home-useful-v2', world));
  });
});

describe('mc_check · 路标 {mark}', () => {
  it('对得上只说还是什么;对不上把两边都说清', () => {
    const ok = fakeWorld({
      marks: () => ({
        name: '熔炉', kind: '工作站', dimension: 'minecraft:overworld',
        pos: [1, 2, 3], verdict: 'ok', found: null,
      }),
    });
    expect(evalOne({ mark: '熔炉' }, ok))
      .toEqual({ verdict: 'ok', text: '「熔炉」[主世界] (1, 2, 3) 还是工作站' });
    const bad = fakeWorld({
      marks: () => ({
        name: '熔炉', kind: '工作站', dimension: 'minecraft:overworld',
        pos: [1, 2, 3], verdict: 'mismatch', found: '空气',
      }),
    });
    expect(evalOne({ mark: '熔炉' }, bad))
      .toEqual({ verdict: 'bad', text: '「熔炉」登记的是工作站,[主世界] (1, 2, 3) 现在是空气' });
  });

  it('核不了的 kind 与没登记过的名字分开说', () => {
    const unchecked = fakeWorld({
      marks: () => ({
        name: '矿洞', kind: '资源点', dimension: 'minecraft:overworld',
        pos: [0, 0, 0], verdict: 'unchecked', found: null,
      }),
    });
    expect(evalOne({ mark: '矿洞' }, unchecked).text).toContain('世界里没有一格叫这个,核不了');
    expect(evalOne({ mark: '不存在' }, fakeWorld()))
      .toEqual({ verdict: 'error', text: '路标表里没有「不存在」' });
  });

  it('区块没加载走 unknown 那一档', () => {
    const off = fakeWorld({
      marks: () => ({
        name: '家', kind: '床', dimension: 'minecraft:overworld',
        pos: [9, 9, 9], verdict: 'unloaded', found: null,
      }),
    });
    expect(evalOne({ mark: '家' }, off).verdict).toBe('unknown');
  });

  it('路标在另一个维度时不拿当前维度同坐标方块核验', () => {
    const elsewhere = fakeWorld({
      marks: () => ({
        name: '下界门', kind: '门户', dimension: 'minecraft:the_nether',
        pos: [1, 2, 3], verdict: 'other-dimension', found: null,
      }),
    });
    expect(evalOne({ mark: '下界门' }, elsewhere))
      .toEqual({
        verdict: 'unknown',
        text: '「下界门」在别的维度 [下界] (1, 2, 3),当前维度没法核',
      });
  });
});

describe('mc_check · 受理', () => {
  it('checks 不成形是整单的错', () => {
    expect(parseChecks({})).toEqual({ error: 'checks 要一个断言数组' });
    expect(parseChecks({ checks: [] })).toEqual({ error: 'checks 是空的,没有东西可对' });
    const many = parseChecks({ checks: Array.from({ length: CHECK_MAX_ASSERTS + 1 }, () => ({})) });
    expect((many as { error: string }).error).toContain(`最多 ${CHECK_MAX_ASSERTS} 条`);
  });

  it('单条不成形只坏那一条,其余照对', () => {
    const parsed = parseChecks({
      checks: [{ at: [0, 0, 0], is: 'stone' }, { nonsense: 1 }, { inv: { torch: 1 } }],
    });
    expect(Array.isArray(parsed)).toBe(true);
    const list = parsed as CheckParsed[];
    expect(list[0].ok).toBe(true);
    expect(list[1]).toEqual({ ok: false, error: '认不出这条断言:要 at / box / inv / blueprint / mark 之一' });
    expect(list[2].ok).toBe(true);
  });

  it('认不出的方块名当场退回(registry 接上时)', () => {
    const knows = (id: string) => ['stone', 'chest'].includes(id);
    expect(parseAssert({ at: [0, 0, 0], is: 'stoen' }, knows))
      .toEqual({ ok: false, error: '这一版里没有叫「stoen」的方块' });
    expect(parseAssert({ at: [0, 0, 0], is: 'stone' }, knows).ok).toBe(true);
    // air 不必在 registry 里对上:它是"该空着"的写法
    expect(parseAssert({ at: [0, 0, 0], is: 'air' }, knows).ok).toBe(true);
  });

  it('区域格数超限当场拒算', () => {
    const huge = parseAssert({ box: [[0, 0, 0], [20, 20, 20]], all: 'stone' });
    expect(huge.ok).toBe(false);
    expect((huge as { error: string }).error).toContain(String(CHECK_BOX_CELL_CAP));
  });

  it('给了 box 却没说要对什么', () => {
    expect(parseAssert({ box: [[0, 0, 0], [1, 1, 1]] }))
      .toEqual({ ok: false, error: '给了 box 但没说要对什么:count / all / air / sealed 选一个' });
  });

  it('计数值只收非负整数或 ">=N" / "<=N"', () => {
    const bad = parseAssert({ box: [[0, 0, 0], [1, 1, 1]], count: { stone: 'lots' } });
    expect((bad as { error: string }).error).toContain('">=8"');
    expect(parseAssert({ box: [[0, 0, 0], [1, 1, 1]], count: { stone: '>= 8' } }).ok).toBe(true);
  });

  it('坐标要三个整数', () => {
    expect(parseAssert({ at: [0, 0], is: 'stone' }))
      .toEqual({ ok: false, error: 'at 要 [x, y, z] 三个整数' });
  });
});

describe('mc_check · 整单回执', () => {
  it('先总账,符合的合并带过,不符的逐条点名', () => {
    const world = fakeWorld({
      cells: { '0,0,0': 'chest', '1,0,0': 'stone' },
      inv: { torch: 2 },
      unloaded: ['9,9,9'],
    });
    const parsed = parseChecks({
      checks: [
        { at: [0, 0, 0], is: 'chest' },
        { at: [1, 0, 0], is: 'chest' },
        { at: [9, 9, 9], is: 'chest' },
        { inv: { torch: '>=8' } },
        { nope: true },
      ],
    }) as CheckParsed[];
    const said = renderChecks(parsed, world);
    const [head, ...body] = said.split('\n');
    expect(head).toBe('对账 5 条:1 条符合、2 条不符、1 条没对上(区块没加载)、1 条没受理。');
    expect(body).toEqual([
      '#2 (1, 0, 0) 该是箱子,现在是石头',
      '#3 (9, 9, 9) 区块没加载,走近再对',
      '#4 包里现有:火把 2(要 ≥8)',
      '#5 认不出这条断言:要 at / box / inv / blueprint / mark 之一',
    ]);
  });

  it('全对上就只有一句总账', () => {
    const world = fakeWorld({ cells: { '0,0,0': 'chest' } });
    const parsed = parseChecks({ checks: [{ at: [0, 0, 0], is: 'chest' }] }) as CheckParsed[];
    expect(renderChecks(parsed, world)).toBe('对账 1 条:1 条符合。');
  });
});
