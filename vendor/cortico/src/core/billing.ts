import type { Charge } from './generation.ts';
import type { UsageRecord } from './types.ts';

export interface BillingBalance {
  currency: string;
  basis: 'marginal' | 'equivalent';
  knownAmount: number;
  pricedCalls: number;
  partialCalls: number;
}

export function recordCharges(record: UsageRecord): readonly Charge[] { return record.attempt?.charges ?? record.charges ?? []; }

/** Currency and cost basis are separate ledgers. Unquoted rows remain visible in coverage. */
export function billingBalances(records: readonly UsageRecord[]): BillingBalance[] {
  const balances = new Map<string, BillingBalance>();
  for (const record of records) for (const charge of recordCharges(record)) {
    const { currency, basis } = charge.quote;
    const key = JSON.stringify([currency, basis]);
    const balance = balances.get(key) ?? { currency, basis, knownAmount: 0, pricedCalls: 0, partialCalls: 0 };
    balance.knownAmount += charge.knownAmount;
    if (charge.amount === null) balance.partialCalls++; else balance.pricedCalls++;
    balances.set(key, balance);
  }
  return [...balances.values()].sort((a,b) => a.basis.localeCompare(b.basis) || a.currency.localeCompare(b.currency));
}
