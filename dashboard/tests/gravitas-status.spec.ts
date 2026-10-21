import { describe, expect, it } from 'vitest';

import { formatSeconds } from '../src/api/gravitas';

describe('Gravitas status formatting', () => {
  it('shows a one-decimal fact age and an em dash for missing ages', () => {
    expect(formatSeconds(1.26)).toBe('1.3 s');
    expect(formatSeconds(null)).toBe('—');
    expect(formatSeconds(Number.NaN)).toBe('—');
  });
});
