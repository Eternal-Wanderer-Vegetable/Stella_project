import { describe, expect, it } from 'vitest';
import {
  BodyLeaseArbiter,
  bodyUtilityScore,
  type BodyLeaseEvent,
  type BodyOwner,
  type BodyProposalInput,
  type BodyUtilityFactors,
} from '../../../src/worlds/minecraft/body-lease.ts';

const utility = (overrides: Partial<BodyUtilityFactors> = {}): BodyUtilityFactors => ({
  survival: 50,
  urgency: 50,
  feasibility: 50,
  progress: 50,
  continuity: 50,
  executionRisk: 0,
  disruption: 0,
  ...overrides,
});

const proposal = (
  owner: BodyOwner,
  ownerKind: BodyProposalInput['ownerKind'],
  score: Partial<BodyUtilityFactors> = {},
  validUntil = 10_000,
): BodyProposalInput => ({ owner, ownerKind, intent: `${ownerKind}-intent`, validUntil, utility: utility(score) });

function rig() {
  const events: BodyLeaseEvent[] = [];
  const arbiter = new BodyLeaseArbiter({
    connectionGeneration: 7,
    emit: (event) => events.push(event),
  });
  return { arbiter, events };
}

describe('BodyLeaseArbiter', () => {
  it('同 owner 连续 reconcile 续租，撤回意图当场释放', () => {
    const { arbiter, events } = rig();
    const owner = {};
    arbiter.update(proposal(owner, 'task'), 0);
    expect(arbiter.reconcile(0).reason).toBe('acquire');
    arbiter.update(proposal(owner, 'task', { progress: 70 }), 1_000);
    expect(arbiter.reconcile(1_000).reason).toBe('renew');
    arbiter.withdraw(owner, 'done', 1_100);
    expect(arbiter.reconcile(1_100).activeAfter).toBeNull();
    expect(events.filter((event) => event.event === 'lease-renewed')).toHaveLength(1);
    expect(events.filter((event) => event.event === 'lease-released')).toHaveLength(1);
  });

  it('迟滞可保留 incumbent，decision 同时给 recommended 与 activeAfter', () => {
    const { arbiter } = rig();
    const incumbent = {};
    const challenger = {};
    arbiter.update(proposal(incumbent, 'task'), 0);
    arbiter.reconcile(0);
    arbiter.update(proposal(challenger, 'combat', { survival: 55 }), 10);
    const decision = arbiter.reconcile(10);
    expect(decision.reason).toBe('hysteresis');
    expect(decision.recommended?.ownerId).not.toBe(decision.activeAfter?.ownerId);
  });

  it('超过统一 margin 时先撤旧租约再签发新的', () => {
    const { arbiter, events } = rig();
    const task = {};
    const lava = {};
    arbiter.update(proposal(task, 'task'), 0);
    arbiter.reconcile(0);
    arbiter.update(proposal(lava, 'lava', { survival: 100, urgency: 100 }), 5);
    const next = arbiter.reconcile(5);
    expect(next.reason).toBe('preempt');
    expect(next.activeAfter?.ownerKind).toBe('lava');
    expect(events.some((event) => event.event === 'lease-preempted')).toBe(true);
  });

  it('租约到期无需额外 reconcile 就不再认 owner，且只产生一次 expiry', () => {
    const { arbiter, events } = rig();
    const owner = {};
    arbiter.update(proposal(owner, 'task', {}, 20_000), 0);
    arbiter.reconcile(0);
    const expiresAt = events.flatMap((event) => (event.event === 'lease-acquired' ? [event.token.expiresAt] : []))[0];
    arbiter.observeLegacyCommit(owner, 'control.jump', () => undefined, expiresAt);
    arbiter.observeLegacyCommit(owner, 'control.jump', () => undefined, expiresAt + 1);
    expect(events.filter((event) => event.event === 'lease-expired')).toHaveLength(1);
    expect(events.filter((event) => event.event === 'command-rejected'
      && event.reason === 'no-active-lease')).toHaveLength(2);
  });

  // 作废是"到恢复为止",不是"到断线为止":death 的恢复口是 revive(见下一条)
  it.each(['death', 'disconnect', 'stop'] as const)('%s invalidate 后、恢复之前不收意图也不签租约', (reason) => {
    const { arbiter, events } = rig();
    const owner = {};
    const input = proposal(owner, 'combat');
    arbiter.update(input, 0);
    arbiter.reconcile(0);
    arbiter.invalidate(reason, 1);
    arbiter.update(input, 3);
    expect(arbiter.reconcile(3).activeAfter).toBeNull();
    expect(events.some((event) => event.event === 'proposal-rejected'
      && event.reason === 'invalidated')).toBe(true);
  });

  it('死亡作废之后重生恢复:重新签发、代次不变、恢复可观测', () => {
    const { arbiter, events } = rig();
    const owner = {};
    arbiter.update(proposal(owner, 'task'), 0);
    arbiter.reconcile(0);
    arbiter.invalidate('death', 1);
    expect(arbiter.reconcile(2).activeAfter).toBeNull();

    arbiter.revive(3);
    expect(events.filter((event) => event.event === 'revived')).toHaveLength(1);
    expect(arbiter.connectionGeneration).toBe(7); // 重生不是新连接:代次不许动

    const reborn = {};
    arbiter.update(proposal(reborn, 'task'), 4);
    expect(arbiter.reconcile(4).activeAfter).not.toBeNull();
    expect(events.some((event) => event.event === 'lease-acquired'
      && event.at === 4 && event.token.connectionGeneration === 7)).toBe(true);
    expect(events.filter((event) => event.event === 'proposal-rejected'
      && event.at > 3)).toEqual([]);
  });

  it('没在作废态时 revive 是 no-op:不发观测事件、不动现有租约', () => {
    const { arbiter, events } = rig();
    const owner = {};
    arbiter.update(proposal(owner, 'task'), 0);
    arbiter.reconcile(0);
    arbiter.revive(1);
    expect(events.some((event) => event.event === 'revived')).toBe(false);
    arbiter.observeLegacyCommit(owner, 'control.jump', () => undefined, 1);
    expect(events.some((event) => event.event === 'command-accepted')).toBe(true);
  });

  it('连接代次切换后新租约挂新代次，旧代次的租约先作废', () => {
    const { arbiter, events } = rig();
    const oldOwner = {};
    arbiter.update(proposal(oldOwner, 'task'), 0);
    arbiter.reconcile(0);
    arbiter.bindGeneration(8, 1);
    const nextOwner = {};
    arbiter.update(proposal(nextOwner, 'task'), 2);
    arbiter.reconcile(2);
    const acquired = events.flatMap((event) => (event.event === 'lease-acquired' ? [event.token] : []));
    expect(acquired.map((token) => token.connectionGeneration)).toEqual([7, 8]);
    expect(events.some((event) => event.event === 'invalidated' && event.reason === 'generation')).toBe(true);
  });

  it('旧连接的迟到 proposal 不能写进新代次', () => {
    const { arbiter, events } = rig();
    arbiter.bindGeneration(8, 1);
    const owner = {};
    arbiter.update(proposal(owner, 'combat'), 2, 7);
    expect(arbiter.reconcile(2).activeAfter).toBeNull();
    expect(events.some((event) => event.event === 'proposal-rejected'
      && event.reason === 'wrong-generation')).toBe(true);
  });

  it('有完整选择但旧路径照跑,并记录 would-accept', () => {
    const { arbiter, events } = rig();
    const owner = {};
    arbiter.update(proposal(owner, 'lava'), 0);
    const decision = arbiter.reconcile(0);
    expect(decision.recommended).not.toBeNull();
    expect(decision.activeAfter).not.toBeNull();
    let wrote = false;
    arbiter.observeLegacyCommit(owner, 'control.jump', () => { wrote = true; }, 1);
    expect(wrote).toBe(true);
    expect(events.some((event) => event.event === 'command-accepted')).toBe(true);
  });

  it('旧路径由别的 owner 提交时记成 wrong-owner,但照样放行', () => {
    const { arbiter, events } = rig();
    const holder = {};
    const other = {};
    arbiter.update(proposal(holder, 'lava', { survival: 100 }), 0);
    arbiter.reconcile(0);
    let wrote = false;
    arbiter.observeLegacyCommit(other, 'path.setGoal', () => { wrote = true; }, 1);
    expect(wrote).toBe(true);
    expect(events.some((event) => event.event === 'command-rejected'
      && event.reason === 'wrong-owner')).toBe(true);
  });

  it('评分只读取通用效用分量，不读取 ownerKind 或 intent', () => {
    const same = utility({ survival: 82, urgency: 63, executionRisk: 12 });
    expect(bodyUtilityScore(same)).toBe(bodyUtilityScore({ ...same }));
    const { arbiter } = rig();
    const a = {};
    const b = {};
    arbiter.update({ ...proposal(a, 'task'), utility: same, intent: 'build' }, 0);
    arbiter.update({ ...proposal(b, 'lava'), utility: same, intent: 'escape-fire' }, 0);
    const decision = arbiter.reconcile(0);
    expect(decision.candidates[0].score).toBe(decision.candidates[1].score);
    expect(decision.activeAfter?.ownerId).toBe(decision.candidates[0].ownerId);
  });
});
