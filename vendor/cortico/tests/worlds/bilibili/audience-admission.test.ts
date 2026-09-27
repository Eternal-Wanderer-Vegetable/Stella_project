import { existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  AudienceAdmission,
  type AudienceAdmissionCandidate,
} from '../../../src/worlds/bilibili/audience-admission.ts';

const DAY_MS = 24 * 60 * 60 * 1000;
const MINUTE_MS = 60 * 1000;
const roots: string[] = [];

afterEach(() => {
  vi.useRealTimers();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe('AudienceAdmission importance ledger', () => {
  it('qualifies SC by one ¥30 payment or ¥50 rolling total and leases it for 30 days', () => {
    const admission = new AudienceAdmission({ roomId: 1, now: () => 0 });

    admission.observe({ senderKey: '101', at: 0, superchatYuan: 30 });
    expect(admission.importanceOf('101', 30 * DAY_MS - 1)?.reasons).toEqual(['superchat']);
    expect(admission.importanceOf('101', 30 * DAY_MS)).toBeNull();

    admission.observe({ senderKey: '202', at: 0, superchatYuan: 20 });
    expect(admission.importanceOf('202', 10 * DAY_MS)).toBeNull();
    admission.observe({ senderKey: '202', at: 10 * DAY_MS, superchatYuan: 30 });
    expect(admission.importanceOf('202', 40 * DAY_MS - 1)?.reasons).toEqual(['superchat']);
    expect(admission.importanceOf('202', 40 * DAY_MS)).toBeNull();
  });

  it('keeps only positive guard evidence for 35 days', () => {
    const admission = new AudienceAdmission({ roomId: 1, now: () => 0 });

    admission.observe({ senderKey: '101', guardLevel: 0, at: 0 });
    expect(admission.importanceOf('101', 0)).toBeNull();
    admission.observe({ senderKey: '101', at: 1000, guardLevel: 1 });
    expect(admission.importanceOf('101', 1000)?.reasons).toEqual(['guard']);
    expect(admission.importanceOf('101', 1000 + 35 * DAY_MS - 1)?.reasons).toEqual(['guard']);
    expect(admission.importanceOf('101', 1000 + 35 * DAY_MS)).toBeNull();

    admission.observe({ senderKey: '0', guard: true, at: 0 });
    admission.observe({ senderKey: 'not-a-uid', guard: true, at: 0 });
    expect(admission.snapshot(0).trackedViewers).toBe(1);
  });

  it('qualifies interaction at the shipped default of 25 unique active minutes in one stream', () => {
    const admission = new AudienceAdmission({ roomId: 1, now: () => 0 });
    admission.startStream({ liveStartedAt: 100 });
    for (let minute = 0; minute < 24; minute++) {
      admission.observe({ senderKey: '101', at: minute * MINUTE_MS, interaction: true });
    }
    expect(admission.importanceOf('101', 24 * MINUTE_MS)).toBeNull();
    admission.observe({ senderKey: '101', at: 24 * MINUTE_MS, interaction: true });
    expect(admission.importanceOf('101', 25 * MINUTE_MS)?.reasons).toEqual(['interaction']);
  });

  it('requires N unique active minutes in each of M streams within 30 days', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      tuning: { interactionMinutesPerStream: 40, interactionStreamCount: 2 },
    });
    admission.startStream({ liveStartedAt: 100 });
    for (let minute = 0; minute < 40; minute++) {
      admission.observe({ senderKey: '101', at: minute * MINUTE_MS, interaction: true });
      admission.observe({ senderKey: '101', at: minute * MINUTE_MS + 1000, interaction: true });
    }
    expect(admission.importanceOf('101', 40 * MINUTE_MS)).toBeNull();

    admission.endStream();
    admission.startStream({ liveStartedAt: 200 });
    const secondStart = DAY_MS;
    for (let minute = 0; minute < 39; minute++) {
      admission.observe({ senderKey: '101', at: secondStart + minute * MINUTE_MS, interaction: true });
    }
    admission.observe({ senderKey: '101', at: secondStart + 38 * MINUTE_MS + 2000, interaction: true });
    expect(admission.importanceOf('101', secondStart + 39 * MINUTE_MS)).toBeNull();

    const qualifiedAt = secondStart + 39 * MINUTE_MS;
    admission.observe({ senderKey: '101', at: qualifiedAt, interaction: true });
    expect(admission.importanceOf('101', qualifiedAt)?.reasons).toEqual(['interaction']);
    expect(admission.importanceOf('101', qualifiedAt + 30 * DAY_MS - 1)?.reasons).toEqual(['interaction']);
    expect(admission.importanceOf('101', qualifiedAt + 30 * DAY_MS)).toBeNull();
  });

  it('merges a fallback stream into the later platform start identity instead of counting one live twice', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      createId: () => 'fallback',
      tuning: { interactionMinutesPerStream: 40, interactionStreamCount: 2 },
    });
    admission.startStream();
    for (let minute = 0; minute < 40; minute++) {
      admission.observe({ senderKey: '101', at: minute * MINUTE_MS, interaction: true });
    }

    admission.startStream({ liveStartedAt: 1234 });
    for (let minute = 40; minute < 80; minute++) {
      admission.observe({ senderKey: '101', at: minute * MINUTE_MS, interaction: true });
    }
    expect(admission.importanceOf('101', 80 * MINUTE_MS)).toBeNull();

    admission.endStream();
    admission.startStream({ liveStartedAt: 5678 });
    for (let minute = 0; minute < 40; minute++) {
      admission.observe({ senderKey: '101', at: DAY_MS + minute * MINUTE_MS, interaction: true });
    }
    expect(admission.importanceOf('101', DAY_MS + 40 * MINUTE_MS)?.reasons).toContain('interaction');
  });
});

