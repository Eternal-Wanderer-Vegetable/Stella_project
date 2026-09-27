export type BodyOwnerKind =
  | 'task'
  | 'combat'
  | 'lava'
  | 'drown'
  | 'suffocation'
  | 'hurt';

/** 身体 owner 是一次动作实例；同类的新实例不能继承旧实例的授权。 */
export type BodyOwner = object;

export interface BodyUtilityFactors {
  survival: number;
  urgency: number;
  feasibility: number;
  progress: number;
  continuity: number;
  executionRisk: number;
  disruption: number;
}

export interface BodyProposalInput {
  owner: BodyOwner;
  ownerKind: BodyOwnerKind;
  intent: string;
  validUntil: number;
  utility: BodyUtilityFactors;
}

interface BodyProposal extends BodyProposalInput {
  proposalId: number;
  ownerId: number;
  updatedAt: number;
}

interface BodyLeaseToken {
  readonly leaseId: number;
  readonly connectionGeneration: number;
  readonly owner: BodyOwner;
  readonly ownerId: number;
  readonly ownerKind: BodyOwnerKind;
  readonly acquiredAt: number;
  readonly expiresAt: number;
}

interface BodyCandidateScore {
  proposalId: number;
  ownerId: number;
  ownerKind: BodyOwnerKind;
  score: number;
}

interface BodyDecision {
  at: number;
  connectionGeneration: number;
  candidates: BodyCandidateScore[];
  recommended: BodyCandidateScore | null;
  incumbentBefore: BodyCandidateScore | null;
  activeAfter: BodyCandidateScore | null;
  reason: 'empty' | 'acquire' | 'renew' | 'same-owner' | 'preempt' | 'hysteresis';
}

export type BodyLeaseEvent =
  | { event: 'proposal-updated'; at: number; generation: number; proposal: BodyProposal }
  | { event: 'proposal-rejected'; at: number; generation: number; proposal: BodyProposal; reason: 'invalidated' | 'wrong-generation' }
  | { event: 'proposal-withdrawn'; at: number; generation: number; proposalId: number; ownerId: number; reason: string }
  | { event: 'decision'; at: number; generation: number; decision: BodyDecision }
  | { event: 'lease-acquired' | 'lease-renewed'; at: number; generation: number; token: BodyLeaseToken }
  | { event: 'lease-preempted' | 'lease-released' | 'lease-expired'; at: number; generation: number; token: BodyLeaseToken; reason: string }
  | {
      event: 'command-accepted' | 'command-rejected';
      at: number;
      generation: number;
      command: string;
      leaseId: number | null;
      ownerId: number | null;
      reason: 'accepted' | 'no-active-lease' | 'wrong-owner';
    }
  | {
      event: 'invalidated';
      at: number;
      generation: number;
      reason: 'death' | 'disconnect' | 'stop' | 'generation';
      leaseId: number | null;
      proposalIds: number[];
    }
  | { event: 'revived'; at: number; generation: number; reason: 'respawn' };

interface BodyLeaseOptions {
  connectionGeneration: number;
  emit?: (event: BodyLeaseEvent) => void;
  leaseMs?: number;
  preemptMargin?: number;
}

const BODY_LEASE_MS = 2_500;
const BODY_PREEMPT_MARGIN = 4;

const UTILITY_WEIGHTS: Readonly<Record<keyof BodyUtilityFactors, number>> = {
  survival: 0.34,
  urgency: 0.22,
  feasibility: 0.20,
  progress: 0.08,
  continuity: 0.08,
  executionRisk: -0.14,
  disruption: -0.08,
};

export function bodyUtilityScore(utility: BodyUtilityFactors): number {
  return (Object.keys(UTILITY_WEIGHTS) as Array<keyof BodyUtilityFactors>)
    .reduce((sum, key) => sum + utility[key] * UTILITY_WEIGHTS[key], 0);
}

interface ActiveLease {
  token: BodyLeaseToken;
  proposalId: number;
  score: number;
}

/** 比较控制器提交的效用并记录建议的身体控制者；当前仅记录，不拦截执行。 */
export class BodyLeaseArbiter {
  private generation: number;
  private readonly emit: (event: BodyLeaseEvent) => void;
  private readonly leaseMs: number;
  private readonly preemptMargin: number;
  private proposalSeq = 0;
  private leaseSeq = 0;
  private ownerSeq = 0;
  private readonly ownerIds = new WeakMap<BodyOwner, number>();
  private readonly proposals = new Map<BodyOwner, BodyProposal>();
  private active: ActiveLease | null = null;
  private invalidated = false;

