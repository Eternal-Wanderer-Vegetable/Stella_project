/** Append-only usage ledger. Failed writes remain queued and are reported to the operator. */
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import type { UsageRecord } from './types.ts';

export class UsageLog {
  private pending: UsageRecord[] = [];
  private error: string | null = null;
  private reconcile = false;
  constructor(private readonly file: string, private readonly report: (message: string) => void = console.error) {}

  append(rec: UsageRecord): void {
    this.pending.push(structuredClone({ ...rec, version: 2, recordId: rec.recordId ?? rec.attempt?.id ?? crypto.randomUUID() }));
    this.flush();
  }

  flush(): void {
    if (!this.pending.length) return;
    try {
      mkdirSync(dirname(this.file), { recursive: true });
      if (this.reconcile) {
        const ids = new Set(this.readDisk().map(record => record.recordId ?? record.attempt?.id));
        this.pending = this.pending.filter(record => !ids.has(record.recordId));
        this.reconcile = false;
      }
      while (this.pending.length) {
        // A newline isolates a prior torn append; damaged lines remain available for inspection.
        appendFileSync(this.file, '\n' + JSON.stringify(this.pending[0]) + '\n', 'utf8');
        this.pending.shift();
      }
      this.error = null;
    } catch (error) { this.reconcile = true; this.note(error); }
  }

  status(): { pending: number; error: string | null } { return { pending: this.pending.length, error: this.error }; }

  private note(error: unknown): void {
    const message = `Usage ledger ${this.file}: ${String(error)}`;
    if (message !== this.error) this.report(message);
    this.error = message;
  }

  private readDisk(): UsageRecord[] {
    if (!existsSync(this.file)) return [];
    const out: UsageRecord[] = [];
    const seen = new Set<string>();
    let damaged = 0;
    for (const line of readFileSync(this.file, 'utf8').split(/\r?\n/)) {
      if (!line.trim()) continue;
      let record: UsageRecord;
      try { record = JSON.parse(line) as UsageRecord; } catch { damaged++; continue; }
      if (!record || record.version !== 2 || typeof record.ts !== 'string') { damaged++; continue; }
      const id = record.recordId ?? record.attempt?.id;
      if (id && seen.has(id)) continue;
      if (id) seen.add(id);
      out.push(record);
    }
    if (damaged) this.note(`${damaged} damaged ledger lines retained on disk`);
    return out;
  }

  readAll(): UsageRecord[] {
    let records: UsageRecord[] = [];
    try { records = this.readDisk(); } catch (error) { this.note(error); }
    const ids = new Set(records.map(record => record.recordId ?? record.attempt?.id));
    return [...records, ...this.pending.filter(record => !ids.has(record.recordId))];
  }

  count(): number { return this.readAll().length; }

  clear(): number {
    const count = this.count();
    mkdirSync(dirname(this.file), { recursive: true });
    writeFileSync(this.file, '', 'utf8');
    this.pending = [];
    this.error = null;
    return count;
  }
}
