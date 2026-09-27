/**
 * 拴绳(lead)与 toss 的定点扔,外加三条维度/栅栏的受理刻判据。
 *
 * 拴绳的服务端信号是 `attach_entity` —— 上游把它记进 `entity.vehicle`(1.9 起这个包
 * 只用于拴绳)。假 bot 就照这条来:`leash(e)` 把它的 vehicle 指向我,`snap(e)` 断开。
 * 一根绳同时也从背包里少掉,两条证据分开断言,免得只靠一条时看不出是哪边坏了。
 */
import { Vec3 as V } from 'vec3';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { precheckStep } from '../../../src/worlds/minecraft/precheck.ts';
import type { SkillCall } from '../../../src/worlds/minecraft/executor.ts';
import { makeExecutorOn, waitUntil } from './executor-harness.ts';

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
});

afterEach(() => {
  vi.useRealTimers();
});

type Bag = Array<{ name: string; count: number }>;
type Mob = {
  id: number;
  name: string;
  isValid: boolean;
  height: number;
  position: V;
  vehicle?: { id?: number } | null;
};

function key(x: number, y: number, z: number): string {
  return `${Math.floor(x)},${Math.floor(y)},${Math.floor(z)}`;
}

interface LeadBotOptions {
  bag?: Bag;
  mobs?: Mob[];
  cells?: Record<string, string>;
  dimension?: string;
  /** 服务端认不认这一次右键:默认认(拴上并扣一根绳) */
  acceptAttach?: boolean;
  /** goto 之后人落在哪儿;不给就直接落到目标圈心 */
  onGoto?: (bot: LeadBot) => void;
}

type LeadBot = ReturnType<typeof leadBot>;

function leadBot(opts: LeadBotOptions = {}) {
  const bag: Bag = opts.bag ?? [{ name: 'lead', count: 2 }];
  const cells = new Map(Object.entries(opts.cells ?? {}));
  const mobs = opts.mobs ?? [];
  const entities: Record<string, unknown> = {};
  for (const m of mobs) entities[String(m.id)] = m;
  let heldItem: { name: string } | null = null;
  const usedOn: string[] = [];
  const activated: string[] = [];
  const gotos: Array<{ x: number; y: number; z: number; range: number }> = [];

  const bot = {
    entity: { id: 1, position: new V(0, 64, 0), height: 1.8, isValid: true },
    entities,
    mobs,
    usedOn,
    activated,
    gotos,
    heldName: () => heldItem?.name ?? null,
    bagOf: (name: string) => bag.filter((b) => b.name === name).reduce((a, b) => a + b.count, 0),
    game: { dimension: opts.dimension ?? 'overworld' },
    health: 20,
    players: {},
    registry: {
      // 注册表是游戏的,与这一刻世界里有没有那只无关:名字认得,附近没有才是 noop
      entitiesByName: { cow: {}, sheep: {}, pig: {}, villager: {} } as Record<string, unknown>,
      blocksByName: {} as Record<string, unknown>,
    },
    inventory: { items: () => bag },
    currentWindow: null,
    closeWindow: () => {},
    chat: () => {},
    equip: async (item: { name: string }) => { heldItem = item; },
    unequip: async () => { heldItem = null; },
    look: async () => {},
    lookAt: async () => {},
    waitForTicks: async () => {},
    setControlState: () => {},
    activateItem: async () => {},
    deactivateItem: () => {},
    toss: async (_type: unknown, _meta: unknown, n: number) => {
      const slot = bag.find((b) => b.count > 0);
      if (slot) slot.count -= n;
    },
    /** 服务端把绳拴上了:它的 vehicle 指向我,背包里少一根 */
    leash(m: Mob) {
      m.vehicle = { id: bot.entity.id };
      const slot = bag.find((b) => b.name === 'lead');
      if (slot) slot.count -= 1;
    },
    /** 绳断/松开:vehicle 清掉。绳掉在地上,这里不模拟掉落物 */
    snap(m: Mob) { m.vehicle = null; },
    useOn: async (e: Mob) => {
      usedOn.push(e.name);
      if (opts.acceptAttach === false) return;
      if (e.vehicle && e.vehicle.id === bot.entity.id) bot.snap(e); // 空手右键 = 松开
      else if (heldItem?.name === 'lead') bot.leash(e);
    },
    activateBlock: async (b: { name: string; position: V }) => {
      activated.push(`${b.name}@${key(b.position.x, b.position.y, b.position.z)}`);
      for (const m of mobs) if (m.vehicle?.id === bot.entity.id) bot.snap(m);
    },
    blockAt: (p: V) => {
      const name = cells.get(key(p.x, p.y, p.z)) ?? 'air';
      return {
        name,
        position: new V(Math.floor(p.x), Math.floor(p.y), Math.floor(p.z)),
        boundingBox: name === 'air' ? 'empty' : 'block',
        stateId: [...name].reduce((a, c) => a + c.charCodeAt(0), 0),
      };
    },
    pathfinder: {
      stop() {},
      setGoal() {},
      // 上游的 GoalNear/GoalFollow 存的是 rangeSq,不是 range
      goto: async (goal: Record<string, number>) => {
        gotos.push({ x: goal.x, y: goal.y, z: goal.z, range: Math.sqrt(goal.rangeSq ?? 0) });
        if (opts.onGoto) { opts.onGoto(bot); return; }
        bot.entity.position = new V(goal.x ?? 0, goal.y ?? 64, goal.z ?? 0);
      },
    },
  };
  return bot;
}

