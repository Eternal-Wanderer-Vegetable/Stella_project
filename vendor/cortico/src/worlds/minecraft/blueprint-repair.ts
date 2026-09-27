/**
 * 严格解析失败时按固定规则规范化格式，再次运行解析及注册表校验。
 * 实际矩阵决定尺寸，缺格用 structure_void 补齐；不裁剪已有内容，不改方块名、属性值或越界索引。
 */

import {
  paletteEntryToState,
  type NormalizedBlueprint,
  type SizeXYZ,
} from './blueprint.ts';
import { BLUEPRINT_MC_VERSION, completeBlockStateDefaults } from './blueprint-registry.ts';

const REPAIR_POLICY_VERSION = 'blueprint-repair-v1' as const;

interface RepairAction {
  code:
    | 'visible-json-recovery'
    | 'axis-order-normalization'
    | 'declared-size-normalization'
    | 'dense-grid-fit'
    | 'default-state-completion';
  message: string;
  count: number;
  samples: string[];
}

export interface RepairReport {
  policyVersion: typeof REPAIR_POLICY_VERSION;
  strictValid: boolean;
  strictError: string | null;
  applied: boolean;
  actions: RepairAction[];
}

export function createRepairReport(): RepairReport {
  return {
    policyVersion: REPAIR_POLICY_VERSION,
    strictValid: false,
    strictError: null,
    applied: false,
    actions: [],
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseJsonObject(text: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(text.trim()) as unknown;
    return isRecord(value) ? value : null;
  } catch {
    return null;
  }
}

function unwrapSubmission(
  value: Record<string, unknown>,
  expectedToolName: string,
): Record<string, unknown> | null {
  // 裸蓝图提交以 size_xyz 识别；工具调用包装以 arguments/parameters 识别。
  // name 也是裸蓝图的合法字段，不能用作包装判据。
  if (Array.isArray(value.size_xyz)) return value;
  if (value.arguments !== undefined || value.parameters !== undefined) {
    if (value.name !== expectedToolName) return null;
    const wrapped = value.arguments ?? value.parameters;
    const args = typeof wrapped === 'string' ? parseJsonObject(wrapped) : wrapped;
    return isRecord(args) ? args : null;
  }
  return null;
}

/** 仅提取正文中唯一一份完整蓝图提交。 */
export function recoverVisibleSubmission(
  visibleContent: string,
  expectedToolName: string,
): Record<string, unknown> | null {
  const candidates: string[] = [];
  for (const match of visibleContent.matchAll(/```[^\r\n]*\r?\n?([\s\S]*?)```/g)) {
    candidates.push(match[1]);
  }
  if (candidates.length === 0) candidates.push(visibleContent);

  const recovered = new Map<string, Record<string, unknown>>();
  for (const candidate of candidates) {
    const parsed = parseJsonObject(candidate);
    if (!parsed) continue;
    const submission = unwrapSubmission(parsed, expectedToolName);
    if (submission) recovered.set(JSON.stringify(submission), submission);
  }
  return recovered.size === 1 ? [...recovered.values()][0] : null;
}

/** 查找可规范化为 minecraft:structure_void 的 Palette 索引。 */
function preserveIndex(submission: Record<string, unknown>): number | undefined {
  if (!Array.isArray(submission.palette)) return undefined;
  for (let index = 0; index < submission.palette.length; index++) {
    try {
      if (paletteEntryToState(submission.palette[index]) === 'minecraft:structure_void') return index;
    } catch {
    }
  }
  return undefined;
}

/** 补齐轴序并统一大小写；按矩阵计算尺寸，向东、向南用 structure_void 补齐参差行。 */
export function repairSubmissionShape(
  value: Record<string, unknown>,
): { submission: Record<string, unknown>; actions: RepairAction[] } {
  const submission = structuredClone(value);
  const actions: RepairAction[] = [];

  if (submission.axis_order === undefined
    || (typeof submission.axis_order === 'string'
      && submission.axis_order.toUpperCase() === 'YZX')) {
    if (submission.axis_order !== 'YZX') {
      submission.axis_order = 'YZX';
      actions.push({
        code: 'axis-order-normalization',
        message: '轴序缺失或大小写不一致,按固定顺序解释。',
        count: 1,
        samples: ['按高度、南北、东西读取三维矩阵'],
      });
    }
  }

  if (!Array.isArray(submission.layers)) return { submission, actions };
  let filler = preserveIndex(submission);
  const layers = submission.layers as unknown[];
  if (layers.length === 0 || layers.some((layer) => !Array.isArray(layer))) {
    return { submission, actions };
  }
  const sizeY = layers.length;
  const sizeZ = Math.max(...layers.map((layer) => (layer as unknown[]).length));
  const rows = layers.flatMap((layer) => layer as unknown[]);
  if (sizeZ === 0 || rows.some((row) => !Array.isArray(row))) return { submission, actions };
  const sizeX = Math.max(...rows.map((row) => (row as unknown[]).length));
  if (sizeX === 0) return { submission, actions };

  const inferred: SizeXYZ = [sizeX, sizeY, sizeZ];
  const declared = Array.isArray(submission.size_xyz) ? submission.size_xyz.join('×') : '未声明';
  if (declared !== inferred.join('×')) {
    submission.size_xyz = inferred;
    actions.push({
      code: 'declared-size-normalization',
      message: '声明尺寸按实际画出的矩阵登记。',
      count: 1,
      samples: [`${declared} → ${inferred.join('×')}`],
    });
  }

  const ragged = layers.some((layer) => (layer as unknown[]).length !== sizeZ)
    || rows.some((row) => (row as unknown[]).length !== sizeX);
  if (ragged && filler === undefined && Array.isArray(submission.palette)) {
    filler = submission.palette.length;
    submission.palette.push('minecraft:structure_void');
  }

  let padded = 0;
  const samples: string[] = [];
  for (let y = 0; y < layers.length; y++) {
    const layer = layers[y] as unknown[];
    const zDelta = layer.length - sizeZ;
    if (zDelta < 0 && filler !== undefined) {
      for (let count = 0; count < -zDelta; count++) {
        layer.push(Array.from({ length: sizeX }, () => filler));
        padded += sizeX;
      }
      samples.push(`第 ${y + 1} 层南侧补保留格 ${-zDelta} 行`);
    }
    for (let z = 0; z < layer.length; z++) {
      const row = layer[z] as unknown[];
      const xDelta = row.length - sizeX;
      if (xDelta < 0 && filler !== undefined) {
        row.push(...Array.from({ length: -xDelta }, () => filler));
        padded += -xDelta;
        samples.push(`第 ${y + 1} 层第 ${z + 1} 行东侧补保留格 ${-xDelta} 格`);
      }
    }
  }

  if (padded > 0) {
    actions.push({
      code: 'dense-grid-fit',
      message: '参差矩阵扩成实际内容所需的最小长方体,缺格解释为不属于工地。',
      count: padded,
      samples: [...samples.slice(0, 4), `共补 ${padded} 个保留格;没有裁掉任何内容`],
    });
  }
  return { submission, actions };
}

/** 整份蓝图逐格补默认属性;一条都没补时 action 是 null */
export function completeBlueprintStateDefaults(
  blueprint: NormalizedBlueprint,
): { blueprint: NormalizedBlueprint; action: RepairAction | null } {
  const cache = new Map<string, string>();
  const samples = new Set<string>();
  let cells = 0;

  const complete = (state: string): string => {
    const cached = cache.get(state);
    if (cached !== undefined) {
      if (cached !== state) cells++;
      return cached;
    }
    let completion: ReturnType<typeof completeBlockStateDefaults>;
    try {
      completion = completeBlockStateDefaults(state);
    } catch {
      cache.set(state, state);
      return state;
    }
    const added = Object.entries(completion.added);
    if (added.length > 0) {
      cells++;
      if (samples.size < 8) {
        samples.add(`${state.split('[', 1)[0]}:${added.map(([k, v]) => `${k}=${v}`).join(',')}`);
      }
    }
    cache.set(state, completion.state);
    return completion.state;
  };

  const layers = blueprint.layers.map((layer) => layer.map((row) => row.map(complete)));
  return {
    blueprint: { size_xyz: [...blueprint.size_xyz], site_mode: blueprint.site_mode, layers },
    action: cells === 0 ? null : {
      code: 'default-state-completion',
      message: `漏写的方块属性按 Minecraft ${BLUEPRINT_MC_VERSION} 官方默认状态补齐。`,
      count: cells,
      samples: [...samples],
    },
  };
}