  constructor(options: BodyLeaseOptions) {
    this.generation = options.connectionGeneration;
    this.emit = options.emit ?? (() => undefined);
    this.leaseMs = options.leaseMs ?? BODY_LEASE_MS;
    this.preemptMargin = options.preemptMargin ?? BODY_PREEMPT_MARGIN;
  }

  get connectionGeneration(): number { return this.generation; }

  update(input: BodyProposalInput, now: number, connectionGeneration = this.generation): BodyProposal {
    const proposal: BodyProposal = {
      ...input,
      proposalId: ++this.proposalSeq,
      ownerId: this.ownerId(input.owner),
      updatedAt: now,
    };
    if (this.invalidated || connectionGeneration !== this.generation) {
      this.emit({
        event: 'proposal-rejected', at: now, generation: this.generation, proposal,
        reason: this.invalidated ? 'invalidated' : 'wrong-generation',
      });
      return proposal;
    }
    this.proposals.set(input.owner, proposal);
    this.emit({ event: 'proposal-updated', at: now, generation: this.generation, proposal });
    return proposal;
  }

  withdraw(owner: BodyOwner, reason: string, now: number): void {
    const proposal = this.proposals.get(owner);
    if (!proposal) return;
    this.proposals.delete(owner);
    this.emit({
      event: 'proposal-withdrawn', at: now, generation: this.generation,
      proposalId: proposal.proposalId, ownerId: proposal.ownerId, reason,
    });
    if (this.active?.token.owner === owner) this.releaseActive(`withdraw:${reason}`, now);
  }

  reconcile(now: number): BodyDecision {
    this.expire(now);
    const ranked = [...this.proposals.values()]
      .filter((proposal) => proposal.validUntil > now)
      .map((proposal) => ({ proposal, score: bodyUtilityScore(proposal.utility) }))
      .sort((a, b) => b.score - a.score || a.proposal.ownerId - b.proposal.ownerId);
    const scores = ranked.map(({ proposal, score }) => this.scoreOf(proposal, score));
    const recommended = ranked[0] ?? null;
    const incumbentBefore = this.active ? this.activeScore() : null;
    let reason: BodyDecision['reason'] = 'empty';

    if (!recommended) {
      if (this.active) this.releaseActive('no-valid-proposal', now);
    } else {
      const incumbentProposal = this.active ? this.proposals.get(this.active.token.owner) : null;
      if (!this.active || !incumbentProposal || incumbentProposal.validUntil <= now) {
        if (this.active) this.releaseActive('proposal-withdrawn-or-expired', now);
        this.acquire(recommended.proposal, recommended.score, now);
        reason = 'acquire';
      } else if (recommended.proposal.owner === this.active.token.owner) {
        const changed = this.renewActive(recommended.proposal, recommended.score, now);
        reason = changed ? 'renew' : 'same-owner';
      } else if (recommended.score > bodyUtilityScore(incumbentProposal.utility) + this.preemptMargin) {
        const incumbentScore = bodyUtilityScore(incumbentProposal.utility);
        const old = this.active.token;
        this.active = null;
        this.emit({
          event: 'lease-preempted', at: now, generation: this.generation,
          token: old, reason: `challenger-margin:${recommended.score - incumbentScore}`,
        });
        this.acquire(recommended.proposal, recommended.score, now);
        reason = 'preempt';
      } else {
        this.renewActive(incumbentProposal, bodyUtilityScore(incumbentProposal.utility), now);
        reason = 'hysteresis';
      }
    }

    const decision: BodyDecision = {
      at: now,
      connectionGeneration: this.generation,
      candidates: scores,
      recommended: recommended ? this.scoreOf(recommended.proposal, recommended.score) : null,
      incumbentBefore,
      activeAfter: this.active ? this.activeScore() : null,
      reason,
    };
    this.emit({ event: 'decision', at: now, generation: this.generation, decision });
    return decision;
  }