async function run(bot: unknown, step: SkillCall) {
  const { exec, reports } = makeExecutorOn(bot);
  exec.submit([step as never]);
  await waitUntil(() => reports.length === 1, 20_000);
  return reports[0];
}

function cow(id: number, at: [number, number, number]): Mob {
  return { id, name: 'cow', isValid: true, height: 1.4, position: new V(...at), vehicle: null };
}

describe('lead:拴上', () => {
  it('拴上之后回执报它在哪、绳还剩几根;背包真少一根,它的 vehicle 指向我', async () => {
    const c = cow(7, [2, 64, 0]);
    const bot = leadBot({ mobs: [c] });
    const r = await run(bot, { skill: 'lead', target: 'cow' } as SkillCall);
    expect(r.kind).toBe('done');
    expect(r.text).toContain('拴上牛了');
    expect(r.text).toContain('拴绳还剩 1 根');
    expect(bot.bagOf('lead')).toBe(1);
    expect(c.vehicle?.id).toBe(bot.entity.id);
  });

  it('绳一根没少也没收到确认 = 没拴上,受阻文案点名拴不住的那几类', async () => {
    const bot = leadBot({ mobs: [cow(7, [2, 64, 0])], acceptAttach: false });
    const r = await run(bot, { skill: 'lead', target: 'cow' } as SkillCall);
    expect(r.kind).toBe('blocked');
    expect(r.text).toContain('绳一根没少');
    expect(r.text).toContain('村民');
    expect(bot.bagOf('lead')).toBe(2);
  });

  it('已经被别人牵着的拴不上第二根,右键都不发', async () => {
    const c = cow(7, [2, 64, 0]);
    c.vehicle = { id: 99 };
    const bot = leadBot({ mobs: [c] });
    const r = await run(bot, { skill: 'lead', target: 'cow' } as SkillCall);
    expect(r.kind).toBe('blocked');
    expect(r.text).toContain('已经拴着别人的绳');
    expect(bot.usedOn).toEqual([]);
  });

  it('包里没绳当场驳回,受阻回执给出配方', async () => {
    const bot = leadBot({ bag: [], mobs: [cow(7, [2, 64, 0])] });
    const r = await run(bot, { skill: 'lead', target: 'cow' } as SkillCall);
    expect(r.kind).toBe('blocked');
    expect(r.text).toContain('拴绳');
    expect(bot.usedOn).toEqual([]);
  });

  it('附近没有那种活物是 noop,不是受阻', async () => {
    const bot = leadBot({ mobs: [] });
    const r = await run(bot, { skill: 'lead', target: 'cow' } as SkillCall);
    expect(r.text).toContain('32 格内没有牛');
  });
});

