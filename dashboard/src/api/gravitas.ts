export interface GravitasFact {
  scope: { kind: string; id: string };
  dimension: string;
  value: string;
  reason_code: string;
  source_id: string;
  age_seconds: number | null;
  valid_for_seconds: number;
  fresh: boolean;
}

export interface GravitasUnassessedItem {
  scope: { kind: string; id: string };
  dimensions: string[];
}

export interface GravitasStatus {
  schema_version: number;
  mode: string;
  configured_mode: string;
  enforcement_enabled: boolean;
  reason_code: string;
  controller_boot_id: string;
  policy_revision: number;
  snapshot_valid: boolean;
  snapshot_age_seconds?: number | null;
  assessment?: {
    state: string;
    facts: GravitasFact[];
    redacted_fact_count: number;
    unassessed: GravitasUnassessedItem[];
    unassessed_count: number;
    criteria: Record<string, number | string | string[]>;
    version: {
      diagnostics_schema_version: number;
      config_schema_version: number;
      controller_boot_id: string;
      policy_revision: number;
      config_digest: string;
    };
    applied_ack: {
      state: string;
      reason_code: string;
      items: Array<{
        adapter_id: string;
        policy_revision: number;
        applied: boolean;
        reason_code: string;
        acknowledged_at: number;
      }>;
    };
  };
}

export function formatSeconds(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${value.toFixed(1)} s`
    : '—';
}
