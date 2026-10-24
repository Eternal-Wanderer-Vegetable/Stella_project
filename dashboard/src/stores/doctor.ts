import { defineStore } from 'pinia';

import { api, unwrap } from '@/api/http';

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
  actions: {
    async ensureLoaded(): Promise<void> {
      if (this.result || this.loading) return;
      try {
        await this.run();
      } catch {
        // Keep the error in result so Settings can show it alongside the report area.
      }
    },
    async run(): Promise<DoctorResult | null> {
      if (this.loading) return this.result;
      this.loading = true;
      try {
        this.result = await unwrap<DoctorResult>(api.get('/system/doctor'));
        return this.result;
      } catch (error) {
        this.result = {
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        };
        throw error;
      } finally {
        this.loading = false;
      }
    },
  },
});