describe('lead:牵着走', () => {
  /** 牵着走时它跟着我:每次 goto 之后把它摆到我身后一格 */
  function follower(): { bot: LeadBot; c: Mob } {
    const c = cow(7, [2, 64, 0]);
    const bot = leadBot({
      mobs: [c],
      onGoto: (b) => {
        // 假寻路器:一次 goto 走到目标圈上(圈心+range),它跟到我身后 1 格
        const g = b.gotos[b.gotos.length - 1];
        const dx = g.x - b.entity.position.x;
        const dz = g.z - b.entity.position.z;
        const d = Math.hypot(dx, dz) || 1;
        const step = Math.max(0, d - g.range);
        b.entity.position = new V(
          b.entity.position.x + (dx / d) * step, g.y, b.entity.position.z + (dz / d) * step,
        );
        c.position = new V(b.entity.position.x - 1, b.entity.position.y, b.entity.position.z);
      },
    });
    return { bot, c };
  }

  it('分段牵到目标圈内:它进 tolerance 就算到,走了几段照实说,到了自动松开', async () => {
    const { bot, c } = follower();
    const r = await run(bot, { skill: 'lead', target: 'cow', to: [30, 64, 0], tolerance: 3 } as SkillCall);
    expect(r.kind).toBe('done');
    expect(r.text).toContain('牵到 (30, 64, 0) 了');
    expect(r.text).toContain('松开牛了');
    // 30 格分段走,不是一口气丢给寻路器
    expect(bot.gotos.length).toBeGreaterThan(1);
    expect(c.vehicle == null).toBe(true);
  });

  it('keep:true 到了继续牵着,不松开', async () => {
    const { bot, c } = follower();
    const r = await run(
      bot,
      { skill: 'lead', target: 'cow', to: [20, 64, 0], tolerance: 3, keep: true } as SkillCall,
    );
    expect(r.kind).toBe('done');
    expect(r.text).not.toContain('松开');
    expect(c.vehicle?.id).toBe(bot.entity.id);
  });

  it('半路绳脱开:当场停下,两边的位置都报出来,并说绳掉在哪要捡', async () => {
    const c = cow(7, [2, 64, 0]);
    let hops = 0;
    const bot = leadBot({
      mobs: [c],
      onGoto: (b) => {
        const g = b.gotos[b.gotos.length - 1];
        b.entity.position = new V(g.x, g.y, g.z);
        hops += 1;
        if (hops >= 2) b.snap(c); // 第二段之后绳断
        else c.position = new V(b.entity.position.x - 1, 64, b.entity.position.z);
      },
    });
    const r = await run(bot, { skill: 'lead', target: 'cow', to: [60, 64, 0], tolerance: 2 } as SkillCall);
    expect(r.kind).toBe('blocked');
    expect(r.text).toContain('绳脱开了');
    expect(r.text).toContain('pickup');
  });
});

describe('lead:系栅栏与松开', () => {
  it('tie 指的不是栅栏就当场驳回,点名栅栏门也不行', async () => {
    const c = cow(7, [2, 64, 0]);
    const bot = leadBot({ mobs: [c], cells: { '5,64,0': 'oak_fence_gate' } });
    const r = await run(bot, { skill: 'lead', target: 'cow', tie: [5, 64, 0] } as SkillCall);
    expect(r.kind).toBe('blocked');
    expect(r.text).toContain('系不上去');
    expect(r.text).toContain('栅栏门');
  });

  it('系到栅栏上:右键的是那一格,绳头不再在我手里', async () => {
    const c = cow(7, [2, 64, 0]);
    const bot = leadBot({ mobs: [c], cells: { '5,64,0': 'jungle_fence' } });
    const r = await run(bot, { skill: 'lead', target: 'cow', tie: [5, 64, 0] } as SkillCall);
    expect(r.kind).toBe('done');
    expect(r.text).toContain('系到 (5, 64, 0)');
    expect(bot.activated).toContain('jungle_fence@5,64,0');
    expect(c.vehicle == null).toBe(true);
  });

  it('off:没牵着任何东西是 noop', async () => {
    const bot = leadBot({ mobs: [cow(7, [2, 64, 0])] });
    const r = await run(bot, { skill: 'lead', off: true } as SkillCall);
    expect(r.text).toContain('没牵着');
  });
});