describe('AudienceAdmission crowd gate', () => {
  it('uses high-energy rank hysteresis, freshness, and the bounded stale hold', () => {
    const admission = new AudienceAdmission({ roomId: 1, now: () => 0 });

    admission.observeOnlineRank(200, 0);
    expect(admission.snapshot(0).crowd).toMatchObject({ active: true, signalFresh: true });
    expect(admission.snapshot(90_001).crowd).toMatchObject({ active: true, signalFresh: false });
    expect(admission.snapshot(300_001).crowd.active).toBe(false);

    admission.observeOnlineRank(180, 300_002);
    expect(admission.snapshot(300_002).crowd.active).toBe(false);
    admission.observeOnlineRank(200, 400_000);
    admission.observeOnlineRank(170, 410_000);
    admission.observeOnlineRank(160, 529_999);
    expect(admission.snapshot(529_999).crowd.active).toBe(true);
    admission.observeOnlineRank(170, 530_000);
    expect(admission.snapshot(530_000).crowd.active).toBe(false);
  });

  it('passes the exact input order unless both crowd and batch overload are true', () => {
    const admission = new AudienceAdmission({ roomId: 1, now: () => 0 });
    const input = candidates(115);

    admission.observeOnlineRank(199, 0);
    const uncrowded = admission.project(input, 0);
    expect(uncrowded.metrics.limitingActive).toBe(false);
    expect(uncrowded.selected).toHaveLength(115);
    uncrowded.selected.forEach((item, index) => expect(item.candidate).toBe(input[index]));

    admission.observeOnlineRank(200, 1);
    const atBudget = admission.project(input.slice(0, 114), 1);
    expect(atBudget.metrics.overloaded).toBe(false);
    expect(atBudget.metrics.limitingActive).toBe(false);
    expect(atBudget.selected.map((item) => item.candidate)).toEqual(input.slice(0, 114));

    const exactTokens = [candidate('exact-tokens', '500', 'a'.repeat(3536))];
    expect(admission.project(exactTokens, 1).metrics.limitingActive).toBe(false);
    const excessTokens = [candidate('excess-tokens', '500', 'a'.repeat(3537))];
    expect(admission.project(excessTokens, 1).metrics.limitingActive).toBe(true);
  });

  it('does not carry the previous stream crowd signal into a quick restart', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      tuning: { lineBudget: 2, tokenBudget: 100 },
    });
    const input = candidates(3);
    admission.startStream({ liveStartedAt: 100 });
    admission.observeOnlineRank(200, 0);
    expect(admission.project(input, 0).metrics.limitingActive).toBe(true);

    admission.endStream();
    admission.startStream({ liveStartedAt: 200 });
    const next = admission.project(input, 1);
    expect(next.metrics.limitingActive).toBe(false);
    expect(next.metrics.crowd).toMatchObject({ onlineRankCount: null, active: false });
    expect(next.selected).toHaveLength(3);
  });

  it('applies validated hot tuning to the current signal and the next projection', () => {
    const admission = new AudienceAdmission({ roomId: 1, now: () => 10_000 });
    admission.observeOnlineRank(150, 10_000);
    expect(admission.snapshot(10_000).crowd.active).toBe(false);

    admission.updateTuning({ onlineRankCrowdedOn: 140, onlineRankCrowdedOff: 120, lineBudget: 2 });
    expect(admission.snapshot(10_000).crowd.active).toBe(true);
    expect(admission.project(candidates(3), 10_000).metrics.limitingActive).toBe(true);
    expect(() => admission.updateTuning({ onlineRankCrowdedOff: 140 })).toThrow(
      'online rank release threshold must be below activation threshold',
    );
    expect(admission.tuning.onlineRankCrowdedOff).toBe(120);
  });
});

