// Snapshot derived from tests/platforms/adapter_matrix.json (2026-10-25).
// Fixture results do not certify live platform behavior.
export interface TransportEvidenceLevel {
  fixture: string;
  live: string;
}

export interface TransportEvidence {
  capabilityProvider: string;
  finalStatus: string;
  levels: Record<string, TransportEvidenceLevel>;
}

export const transportEvidence: Record<string, TransportEvidence> = {
  'onebot-v11': {
    capabilityProvider: 'core.transport.capabilities.ONEBOT_V11_CAPABILITIES via StaticCapabilityProvider',
    finalStatus: 'not_certified',
    levels: {
      L0: { fixture: 'not_run', live: 'not_run' },
      L1: { fixture: 'pass', live: 'not_run' },
      L2: { fixture: 'not_run', live: 'not_run' },
      L3: { fixture: 'partial', live: 'not_run' },
    },
  },
  telegram: {
    capabilityProvider: 'core.transport.adapters.telegram.TELEGRAM_CAPABILITIES via StaticCapabilityProvider',
    finalStatus: 'not_certified',
    levels: {
      L0: { fixture: 'pass', live: 'not_run' },
      L1: { fixture: 'pass', live: 'not_run' },
      L2: { fixture: 'partial', live: 'not_run' },
      L3: { fixture: 'partial', live: 'not_run' },
    },
  },
  discord: {
    capabilityProvider: 'core.transport.adapters.discord.DISCORD_CAPABILITIES via StaticCapabilityProvider',
    finalStatus: 'not_certified',
    levels: {
      L0: { fixture: 'pass', live: 'not_run' },
      L1: { fixture: 'pass', live: 'not_run' },
      L2: { fixture: 'partial', live: 'not_run' },
      L3: { fixture: 'partial', live: 'not_run' },
    },
  },
  'qq-official': {
    capabilityProvider: 'core.transport.adapters.qq.QQ_CAPABILITIES via StaticCapabilityProvider',
    finalStatus: 'not_certified',
    levels: {
      L0: { fixture: 'not_run', live: 'not_run' },
      L1: { fixture: 'pass', live: 'not_run' },
      L2: { fixture: 'pass', live: 'not_run' },
      L3: { fixture: 'partial', live: 'not_run' },
    },
  },
};
