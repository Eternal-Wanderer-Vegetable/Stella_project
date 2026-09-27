import { describe, expect, it } from 'vitest';

import {
  FindObservationCache,
  type SearchScope,
} from '../../../src/worlds/minecraft/search-observation.ts';

const scope = (overrides: Partial<SearchScope> = {}): SearchScope => ({
  connectionGeneration: 1,
  realm: 'benchmark',
  dimension: 'overworld',
  ...overrides,
});

describe('find observation evidence', () => {
  it('only recalls real sightings, with age, inside the same connection and dimension', () => {
    const cache = new FindObservationCache();
    expect(cache.recall(scope(), 'chest', 'block', 10_000)).toBeNull();

    cache.remember(scope(), {
      target: 'minecraft:Chest', kind: 'block', what: '箱子', at: [4, 64, 9], observedAt: 2_000,
    });
    expect(cache.recall(scope(), ' chest ', 'block', 12_000)).toMatchObject({
      at: [4, 64, 9], ageMs: 10_000, observedAt: 2_000,
    });

    expect(cache.recall(scope({ dimension: 'the_nether' }), 'chest', 'block', 12_000)).toBeNull();
    cache.remember(scope({ dimension: 'the_nether' }), {
      target: 'chest', kind: 'block', what: '箱子', at: [1, 70, 1], observedAt: 13_000,
    });
    expect(cache.recall(scope({ connectionGeneration: 2, dimension: 'the_nether' }), 'chest', 'block', 14_000))
      .toBeNull();
  });

  it('expires and bounds history without persisting stale sightings', () => {
    const cache = new FindObservationCache(100, 2);
    for (let i = 0; i < 3; i++) {
      cache.remember(scope(), {
        target: `target_${i}`, kind: 'block', what: `目标${i}`, at: [i, 64, 0], observedAt: i,
      });
    }
    expect(cache.recall(scope(), 'target_0', 'block', 3)).toBeNull();
    expect(cache.recall(scope(), 'target_1', 'block', 3)).not.toBeNull();
    expect(cache.recall(scope(), 'target_2', 'block', 200)).toBeNull();
  });
});