describe('AudienceAdmission delivery projection', () => {
  it('keeps critical events, caps the important lane, samples ordinary events, and restores source order', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      tuning: { lineBudget: 10, tokenBudget: 100, importantBudgetShare: 0.5 },
    });
    admission.startStream({ liveStartedAt: 100 });
    admission.observe({ senderKey: '101', at: 0, guard: true });
    admission.observe({ senderKey: '202', at: 0, guard: true });
    admission.observeOnlineRank(200, 0);

    const input: AudienceAdmissionCandidate[] = [
      ...Array.from({ length: 8 }, (_, index) => candidate(`important-${index}`, index % 2 ? '101' : '202')),
      ...Array.from({ length: 5 }, (_, index) => candidate(`ordinary-${index}`, String(300 + index))),
      { ...candidate('critical', '999'), critical: true },
    ];
    const result = admission.project(input, 0);

    expect(result.metrics.limitingActive).toBe(true);
    expect(result.metrics.lanes.critical).toMatchObject({ input: 1, selected: 1 });
    expect(result.metrics.lanes.important.selected).toBeGreaterThan(0);
    expect(result.metrics.lanes.important.selected).toBeLessThanOrEqual(5);
    expect(result.selected.some((item) => item.candidate.stableKey === 'critical')).toBe(true);
    expect(result.selected.map((item) => item.index)).toEqual(
      [...result.selected.map((item) => item.index)].sort((a, b) => a - b),
    );
    expect(result.metrics.selectedLines).toBeLessThanOrEqual(10);
    expect(result.selected.find((item) => item.lane === 'important')?.importantParticipants[0]?.reasons)
      .toEqual(['guard']);
  });

  it('treats a merged group as important when any participant qualifies', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      tuning: { lineBudget: 2, tokenBudget: 30 },
    });
    admission.observe({ senderKey: '101', at: 0, superchatYuan: 30 });
    admission.observeOnlineRank(200, 0);
    const group = { ...candidate('group', '999'), senderKeys: ['999', '101'] };
    const result = admission.project([group, candidate('a', '301'), candidate('b', '302')], 0);

    const projected = result.selected.find((item) => item.candidate === group);
    expect(projected?.lane).toBe('important');
    expect(projected?.importantParticipants).toEqual([{ senderKey: '101', reasons: ['superchat'] }]);
  });

  it('carries fair debt across batches when only one important viewer fits', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      tuning: { lineBudget: 2, tokenBudget: 30, importantBudgetShare: 0.5 },
    });
    admission.observe({ senderKey: '101', at: 0, guard: true });
    admission.observe({ senderKey: '202', at: 0, guard: true });
    admission.observeOnlineRank(200, 0);
    const input = [
      candidate('a1', '101'),
      candidate('a2', '101'),
      candidate('b1', '202'),
      candidate('b2', '202'),
    ];

    const first = admission.project(input, 0).selected;
    const second = admission.project(input, 0).selected;
    expect(first).toHaveLength(1);
    expect(second).toHaveLength(1);
    expect(first[0]!.importantParticipants[0]!.senderKey)
      .not.toBe(second[0]!.importantParticipants[0]!.senderKey);
  });

  it('allows critical traffic to exceed the normal budget without admitting extra traffic', () => {
    const admission = new AudienceAdmission({
      roomId: 1,
      now: () => 0,
      tuning: { lineBudget: 2, tokenBudget: 30 },
    });
    admission.observeOnlineRank(200, 0);
    const input = [
      { ...candidate('c1', '101'), critical: true },
      { ...candidate('c2', '102'), critical: true },
      { ...candidate('c3', '103'), critical: true },
      candidate('ordinary', '104'),
    ];
    const result = admission.project(input, 0);

    expect(result.selected.map((item) => item.candidate.stableKey)).toEqual(['c1', 'c2', 'c3']);
    expect(result.metrics.selectedLines).toBe(3);
    expect(result.metrics.criticalOverflow).toBe(true);
  });
});

