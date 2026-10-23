import { defineStore } from 'pinia';

export interface DoctorItem {
  id: string;
  level: string;
  title: string;
  detail?: string;
  fix_hint?: string;
}

export interface DoctorSummary {
  ok: number;
  warn: number;
  error: number;
  blocking: boolean;
  total: number;
}

export interface DoctorReport {
  version: number;
  summary: DoctorSummary;
  items: DoctorItem[];
}

export interface DoctorResult {
  ok: boolean;
  report?: DoctorReport;
  summary?: DoctorSummary;
  error?: string;
  output?: string;
  exit_code?: number;
}

// Keep the most recent environment check while the user navigates between pages.
export const useDoctorStore = defineStore('doctor', {
  state: () => ({
    result: null as DoctorResult | null,
    loading: false,
  }),
});