describe('toss:朝一格扔', () => {
  it('给了 at 就朝那一格扔,回执报朝哪儿、隔多远,并且不承诺落点', async () => {
    const bot = leadBot({ bag: [{ name: 'gold_ingot', count: 4 }] });
    const r = await run(bot, { skill: 'toss', item: 'gold_ingot', count: 2, at: [3, 64, 0] } as SkillCall);
    expect(r.kind).toBe('done');
    expect(r.text).toContain('朝 (3, 64, 0) 扔的');
    expect(r.text).toContain('不保证正好落在那一格');
    expect(bot.bagOf('gold_ingot')).toBe(2);
  });

  it('超出手扔距离当场驳回,报实测距离并让她先走近', async () => {
    const bot = leadBot({ bag: [{ name: 'gold_ingot', count: 4 }] });
    const r = await run(bot, { skill: 'toss', item: 'gold_ingot', count: 1, at: [40, 64, 0] } as SkillCall);
    expect(r.kind).toBe('blocked');
    expect(r.text).toContain('够不着');
    expect(r.text).toContain('先走近');
    expect(bot.bagOf('gold_ingot')).toBe(4);
  });

  it('不给 at 还是老样子:自己挑方向,不报「朝某一格」', async () => {
    const bot = leadBot({ bag: [{ name: 'cobblestone', count: 4 }] });
    const r = await run(bot, { skill: 'toss', item: 'cobblestone', count: 1 } as SkillCall);
    expect(r.kind).toBe('done');
    expect(r.text).not.toContain('朝 (');
  });
});

describe('受理刻:维度与栅栏', () => {
  const deps = (bot: LeadBot) => ({
    resolve: (a: unknown) => {
      const t = a as [number, number, number];
      return Array.isArray(t) ? { x: t[0], y: t[1], z: t[2] } : null;
    },
    cellsOf: () => null,
    blockAt: (c: { x: number; y: number; z: number }) => bot.blockAt(new V(c.x, c.y, c.z)),
  });

  it('surface 在下界是 hard:同一条判据提到受理刻说,不等她跑到这一步', () => {
    const bot = leadBot({ dimension: 'the_nether' });
    const note = precheckStep(bot as never, { skill: 'surface' } as SkillCall, deps(bot) as never);
    expect(note?.level).toBe('hard');
    expect(note?.rule).toBe('surface.nether');
    expect(note?.text).toContain('基岩');
  });

  it('surface 在主世界不出判据', () => {
    const bot = leadBot({});
    expect(precheckStep(bot as never, { skill: 'surface' } as SkillCall, deps(bot) as never)).toBeNull();
  });

  it('下界点床是 soft 不是 hard:执行器有意不拦(打龙要用),只把「会爆炸」提前说', () => {
    const bot = leadBot({ dimension: 'the_nether', cells: { '3,64,0': 'white_bed' } });
    const note = precheckStep(bot as never, { skill: 'use', at: [3, 64, 0] } as SkillCall, deps(bot) as never);
    expect(note?.level).toBe('soft');
    expect(note?.rule).toBe('use.bedExplodes');
    expect(note?.text).toContain('爆炸');
  });

  it('主世界点床一个字都不加', () => {
    const bot = leadBot({ cells: { '3,64,0': 'white_bed' } });
    expect(
      precheckStep(bot as never, { skill: 'use', at: [3, 64, 0] } as SkillCall, deps(bot) as never),
    ).toBeNull();
  });

  it('lead 的 tie 不是栅栏 = hard;没绳 = hard', () => {
    const bot = leadBot({ cells: { '5,64,0': 'cobblestone' } });
    const fence = precheckStep(
      bot as never, { skill: 'lead', tie: [5, 64, 0] } as SkillCall, deps(bot) as never,
    );
    expect(fence?.level).toBe('hard');
    expect(fence?.rule).toBe('lead.notFence');

    const empty = leadBot({ bag: [], cells: {} });
    const stock = precheckStep(
      empty as never, { skill: 'lead', target: 'cow' } as SkillCall, deps(empty) as never,
    );
    expect(stock?.level).toBe('hard');
    expect(stock?.rule).toBe('lead.noStock');
  });
});