describe('AudienceAdmission persistence', () => {
  it('rejects a damaged existing ledger without overwriting it', () => {
    const root = mkdtempSync(join(tmpdir(), 'bilibili-audience-damaged-'));
    roots.push(root);
    const file = join(root, 'ledger.json');
    writeFileSync(file, '{damaged\n', 'utf8');

    expect(() => new AudienceAdmission({ roomId: 42, file })).toThrow('invalid audience ledger');
    expect(readFileSync(file, 'utf8')).toBe('{damaged\n');
  });

  it('recovers the stable backup left by an interrupted replacement', () => {
    const root = mkdtempSync(join(tmpdir(), 'bilibili-audience-recover-'));
    roots.push(root);
    const file = join(root, 'ledger.json');
    const first = new AudienceAdmission({ roomId: 42, file, now: () => 0 });
    first.observe({ senderKey: '101', at: 0, guard: true });
    first.flush();
    renameSync(file, `${file}.bak`);

    const recovered = new AudienceAdmission({ roomId: 42, file, now: () => 0 });
    expect(recovered.importanceOf('101', 0)?.reasons).toEqual(['guard']);
    expect(existsSync(file)).toBe(true);
    expect(existsSync(`${file}.bak`)).toBe(false);
  });

  it('writes dirty state at the thirty-second snapshot interval', () => {
    vi.useFakeTimers();
    const root = mkdtempSync(join(tmpdir(), 'bilibili-audience-debounce-'));
    roots.push(root);
    const file = join(root, 'ledger.json');
    const admission = new AudienceAdmission({ roomId: 42, file, now: () => 0 });
    admission.observe({ senderKey: '101', at: 0, guard: true });

    vi.advanceTimersByTime(29_999);
    expect(existsSync(file)).toBe(false);
    vi.advanceTimersByTime(1);
    expect(existsSync(file)).toBe(true);
  });

  it('reports timer persistence failures without crashing and retries after the next update', () => {
    vi.useFakeTimers();
    const root = mkdtempSync(join(tmpdir(), 'bilibili-audience-persist-error-'));
    roots.push(root);
    const blockedDir = join(root, 'blocked');
    const file = join(blockedDir, 'ledger.json');
    writeFileSync(blockedDir, 'not a directory', 'utf8');
    const errors: Error[] = [];
    const admission = new AudienceAdmission({
      roomId: 42,
      file,
      now: () => 0,
      onPersistError: (error) => errors.push(error),
    });

    expect(() => vi.advanceTimersByTime(30_000)).not.toThrow();
    expect(errors).toHaveLength(1);
    expect(admission.snapshot().persistenceError).toBeTruthy();

    rmSync(blockedDir);
    mkdirSync(blockedDir);
    admission.observe({ senderKey: '101', at: 0, guard: true });
    vi.advanceTimersByTime(30_000);
    expect(existsSync(file)).toBe(true);
    expect(admission.snapshot().persistenceError).toBeNull();
  });

  it('persists only UID machine signals and reuses an open fallback stream across restart', () => {
    const root = mkdtempSync(join(tmpdir(), 'bilibili-audience-'));
    roots.push(root);
    const file = join(root, 'ledger.json');
    const ids = ['private-salt', 'fallback-stream'];
    const first = new AudienceAdmission({ roomId: 42, file, now: () => 0, createId: () => ids.shift()! });
    const streamId = first.startStream();
    first.observe({ senderKey: '101', interaction: true, superchatYuan: 30, at: 0 });
    first.observeOnlineRank(200, 0);
    const input = candidates(20, '观众昵称与秘密正文');
    const projected = first.project(input, 0);
    first.flush();

    const stored = readFileSync(file, 'utf8');
    expect(stored).not.toContain('观众昵称');
    expect(stored).not.toContain('秘密正文');
    expect(stored).not.toContain('meta-name');
    expect(stored).toContain('"101"');

    const second = new AudienceAdmission({ roomId: 42, file, now: () => 0, createId: () => 'unused' });
    expect(second.startStream()).toBe(streamId);
    second.observeOnlineRank(200, 0);
    expect(second.project(input, 0).selected.map((item) => item.candidate.stableKey))
      .toEqual(projected.selected.map((item) => item.candidate.stableKey));

    second.endStream();
    second.flush();
    const third = new AudienceAdmission({ roomId: 42, file, now: () => 0, createId: () => 'next-stream' });
    expect(third.startStream()).not.toBe(streamId);
    third.stop();
  });

  it('keeps ordinary sampling stable across restart with the persisted salt and stream', () => {
    const root = mkdtempSync(join(tmpdir(), 'bilibili-sampling-'));
    roots.push(root);
    const file = join(root, 'ledger.json');
    const ids = ['salt', 'stream'];
    const input = candidates(15);
    const tuning = { lineBudget: 4, tokenBudget: 100 };
    const first = new AudienceAdmission({ roomId: 42, file, now: () => 0, tuning, createId: () => ids.shift()! });
    first.startStream();
    first.observeOnlineRank(200, 0);
    const selected = first.project(input, 0).selected.map((item) => item.candidate.stableKey);
    first.stop();

    const second = new AudienceAdmission({ roomId: 42, file, now: () => 0, tuning });
    second.observeOnlineRank(200, 0);
    expect(second.project(input, 0).selected.map((item) => item.candidate.stableKey)).toEqual(selected);
    second.stop();
  });
});

function candidate(stableKey: string, senderKey: string, text = 'x'): AudienceAdmissionCandidate {
  return {
    stableKey,
    text,
    type: 'bilibili.danmaku',
    senderKeys: [senderKey],
    meta: { uname: 'meta-name' },
  };
}

function candidates(count: number, text = 'x'): AudienceAdmissionCandidate[] {
  return Array.from({ length: count }, (_, index) => candidate(`event-${index}`, String(1000 + index), text));
}