  /** 记录旧路径是否会获准，但不改变旧路径的执行。 */
  observeLegacyCommit<T>(owner: BodyOwner, command: string, fn: () => T, now: number): T {
    this.expire(now);
    const wouldAccept = this.active?.token.owner === owner && now < this.active.token.expiresAt;
    this.emit({
      event: wouldAccept ? 'command-accepted' : 'command-rejected',
      at: now,
      generation: this.generation,
      command,
      leaseId: this.active?.token.leaseId ?? null,
      ownerId: this.ownerIds.get(owner) ?? null,
      reason: wouldAccept ? 'accepted' : this.active ? 'wrong-owner' : 'no-active-lease',
    });
    return fn();
  }

  invalidate(
    reason: 'death' | 'disconnect' | 'stop' | 'generation',
    now: number,
  ): void {
    const leaseId = this.active?.token.leaseId ?? null;
    const proposalIds = [...this.proposals.values()].map((proposal) => proposal.proposalId);
    this.emit({ event: 'invalidated', at: now, generation: this.generation, reason, leaseId, proposalIds });
    this.active = null;
    this.proposals.clear();
    this.invalidated = true;
  }

  /** 重生解除作废状态并创建新的身体租约，保留当前连接代次。未作废时不产生事件。 */
  revive(now: number): void {
    if (!this.invalidated) return;
    this.invalidated = false;
    this.emit({ event: 'revived', at: now, generation: this.generation, reason: 'respawn' });
  }

  bindGeneration(connectionGeneration: number, now: number): void {
    if (connectionGeneration === this.generation) return;
    this.invalidate('generation', now);
    this.generation = connectionGeneration;
    this.invalidated = false;
  }

  private ownerId(owner: BodyOwner): number {
    const found = this.ownerIds.get(owner);
    if (found !== undefined) return found;
    const id = ++this.ownerSeq;
    this.ownerIds.set(owner, id);
    return id;
  }

  private scoreOf(proposal: BodyProposal, score: number): BodyCandidateScore {
    return {
      proposalId: proposal.proposalId,
      ownerId: proposal.ownerId,
      ownerKind: proposal.ownerKind,
      score,
    };
  }

  private activeScore(): BodyCandidateScore {
    const active = this.active!;
    const proposal = this.proposals.get(active.token.owner);
    return proposal
      ? this.scoreOf(proposal, active.score)
      : {
          proposalId: active.proposalId,
          ownerId: active.token.ownerId,
          ownerKind: active.token.ownerKind,
          score: active.score,
        };
  }

  private acquire(proposal: BodyProposal, score: number, now: number): void {
    const token: BodyLeaseToken = Object.freeze({
      leaseId: ++this.leaseSeq,
      connectionGeneration: this.generation,
      owner: proposal.owner,
      ownerId: proposal.ownerId,
      ownerKind: proposal.ownerKind,
      acquiredAt: now,
      expiresAt: Math.min(now + this.leaseMs, proposal.validUntil),
    });
    this.active = { token, proposalId: proposal.proposalId, score };
    this.emit({ event: 'lease-acquired', at: now, generation: this.generation, token });
  }

  private renewActive(proposal: BodyProposal, score: number, now: number): boolean {
    const previous = this.active!;
    const expiresAt = Math.min(now + this.leaseMs, proposal.validUntil);
    if (expiresAt <= previous.token.expiresAt && previous.proposalId === proposal.proposalId) return false;
    const token: BodyLeaseToken = Object.freeze({
      ...previous.token,
      acquiredAt: previous.token.acquiredAt,
      expiresAt,
    });
    this.active = { token, proposalId: proposal.proposalId, score };
    this.emit({ event: 'lease-renewed', at: now, generation: this.generation, token });
    return true;
  }

  private releaseActive(reason: string, now: number): void {
    if (!this.active) return;
    const token = this.active.token;
    this.active = null;
    this.emit({ event: 'lease-released', at: now, generation: this.generation, token, reason });
  }

  private expire(now: number): void {
    for (const [owner, proposal] of this.proposals) {
      if (proposal.validUntil <= now) this.proposals.delete(owner);
    }
    if (!this.active || now < this.active.token.expiresAt) return;
    const token = this.active.token;
    this.active = null;
    this.emit({ event: 'lease-expired', at: now, generation: this.generation, token, reason: 'lease-expired' });
  }
}
