export type FindKind = 'block' | 'entity';

export interface SearchScope {
  connectionGeneration: number;
  realm: string;
  dimension: string;
}

interface ObservedFindHit {
  kind: FindKind;
  target: string;
  what: string;
  at: [number, number, number];
  observedAt: number;
}

interface AgedFindHit extends ObservedFindHit {
  ageMs: number;
}

const HISTORY_TTL_MS = 15 * 60_000;
const HISTORY_LIMIT = 128;

function canonicalFindTarget(target: string): string {
  return target.trim().toLowerCase().replace(/^minecraft:/, '');
}

function scopeKey(scope: SearchScope): string {
  return `${scope.connectionGeneration}\0${scope.realm}\0${scope.dimension}`;
}

function observationKey(scope: SearchScope, target: string, kind: FindKind): string {
  return `${scopeKey(scope)}\0${kind}\0${canonicalFindTarget(target)}`;
}

/** Recent sightings are process-local evidence and never survive a connection or dimension boundary. */
export class FindObservationCache {
  private entries = new Map<string, ObservedFindHit>();
  private activeScope: string | null = null;

  constructor(
    private readonly ttlMs = HISTORY_TTL_MS,
    private readonly limit = HISTORY_LIMIT,
  ) {}

  sync(scope: SearchScope): void {
    const next = scopeKey(scope);
    if (this.activeScope !== null && this.activeScope !== next) this.entries.clear();
    this.activeScope = next;
  }

  remember(
    scope: SearchScope,
    hit: Omit<ObservedFindHit, 'observedAt' | 'target'> & { target: string; observedAt?: number },
  ): void {
    this.sync(scope);
    const observedAt = hit.observedAt ?? Date.now();
    this.purge(observedAt);
    const key = observationKey(scope, hit.target, hit.kind);
    this.entries.delete(key);
    this.entries.set(key, { ...hit, target: canonicalFindTarget(hit.target), observedAt });
    while (this.entries.size > this.limit) this.entries.delete(this.entries.keys().next().value!);
  }

  recall(
    scope: SearchScope,
    target: string,
    kind: FindKind,
    now = Date.now(),
  ): AgedFindHit | null {
    this.sync(scope);
    this.purge(now);
    const key = observationKey(scope, target, kind);
    const hit = this.entries.get(key);
    if (!hit) return null;
    this.entries.delete(key);
    this.entries.set(key, hit);
    return { ...hit, ageMs: Math.max(0, now - hit.observedAt) };
  }

  clear(): void {
    this.entries.clear();
    this.activeScope = null;
  }

  private purge(now: number): void {
    for (const [key, hit] of this.entries) {
      if (now - hit.observedAt > this.ttlMs) this.entries.delete(key);
    }
  }
}

