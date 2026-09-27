import { EventEmitter } from 'node:events';
import { describe, expect, it, vi } from 'vitest';
import type { Bot } from 'mineflayer';
import { ItemBreakDecoder, type ItemBreakFact } from '../../../src/worlds/minecraft/item-break.ts';

interface FakeItem {
  name: string;
  count: number;
  componentMap: Map<string, { data: number }>;
}

function item(name: string, damage: number): FakeItem {
  return { name, count: 1, componentMap: new Map([['damage', { data: damage }]]) };
}

function rig() {
  const client = new EventEmitter();
  const inventory = new EventEmitter() as EventEmitter & { slots: Array<FakeItem | null> };
  inventory.slots = Array.from({ length: 46 }, () => null);
  let heldItem: FakeItem | null = null;
  const botEvents = new EventEmitter();
  Object.assign(botEvents, {
    entity: { id: 17 },
    _client: client,
    inventory,
  });
  Object.defineProperty(botEvents, 'heldItem', { get: () => heldItem });
  const bot = botEvents as unknown as Bot;
  const facts: ItemBreakFact[] = [];
  const decoder = new ItemBreakDecoder(bot, (fact) => { facts.push(fact); });

  return {
    bot,
    client,
    inventory,
    facts,
    decoder,
    hold(next: FakeItem | null) {
      heldItem = next;
      botEvents.emit('heldItemChanged', next);
    },
    equip(slot: number, next: FakeItem | null) {
      const old = inventory.slots[slot] ?? null;
      inventory.slots[slot] = next;
      inventory.emit('updateSlot', slot, old, next);
    },
    status(entityStatus: number, entityId = 17) {
      client.emit('entity_status', { entityId, entityStatus });
    },
    setInitial(main: FakeItem | null, entries: Array<[number, FakeItem]>) {
      heldItem = main;
      for (const [slot, entry] of entries) inventory.slots[slot] = entry;
    },
  };
}

describe('ItemBreakDecoder', () => {
  it('47–52 分别解码主手、副手、头、胸、腿、脚，并带事件前耐久快照', () => {
    const r = rig();
    r.setInitial(item('diamond_pickaxe', 61), [
      [45, item('shield', 36)],
      [5, item('diamond_helmet', 13)],
      [6, item('iron_chestplate', 22)],
      [7, item('iron_leggings', 25)],
      [8, item('iron_boots', 30)],
    ]);
    r.decoder.attach();

    for (const status of [47, 48, 49, 50, 51, 52]) r.status(status);

    expect(r.facts).toEqual([
      { kind: 'item-break', slot: 'mainhand', name: 'diamond_pickaxe', durability: { left: 1500, max: 1561 } },
      { kind: 'item-break', slot: 'offhand', name: 'shield', durability: { left: 300, max: 336 } },
      { kind: 'item-break', slot: 'head', name: 'diamond_helmet', durability: { left: 350, max: 363 } },
      { kind: 'item-break', slot: 'chest', name: 'iron_chestplate', durability: { left: 218, max: 240 } },
      { kind: 'item-break', slot: 'legs', name: 'iron_leggings', durability: { left: 200, max: 225 } },
      { kind: 'item-break', slot: 'feet', name: 'iron_boots', durability: { left: 165, max: 195 } },
    ]);
  });

  it('忽略其他实体、未知状态和没有可损坏装备的槽', () => {
    const r = rig();
    r.setInitial(item('iron_sword', 1), []);
    r.decoder.attach();

    r.status(47, 99);
    r.status(46);
    r.status(53);
    r.status(48);

    expect(r.facts).toEqual([]);
  });

  it('换栏、换甲与卸下不自行生成损坏事实', () => {
    const r = rig();
    r.setInitial(item('wooden_pickaxe', 10), [[5, item('iron_helmet', 5)]]);
    r.decoder.attach();

    r.hold(item('diamond_axe', 100));
    r.equip(5, null);
    r.equip(6, item('diamond_chestplate', 20));
    expect(r.facts).toEqual([]);

    r.status(47);
    r.status(50);
    expect(r.facts).toEqual([
      { kind: 'item-break', slot: 'mainhand', name: 'diamond_axe', durability: { left: 1461, max: 1561 } },
      { kind: 'item-break', slot: 'chest', name: 'diamond_chestplate', durability: { left: 508, max: 528 } },
    ]);
  });

  it('槽位先被清空也保留事件前快照，随后的权威 status 仍只报一次', () => {
    const r = rig();
    r.setInitial(item('iron_pickaxe', 249), [[5, item('iron_helmet', 164)]]);
    r.decoder.attach();

    r.hold(null);
    r.equip(5, null);
    expect(r.facts).toEqual([]);

    r.status(47);
    r.status(49);
    r.status(47);
    r.status(49);
    expect(r.facts).toEqual([
      { kind: 'item-break', slot: 'mainhand', name: 'iron_pickaxe', durability: { left: 1, max: 250 } },
      { kind: 'item-break', slot: 'head', name: 'iron_helmet', durability: { left: 1, max: 165 } },
    ]);
  });

  it('普通卸下留下的旧快照超过关联窗口后不再冒充损坏事件', () => {
    const clock = vi.spyOn(Date, 'now').mockReturnValue(1_000);
    try {
      const r = rig();
      r.setInitial(item('iron_pickaxe', 10), []);
      r.decoder.attach();
      r.hold(null);

      clock.mockReturnValue(2_001);
      r.status(47);
      expect(r.facts).toEqual([]);
    } finally {
      clock.mockRestore();
    }
  });

  it('同一快照只消费一次；快照复制耐久值，不受原物品随后原地修改影响', () => {
    const r = rig();
    const pickaxe = item('diamond_pickaxe', 61);
    r.setInitial(pickaxe, []);
    r.decoder.attach();
    pickaxe.componentMap.get('damage')!.data = 100;

    r.status(47);
    r.status(47);
    expect(r.facts).toEqual([
      { kind: 'item-break', slot: 'mainhand', name: 'diamond_pickaxe', durability: { left: 1500, max: 1561 } },
    ]);

    r.hold(item('iron_pickaxe', 9));
    r.status(47);
    expect(r.facts.at(-1)).toEqual({
      kind: 'item-break', slot: 'mainhand', name: 'iron_pickaxe', durability: { left: 241, max: 250 },
    });
  });

  it('attach 幂等且 detach 移除全部监听；重新挂载从当前装备重建快照', () => {
    const r = rig();
    r.setInitial(item('stone_sword', 20), []);
    r.decoder.attach();
    r.decoder.attach();
    expect(r.client.listenerCount('entity_status')).toBe(1);
    expect(r.inventory.listenerCount('updateSlot')).toBe(1);
    expect((r.bot as unknown as EventEmitter).listenerCount('heldItemChanged')).toBe(1);

    r.decoder.detach();
    expect(r.decoder.active).toBe(false);
    expect(r.client.listenerCount('entity_status')).toBe(0);
    expect(r.inventory.listenerCount('updateSlot')).toBe(0);
    expect((r.bot as unknown as EventEmitter).listenerCount('heldItemChanged')).toBe(0);
    r.status(47);
    expect(r.facts).toEqual([]);

    r.decoder.attach();
    r.status(47);
    expect(r.facts).toHaveLength(1);
  });
});
