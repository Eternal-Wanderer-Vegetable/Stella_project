import { join } from 'node:path';
import type { WorldDefinition } from '../../world.ts';
import { type BilibiliConfigSection, BILIBILI_DEFAULTS } from './config.ts';
import { BilibiliWorld } from './world.ts';

export const BILIBILI: WorldDefinition<BilibiliConfigSection> = {
  id: 'bilibili',
  label: 'B 站直播间',
  defaults: () => structuredClone(BILIBILI_DEFAULTS),
  create: (ctx) => {
    const { cfg } = ctx;
    return new BilibiliWorld({
      roomId: cfg.roomId,
      sessdata: cfg.sessdata,
      giftFlushYuan: () => cfg.giftFlushYuan,
      coalesceWindowMs: () => cfg.coalesceWindowMs,
      coalesceMaxItems: () => cfg.coalesceMaxItems,
      audienceOnlineRankOn: () => cfg.audienceOnlineRankOn,
      audienceOnlineRankOff: () => cfg.audienceOnlineRankOff,
      audienceReleaseHoldSec: () => cfg.audienceReleaseHoldSec,
      audienceSignalFreshSec: () => cfg.audienceSignalFreshSec,
      audienceActiveStaleHoldSec: () => cfg.audienceActiveStaleHoldSec,
      audienceEventLineBudget: () => cfg.audienceEventLineBudget,
      audienceEventTokenBudget: () => cfg.audienceEventTokenBudget,
      audienceImportantShare: () => cfg.audienceImportantShare,
      audienceLedgerFile: join(ctx.dataDir, 'bilibili-audience', 'ledger.json'),
      overlay: cfg.overlay,
      agentNoticeMaxChars: () => cfg.overlay.agentNoticeMaxChars,
      agentNoticeFile: join(ctx.dataDir, 'bilibili-overlay', 'agent-notice.json'),
      overlayAssetDir: join(ctx.dataDir, 'bilibili-overlay', 'assets'),
      onOverlayConfig: (overlay) => ctx.persist({ overlay: { design: overlay.design } }),
      timezone: ctx.timezone,
    });
  },
};
