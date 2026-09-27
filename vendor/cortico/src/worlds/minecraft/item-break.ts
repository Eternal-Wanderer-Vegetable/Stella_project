import type { Bot } from 'mineflayer';
import { readDurability, type Durability, type ItemLike } from './item-facts.ts';

type ItemBreakSlot = 'mainhand' | 'offhand' | 'head' | 'chest' | 'legs' | 'feet';

export interface ItemBreakFact {
  kind: 'item-break';
  slot: ItemBreakSlot;
  name: string;
  /** 事件前最近一次装备快照中的剩余耐久。 */
  durability: Durability;
}

interface EntityStatusPacket {
  entityId: number;
  entityStatus: number;
}

type ItemSnapshot = Omit<ItemBreakFact, 'kind'> & {
  /** 槽位先清空时给同一批服务端损坏事件留出的短暂关联窗口。 */
  validUntil?: number;
};

const CLEARED_SNAPSHOT_MS = 1_000;

const STATUS_SLOT = new Map<number, ItemBreakSlot>([
  [47, 'mainhand'],
  [48, 'offhand'],
  [49, 'head'],
  [50, 'chest'],
  [51, 'legs'],
  [52, 'feet'],
]);

const INVENTORY_SLOT = new Map<number, ItemBreakSlot>([
  [45, 'offhand'],
  [5, 'head'],
  [6, 'chest'],
  [7, 'legs'],
  [8, 'feet'],
]);

/** 从本玩家的 entity_status 47–52 读取物品损坏事件；槽位变化只更新关联用的装备快照。 */
export class ItemBreakDecoder {
  private attached = false;
  private readonly snapshots = new Map<ItemBreakSlot, ItemSnapshot>();

  private readonly onHeldItemChanged = (item: ItemLike | null): void => {
    this.remember('mainhand', item);
  };

  private readonly onInventorySlot = (
    index: number,
    _oldItem: ItemLike | null,
    newItem: ItemLike | null,
  ): void => {
    const slot = INVENTORY_SLOT.get(index);
    if (slot) this.remember(slot, newItem);
  };

  private readonly onEntityStatus = (packet: EntityStatusPacket): void => {
    if (packet.entityId !== this.bot.entity.id) return;
    const slot = STATUS_SLOT.get(packet.entityStatus);
    if (!slot) return;
    const snapshot = this.snapshots.get(slot);
    if (!snapshot) return;
    this.snapshots.delete(slot);
    if (snapshot.validUntil !== undefined && Date.now() > snapshot.validUntil) return;
    this.onBreak({
      kind: 'item-break',
      slot: snapshot.slot,
      name: snapshot.name,
      durability: { ...snapshot.durability },
    });
  };

  constructor(
    private readonly bot: Bot,
    private readonly onBreak: (fact: ItemBreakFact) => void,
  ) {}

  get active(): boolean { return this.attached; }

  attach(): void {
    if (this.attached) return;
    this.attached = true;
    this.captureAll();
    this.bot.on('heldItemChanged', this.onHeldItemChanged as never);
    this.bot.inventory.on('updateSlot', this.onInventorySlot as never);
    this.bot._client.on('entity_status', this.onEntityStatus as never);
  }

  detach(): void {
    if (!this.attached) return;
    this.attached = false;
    this.bot.off('heldItemChanged', this.onHeldItemChanged as never);
    this.bot.inventory.off('updateSlot', this.onInventorySlot as never);
    this.bot._client.off('entity_status', this.onEntityStatus as never);
    this.snapshots.clear();
  }

  private captureAll(): void {
    this.snapshots.clear();
    this.remember('mainhand', this.bot.heldItem);
    for (const [index, slot] of INVENTORY_SLOT) {
      this.remember(slot, this.bot.inventory.slots[index] as ItemLike | null | undefined);
    }
  }

  private remember(slot: ItemBreakSlot, item: ItemLike | null | undefined): void {
    if (!item) {
      const previous = this.snapshots.get(slot);
      if (previous && previous.validUntil === undefined) {
        this.snapshots.set(slot, { ...previous, validUntil: Date.now() + CLEARED_SNAPSHOT_MS });
      }
      return;
    }
    const durability = readDurability(item);
    if (!durability) return;
    this.snapshots.set(slot, {
      slot,
      name: item.name,
      durability: { ...durability },
    });
  }
}
