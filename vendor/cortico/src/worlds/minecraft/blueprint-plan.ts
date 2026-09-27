/**
 * 蓝图受理、施工中间表示（IR）编译、世界核验、材料统计与进度计算。
 * 体量按 Palette 编码长度计；普通放置核验方块类型并报告属性差异，功能动作核验指定属性。
 * 自底向上逐层编译，层内按行扫描，合并与 stopAfter 均不跨层。
 */

import {
  blockIdOf,
  isAirState,
  isStructureVoidState,
  multiPartRole,
  normalizeBlockName,
  tryNormalizeBlueprint,
  voxelMetrics,
  type NormalizedBlueprint,
  type PositionXYZ,
  type SizeXYZ,
  type VoxelMetrics,
} from './blueprint.ts';
import {
  BLUEPRINT_TOOL_FAMILIES,
  blueprintNeedsTilledSoil,
  blueprintPlacementMethod,
  blueprintSupportRules,
  blueprintSupportViolation,
  validateBlueprintPlaceability,
  validateBlueprintRegistry,
  type BlueprintStateFailure,
  type BlueprintPlacementMethod,
} from './blueprint-registry.ts';
import {
  completeBlueprintStateDefaults,
  createRepairReport,
  repairSubmissionShape,
  type RepairReport,
} from './blueprint-repair.ts';
import type { Anchor } from './geometry.ts';

/** palette 编码交稿的最大字符数；分批只改变传输方式，不改变这条总预算。 */
export const BLUEPRINT_MAX_OUTPUT_CHARS = 131_072;
/** 单个底层 build 调用的体素上限；大平面会在 IR 内自动切步。 */
const BLUEPRINT_STEP_CELL_CAP = 256;

// ── 额外校验 ──────────────────────────────────────────────────────────────────

/** 规范化蓝图按实际 palette 编码估算交稿长度。 */
export function blueprintOutputChars(blueprint: NormalizedBlueprint): number {
  const index = new Map<string, number>();
  const palette: string[] = [];
  const layers = blueprint.layers.map((layer) => layer.map((row) => row.map((state) => {
    let at = index.get(state);
    if (at === undefined) {
      at = palette.length;
      index.set(state, at);
      palette.push(state);
    }
    return at;
  })));
  return JSON.stringify({
    site_mode: blueprint.site_mode,
    size_xyz: blueprint.size_xyz,
    axis_order: 'YZX',
    palette,
    layers,
  }).length;
}

/** 按编码字符数限制提交大小。 */
export function validateBlueprintLimits(
  blueprint: NormalizedBlueprint,
): BlueprintStateFailure[] {
  const chars = blueprintOutputChars(blueprint);
  return chars <= BLUEPRINT_MAX_OUTPUT_CHARS ? [] : [{
    path: 'layers',
    state: String(chars),
    reason: `palette 编码后约 ${chars} 字符,总输出上限 ${BLUEPRINT_MAX_OUTPUT_CHARS} 字符`,
  }];
}

// ── IR ────────────────────────────────────────────────────────────────────────

/** 一个同状态长方体的施工步骤；from/to 是含端点的蓝图局部坐标。 */
export interface BlueprintStep {
  /** 步序,0 起,即游标口径 */
  index: number;
  state: string;
  /** 完成这一步要拿的方块、工具或可使用物品。 */
  item: string;
  /** 直接放置，或用物品把目标格加工出来。 */
  method: BlueprintPlacementMethod;
  from: PositionXYZ;
  to: PositionXYZ;
  cells: number;
  /** 所在层;并块不跨层,所以 from[1] === to[1] === y */
  y: number;
}

/** 门上半格、床头等从部件不单独生成步骤，仍参与主步骤的完成核验。 */
export interface BlueprintCheckCell {
  pos: PositionXYZ;
  state: string;
  mainPos: PositionXYZ;
  /** 主部件落在第几步 */
  mainStep: number;
}

/** 需要在工地核验的图外条件；不阻止设计受理。 */
interface BlueprintAdvisory {
  /** 同一条提醒第一次出现的位置 */
  path: string;
  state: string;
  reason: string;
  /** 这一条覆盖的格数 */
  cells: number;
}

/** 现场前提那一段回执;失败清单(renderBlueprintFailures)同一个形状 */
export function renderBlueprintAdvisories(advisories: readonly BlueprintAdvisory[]): string {
  const shown = advisories.slice(0, 6);
  const lines = shown.map((a) => `· ${a.path}${a.state ? `(${a.state})` : ''}: ${a.reason}`
    + `${a.cells > 1 ? `(同样的还有 ${a.cells - 1} 格)` : ''}`);
  const more = advisories.length > shown.length ? `\n(还有 ${advisories.length - shown.length} 条同类)` : '';
  return `${lines.join('\n')}${more}`;
}

export interface BlueprintPlan {
  steps: BlueprintStep[];
  checks: BlueprintCheckCell[];
  /** 要施工的格数(不含从部件)。 */
  placeCells: number;
  /** 编译期发现的设计问题(孤立从部件、放不出的状态、图内撑不住的支撑) */
  failures: BlueprintStateFailure[];
  /** 依赖图外现场的前提;不影响受理 */
  advisories: BlueprintAdvisory[];
}

type CellRole = 'air' | 'place' | 'secondary' | 'broken';

function cellPath(x: number, y: number, z: number): string {
  return `layers[${y}][${z}][${x}]`;
}

/**
 * 图内支撑不符合规则时拒绝；图外或 structure_void 支撑只生成现场核验提示。
 * 按状态、要求和违规类型归并，报告首个位置与数量。
 */
function reviewSupports(
  blueprint: NormalizedBlueprint,
  roles: readonly CellRole[][][],
): { failures: BlueprintStateFailure[]; advisories: BlueprintAdvisory[] } {
  const [sizeX, sizeY, sizeZ] = blueprint.size_xyz;
  const failures = new Map<string, BlueprintStateFailure & { cells: number }>();
  const advisories = new Map<string, BlueprintAdvisory>();

  for (let y = 0; y < sizeY; y++) {
    for (let z = 0; z < sizeZ; z++) {
      for (let x = 0; x < sizeX; x++) {
        if (roles[y][z][x] !== 'place') continue;
        const state = blueprint.layers[y][z][x];
        for (const rule of blueprintSupportRules(state)) {
          const [sx, sy, sz] = [x + rule.offset[0], y + rule.offset[1], z + rule.offset[2]];
          const outside = sx < 0 || sy < 0 || sz < 0 || sx >= sizeX || sy >= sizeY || sz >= sizeZ;
          const support = outside ? null : blueprint.layers[sy][sz][sx];

          if (support === null || isStructureVoidState(support)) {
            const key = `${state}|${rule.demand}`;
            const seen = advisories.get(key);
            if (seen === undefined) {
              advisories.set(key, {
                path: cellPath(x, y, z),
                state,
                reason: `${rule.demand};支撑那一格不在图里,施工前现场必须已经满足`,
                cells: 1,
              });
            } else seen.cells++;
            continue;
          }

          const violation = blueprintSupportViolation(rule, support);
          if (violation === null) continue;
          const key = `${state}|${rule.demand}|${violation}`;
          const seen = failures.get(key);
          if (seen === undefined) {
            failures.set(key, {
              path: cellPath(x, y, z),
              state,
              reason: `${rule.demand};${violation},原版放不下去`,
              cells: 1,
            });
          } else seen.cells++;
        }
      }
    }
  }

  return {
    failures: [...failures.values()].map(({ cells, ...failure }) => (cells === 1
      ? failure
      : { ...failure, reason: `${failure.reason}(同样的还有 ${cells - 1} 格)` })),
    advisories: [...advisories.values()],
  };
}

/** 按层、从北向南及从西向东编译；同状态格先向东合并，再合并相邻整行。 */
export function compileBlueprint(blueprint: NormalizedBlueprint): BlueprintPlan {
  const [sizeX, sizeY, sizeZ] = blueprint.size_xyz;
  const failures: BlueprintStateFailure[] = [];
  const roles: CellRole[][][] = [];
  const pendingChecks: Array<{ pos: PositionXYZ; state: string; mainPos: PositionXYZ }> = [];

  const stateAt = (x: number, y: number, z: number): string | null =>
    x < 0 || y < 0 || z < 0 || x >= sizeX || y >= sizeY || z >= sizeZ
      ? null
      : blueprint.layers[y][z][x];

  for (let y = 0; y < sizeY; y++) {
    const layer: CellRole[][] = [];
    for (let z = 0; z < sizeZ; z++) {
      const row: CellRole[] = [];
      for (let x = 0; x < sizeX; x++) {
        const state = blueprint.layers[y][z][x];
        if (isAirState(state)) { row.push('air'); continue; }

        const method = blueprintPlacementMethod(state);
        if (method.item === null) {
          failures.push({ path: cellPath(x, y, z), state, reason: method.reason });
          row.push('broken');
          continue;
        }

        const role = multiPartRole(state);
        if (role.role !== 'secondary') { row.push('place'); continue; }

        const [dx, dy, dz] = role.mainOffset;
        const mainPos: PositionXYZ = [x + dx, y + dy, z + dz];
        const mainState = stateAt(mainPos[0], mainPos[1], mainPos[2]);
        const mainRole = mainState === null ? null : multiPartRole(mainState);
        const paired = mainState !== null
          && mainRole !== null
          && mainRole.role === 'main'
          && blockIdOf(mainState) === blockIdOf(state)
          && mainRole.secondaryOffset[0] === -dx
          && mainRole.secondaryOffset[1] === -dy
          && mainRole.secondaryOffset[2] === -dz;
        if (!paired) {
          failures.push({
            path: cellPath(x, y, z),
            state,
            reason: `这是多格方块的从部件,主部件该在 ${mainPos.join(',')},那一格却是 ` +
              `${mainState ?? '矩阵之外'}`,
          });
          row.push('broken');
          continue;
        }
        pendingChecks.push({ pos: [x, y, z], state, mainPos });
        row.push('secondary');
      }
      layer.push(row);
    }
    roles.push(layer);
  }

  const supports = reviewSupports(blueprint, roles);
  failures.push(...supports.failures);

  const steps: BlueprintStep[] = [];
  const stepOfCell = new Map<string, number>();
  const key = (x: number, y: number, z: number): string => `${x},${y},${z}`;
  let placeCells = 0;

  for (let y = 0; y < sizeY; y++) {
    const claimed = roles[y].map((row) => row.map((role) => role !== 'place'));
    for (let z = 0; z < sizeZ; z++) {
      for (let x = 0; x < sizeX; x++) {
        if (claimed[z][x]) continue;
        const state = blueprint.layers[y][z][x];

        let width = 1;
        while (x + width < sizeX
          && !claimed[z][x + width]
          && blueprint.layers[y][z][x + width] === state) width++;

        let depth = 1;
        while (z + depth < sizeZ) {
          let uniform = true;
          for (let step = 0; step < width; step++) {
            if (claimed[z + depth][x + step] || blueprint.layers[y][z + depth][x + step] !== state) {
              uniform = false;
              break;
            }
          }
          if (!uniform) break;
          depth++;
        }

        const method = blueprintPlacementMethod(state);
        if (method.item === null) {
          failures.push({ path: cellPath(x, y, z), state, reason: method.reason });
          continue;
        }
        let zOffset = 0;
        while (zOffset < depth) {
          const chunkDepth = Math.min(
            depth - zOffset,
            Math.max(1, Math.floor(BLUEPRINT_STEP_CELL_CAP / Math.min(width, BLUEPRINT_STEP_CELL_CAP))),
          );
          let xOffset = 0;
          while (xOffset < width) {
            const chunkWidth = Math.min(
              width - xOffset,
              Math.floor(BLUEPRINT_STEP_CELL_CAP / chunkDepth),
            );
            const index = steps.length;
            for (let dz = 0; dz < chunkDepth; dz++) {
              for (let dx = 0; dx < chunkWidth; dx++) {
                const cellX = x + xOffset + dx;
                const cellZ = z + zOffset + dz;
                claimed[cellZ][cellX] = true;
                stepOfCell.set(key(cellX, y, cellZ), index);
              }
            }
            const cells = chunkWidth * chunkDepth;
            placeCells += cells;
            steps.push({
              index,
              state,
              item: method.item,
              method,
              from: [x + xOffset, y, z + zOffset],
              to: [x + xOffset + chunkWidth - 1, y, z + zOffset + chunkDepth - 1],
              cells,
              y,
            });
            xOffset += chunkWidth;
          }
          zOffset += chunkDepth;
        }
      }
    }
  }

  const checks: BlueprintCheckCell[] = pendingChecks.map((entry) => ({
    pos: entry.pos,
    state: entry.state,
    mainPos: entry.mainPos,
    mainStep: stepOfCell.get(key(entry.mainPos[0], entry.mainPos[1], entry.mainPos[2])) ?? -1,
  }));

  return { steps, checks, placeCells, failures, advisories: supports.advisories };
}

/** 局部坐标 + 锚点 → 世界坐标。锚点是蓝图 [0,0,0] 落在世界的哪一格。 */
export function toWorld(anchor: PositionXYZ, local: PositionXYZ): PositionXYZ {
  return [anchor[0] + local[0], anchor[1] + local[1], anchor[2] + local[2]];
}

/** 将 IR 转为 box/solid 的绝对坐标 build 调用；needs 与 expect 由队列补充。 */
interface BlueprintBuildCall {
  skill: 'build';
  shape: 'box';
  fill: 'solid';
  anchors: [Anchor, Anchor];
  material: string;
}

export function stepToBuildCall(step: BlueprintStep, anchor: PositionXYZ): BlueprintBuildCall {
  const from = toWorld(anchor, step.from);
  const to = toWorld(anchor, step.to);
  return {
    skill: 'build',
    shape: 'box',
    fill: 'solid',
    anchors: [[from[0], from[1], from[2]], [to[0], to[1], to[2]]],
    material: step.method.kind === 'use' && step.method.baseItem
      ? step.method.baseItem[0]
      : step.item,
  };
}

// ── 受理管线 ──────────────────────────────────────────────────────────────────

interface BlueprintAcceptance {
  ok: boolean;
  blueprint: NormalizedBlueprint | null;
  plan: BlueprintPlan | null;
  metrics: VoxelMetrics | null;
  repair: RepairReport;
  failures: BlueprintStateFailure[];
}

interface AcceptOptions {
  expectedSize?: SizeXYZ;
}

/**
 * 受理顺序：严格解析、格式修复、默认属性、注册表、体量和施工规则校验、IR 编译。
 * 失败时返回已发现的精确错误路径。
 */
export function acceptBlueprint(
  submission: unknown,
  options: AcceptOptions = {},
): BlueprintAcceptance {
  const repair = createRepairReport();
  const empty = (failures: BlueprintStateFailure[]): BlueprintAcceptance =>
    ({ ok: false, blueprint: null, plan: null, metrics: null, repair, failures });

  const strict = tryNormalizeBlueprint(submission, options);
  repair.strictValid = strict.ok;
  let normalized: NormalizedBlueprint;

  if (strict.ok) {
    normalized = strict.blueprint;
  } else {
    repair.strictError = `${strict.path}: ${strict.reason}`;
    if (typeof submission !== 'object' || submission === null || Array.isArray(submission)) {
      return empty([{ path: strict.path, state: '', reason: strict.reason }]);
    }
    const shaped = repairSubmissionShape(submission as Record<string, unknown>);
    const retry = tryNormalizeBlueprint(shaped.submission, options);
    if (!retry.ok) {
      return empty([{ path: retry.path, state: '', reason: retry.reason }]);
    }
    repair.actions.push(...shaped.actions);
    repair.applied = shaped.actions.length > 0;
    normalized = retry.blueprint;
  }

  const completed = completeBlueprintStateDefaults(normalized);
  if (completed.action !== null) {
    repair.actions.push(completed.action);
    repair.applied = true;
  }
  normalized = completed.blueprint;

  const registryResult = validateBlueprintRegistry(normalized);
  const failures: BlueprintStateFailure[] = [
    ...registryResult.failures,
    ...validateBlueprintLimits(normalized),
  ];
  if (registryResult.valid) {
    failures.push(...validateBlueprintPlaceability(normalized).failures);
  }
  if (failures.length > 0) return empty(failures);

  const plan = compileBlueprint(normalized);
  if (plan.failures.length > 0) return empty(plan.failures);

  return {
    ok: true,
    blueprint: normalized,
    plan,
    metrics: voxelMetrics(normalized),
    repair,
    failures: [],
  };
}

// ── 世界对账 ──────────────────────────────────────────────────────────────────

/** 按世界坐标读取方块；null 表示读数不可用，不计入冲突或完成。 */
export type BlockNameReader = (x: number, y: number, z: number) => string | null;

type ConflictKind = 'wrong-block' | 'should-be-air';

export interface BlueprintConflict {
  /** 世界坐标 */
  pos: PositionXYZ;
  /** 局部坐标 */
  local: PositionXYZ;
  expect: string;
  actual: string;
  kind: ConflictKind;
}

export interface BlueprintDiff {
  /** 要施工的格数(不含从部件)。 */
  total: number;
  /** 已达到机械终态的格数。 */
  matched: number;
  /** 还没到位的格数 */
  missing: number;
  /** 读不到(区块没加载)的格数 */
  unknown: number;
  conflictCounts: Record<ConflictKind, number>;
  /** 冲突样本,按 sampleLimit 截断 */
  conflicts: BlueprintConflict[];
  /** 每一格都已符合的步 */
  doneSteps: number[];
  /** 还没完成的步(不只是游标之后那些) */
  remaining: BlueprintStep[];
  /** 游标 = 从头连着已完成的步数 */
  cursor: number;
}

/** 一格是否达到该施工步的机械终态；功能动作只核对它明确保证的属性。 */
export function blueprintStepStateMatches(step: BlueprintStep, actual: string): boolean {
  const normalized = normalizeBlockName(actual);
  if (blockIdOf(normalized) !== blockIdOf(step.state)) return false;
  const required = step.method.kind === 'place' ? step.method.postUse : step.method.verify;
  if (!required) return true;
  const properties = normalized.includes('[')
    ? new Map(normalized.slice(normalized.indexOf('[') + 1, -1).split(',').map((entry) => {
        const separator = entry.indexOf('=');
        return [entry.slice(0, separator), entry.slice(separator + 1)] as [string, string];
      }))
    : new Map<string, string>();
  return properties.get(required.property) === required.value;
}

interface DiffOptions {
  /** 顺带核对"该是空气的地方现在有没有东西";默认核对 */
  checkAir?: boolean;
  sampleLimit?: number;
}

/** 普通方块按类型核验；功能动作另外核验指定属性。 */
export function diffBlueprint(
  blueprint: NormalizedBlueprint,
  plan: BlueprintPlan,
  anchor: PositionXYZ,
  read: BlockNameReader,
  options: DiffOptions = {},
): BlueprintDiff {
  const { checkAir = true, sampleLimit = 12 } = options;
  const conflicts: BlueprintConflict[] = [];
  const conflictCounts: Record<ConflictKind, number> = { 'wrong-block': 0, 'should-be-air': 0 };
  let matched = 0;
  let missing = 0;
  let unknown = 0;

  const note = (
    local: PositionXYZ,
    pos: PositionXYZ,
    expect: string,
    actual: string,
    kind: ConflictKind,
  ): void => {
    conflictCounts[kind]++;
    if (conflicts.length < sampleLimit) conflicts.push({ pos, local, expect, actual, kind });
  };

  const done = new Set<number>();
  for (const step of plan.steps) {
    const expectId = blockIdOf(step.state);
    // 可转换基材由执行器原地加工，不计清场冲突；豁免集包含全部等价源方块。
    const baseIds = new Set(
      step.method.kind === 'use' && step.method.baseItem
        ? step.method.baseItem.map((n) => `minecraft:${n}`)
        : [],
    );
    let stepDone = true;
    for (let y = step.from[1]; y <= step.to[1]; y++) {
      for (let z = step.from[2]; z <= step.to[2]; z++) {
        for (let x = step.from[0]; x <= step.to[0]; x++) {
          const local: PositionXYZ = [x, y, z];
          const pos = toWorld(anchor, local);
          const raw = read(pos[0], pos[1], pos[2]);
          if (raw === null) { unknown++; stepDone = false; continue; }
          const actual = normalizeBlockName(raw);
          if (blueprintStepStateMatches(step, actual)) { matched++; continue; }
          stepDone = false;
          missing++;
          const actualId = blockIdOf(actual);
          if (actualId !== expectId && !isAirState(actual) && !baseIds.has(actualId)) {
            note(local, pos, expectId, actualId, 'wrong-block');
          }
        }
      }
    }
    if (stepDone) done.add(step.index);
  }

  // 门上半格、床头等从部件不单独消耗物品，但仍是主步骤的终态。
  for (const check of plan.checks) {
    if (!done.has(check.mainStep)) continue;
    const pos = toWorld(anchor, check.pos);
    const raw = read(pos[0], pos[1], pos[2]);
    if (raw === null) {
      unknown++;
      done.delete(check.mainStep);
      continue;
    }
    const actual = normalizeBlockName(raw);
    const expectId = blockIdOf(check.state);
    if (blockIdOf(actual) === expectId) continue;
    done.delete(check.mainStep);
    if (!isAirState(actual)) note(check.pos, pos, expectId, blockIdOf(actual), 'wrong-block');
  }

  if (checkAir) {
    const [sizeX, sizeY, sizeZ] = blueprint.size_xyz;
    for (let y = 0; y < sizeY; y++) {
      for (let z = 0; z < sizeZ; z++) {
        for (let x = 0; x < sizeX; x++) {
          const expected = blueprint.layers[y][z][x];
          if (!isAirState(expected) || isStructureVoidState(expected)) continue;
          const local: PositionXYZ = [x, y, z];
          const pos = toWorld(anchor, local);
          const raw = read(pos[0], pos[1], pos[2]);
          if (raw === null) { unknown++; continue; }
          const actual = normalizeBlockName(raw);
          if (!isAirState(actual)) note(local, pos, 'minecraft:air', actual, 'should-be-air');
        }
      }
    }
  }

  const doneSteps = plan.steps.filter((step) => done.has(step.index)).map((step) => step.index);
  const remaining = plan.steps.filter((step) => !done.has(step.index));
  let cursor = 0;
  while (done.has(cursor)) cursor++;

  return {
    total: plan.placeCells,
    matched,
    missing,
    unknown,
    conflictCounts,
    conflicts,
    doneSteps,
    remaining,
    cursor,
  };
}

// ── 三分账单 ──────────────────────────────────────────────────────────────────

/** 物品名到数量的映射。 */
export type ItemTally = Readonly<Record<string, number>>;

interface BlueprintBillInput {
  /** 随身 */
  carried?: ItemTally;
  /** 容器上次观测的合计数量。 */
  stored?: ItemTally;
}

export interface BlueprintBillLine {
  item: string;
  need: number;
  carried: number;
  stored: number;
  /** 还缺 = need - carried - stored,不为负 */
  missing: number;
}

interface BlueprintBill {
  lines: BlueprintBillLine[];
  totalNeed: number;
  totalMissing: number;
  /** 只用随身的料,从头连着能盖完前几步 */
  reachableSteps: number;
  reachableCells: number;
  /** 把箱里的也取来,从头连着能盖完前几步 */
  reachableStepsWithStored: number;
}

function tallyOf(source: ItemTally | undefined, item: string): number {
  /** 工具族按 _hoe/_shovel 后缀匹配；耗材要求精确物品名。 */
  const family = BLUEPRINT_TOOL_FAMILIES.has(item);
  let total = 0;
  for (const [name, value] of Object.entries(source ?? {})) {
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    if (name !== item && !(family && name.endsWith(`_${item}`))) continue;
    total += Math.max(0, Math.floor(value));
  }
  return total;
}

interface BlueprintRequirement {
  item: string;
  count: number;
  reusable: boolean;
}

/** 一步需要的耗材与工具。可重复使用的工具在整份账里只计一件。 */
function blueprintStepRequirements(step: BlueprintStep): BlueprintRequirement[] {
  if (step.method.kind === 'place') return [{ item: step.item, count: step.cells, reusable: false }];
  return [
    ...(step.method.baseItem
      ? [{ item: step.method.baseItem[0], count: step.cells, reusable: false }]
      : []),
    {
      item: step.method.item,
      count: step.method.reusable ? 1 : step.cells,
      reusable: step.method.reusable === true,
    },
    ...(blueprintNeedsTilledSoil(step.state)
      ? [{ item: 'hoe', count: 1, reusable: true }]
      : []),
  ];
}

/** 手上的料从头连着能盖完前几步(遇到第一步不够就停,不跳步) */
function reachable(
  steps: readonly BlueprintStep[],
  stock: Map<string, number>,
): { steps: number; cells: number } {
  const left = new Map(stock);
  let count = 0;
  let cells = 0;
  for (const step of steps) {
    const requirements = blueprintStepRequirements(step);
    if (requirements.some((need) => (left.get(need.item) ?? 0) < need.count)) break;
    for (const need of requirements) {
      if (!need.reusable) left.set(need.item, (left.get(need.item) ?? 0) - need.count);
    }
    count++;
    cells += step.cells;
  }
  return { steps: count, cells };
}

/** 按剩余步骤顺序扣减材料，统计随身、容器与缺口；材料不足时停止计算可完成步数。 */
export function billForSteps(
  steps: readonly BlueprintStep[],
  input: BlueprintBillInput = {},
): BlueprintBill {
  const need = new Map<string, number>();
  for (const step of steps) {
    for (const requirement of blueprintStepRequirements(step)) {
      const prev = need.get(requirement.item) ?? 0;
      need.set(requirement.item, requirement.reusable
        ? Math.max(prev, requirement.count)
        : prev + requirement.count);
    }
  }

  const lines: BlueprintBillLine[] = [...need].map(([item, count]) => {
    const carried = tallyOf(input.carried, item);
    const stored = tallyOf(input.stored, item);
    return {
      item,
      need: count,
      carried,
      stored,
      missing: Math.max(0, count - carried - stored),
    };
  }).sort((left, right) =>
    right.missing - left.missing || right.need - left.need || left.item.localeCompare(right.item));

  const carriedStock = new Map(lines.map((line) => [line.item, line.carried]));
  const bothStock = new Map(lines.map((line) => [line.item, line.carried + line.stored]));
  const byCarried = reachable(steps, carriedStock);

  return {
    lines,
    totalNeed: lines.reduce((sum, line) => sum + line.need, 0),
    totalMissing: lines.reduce((sum, line) => sum + line.missing, 0),
    reachableSteps: byCarried.steps,
    reachableCells: byCarried.cells,
    reachableStepsWithStored: reachable(steps, bothStock).steps,
  };
}

// ── 进度与按层分段 ────────────────────────────────────────────────────────────

interface BlueprintLayerSpan {
  y: number;
  /** 这一层第一步的步序 */
  firstStep: number;
  /** 这一层结束时的步数(= 最后一步的 index + 1),就是 stopAfter 该停的游标 */
  endStep: number;
  steps: number;
  cells: number;
}

/** 按 y 层分段:每层从第几步到第几步。`stopAfter` 按层停就读 `endStep`。 */
export function layerSpans(steps: readonly BlueprintStep[]): BlueprintLayerSpan[] {
  const spans: BlueprintLayerSpan[] = [];
  for (const step of steps) {
    const last = spans[spans.length - 1];
    if (last !== undefined && last.y === step.y) {
      last.endStep = step.index + 1;
      last.steps++;
      last.cells += step.cells;
      continue;
    }
    spans.push({
      y: step.y,
      firstStep: step.index,
      endStep: step.index + 1,
      steps: 1,
      cells: step.cells,
    });
  }
  return spans;
}

/**
 * 「盖到第 y 层为止」对应走到第几步。该层一步都没有(整层空气)时向下取最近的一层;
 * 比最低层还低就返回 0。
 */
export function stepCountThroughLayer(steps: readonly BlueprintStep[], y: number): number {
  let count = 0;
  for (const step of steps) {
    if (step.y > y) break;
    count = step.index + 1;
  }
  return count;
}

interface BlueprintProgress {
  steps: { done: number; total: number };
  cells: { done: number; total: number };
  /** 正在盖第几层(全盖完是 null),以及这一层的步数进度 */
  layer: { y: number | null; done: number; total: number };
  /** 0..1,两位小数,按格数算 */
  ratio: number;
}

/** 游标 → 进度。游标口径 = 已完成 IR 步数(从头连着的那些)。 */
export function blueprintProgress(
  steps: readonly BlueprintStep[],
  cursor: number,
): BlueprintProgress {
  const total = steps.length;
  const done = Math.max(0, Math.min(total, Math.floor(cursor)));
  const totalCells = steps.reduce((sum, step) => sum + step.cells, 0);
  const doneCells = steps.slice(0, done).reduce((sum, step) => sum + step.cells, 0);

  const current = done < total ? steps[done].y : null;
  const span = current === null
    ? null
    : layerSpans(steps).find((entry) => entry.y === current) ?? null;

  return {
    steps: { done, total },
    cells: { done: doneCells, total: totalCells },
    layer: {
      y: current,
      done: span === null ? 0 : done - span.firstStep,
      total: span?.steps ?? 0,
    },
    ratio: totalCells === 0 ? 1 : Math.round((doneCells / totalCells) * 100) / 100,
  };
}

// ── 回读验收 ──────────────────────────────────────────────────────────────────

/** type 不符判失败；type 相同而 state 漂移单独报告，不判失败。 */
type ReadbackVerdict = 'exact' | 'state-drift' | 'failed';

export function classifyReadback(expected: string, actual: string | null): ReadbackVerdict {
  if (actual === null) return 'failed';
  const actualState = normalizeBlockName(actual);
  if (actualState === expected) return 'exact';
  return blockIdOf(actualState) === blockIdOf(expected) ? 'state-drift' : 'failed';
}

export interface ReadbackEntry {
  pos: PositionXYZ;
  expected: string;
  /** 世界读回来的完整状态串;读不到给 null */
  actual: string | null;
}

interface ReadbackSummary {
  total: number;
  exact: number;
  drift: number;
  failed: number;
  /** 漂了哪些属性:`minecraft:oak_stairs shape` → 次数 */
  driftProperties: Record<string, number>;
  driftSamples: ReadbackEntry[];
  failedSamples: ReadbackEntry[];
}

function driftedProperties(expected: string, actual: string): string[] {
  const props = (state: string): Map<string, string> => {
    const bracket = state.indexOf('[');
    if (bracket === -1) return new Map();
    return new Map(state.slice(bracket + 1, -1).split(',').map((pair) => {
      const separator = pair.indexOf('=');
      return [pair.slice(0, separator), pair.slice(separator + 1)] as [string, string];
    }));
  };
  const left = props(expected);
  const right = props(actual);
  const names = new Set([...left.keys(), ...right.keys()]);
  return [...names].filter((name) => left.get(name) !== right.get(name)).sort();
}

/** 回读汇总;样本按 sampleLimit 截断,drift 顺带统计漂在哪个属性上 */
export function summarizeReadback(
  entries: readonly ReadbackEntry[],
  sampleLimit = 8,
): ReadbackSummary {
  const summary: ReadbackSummary = {
    total: entries.length,
    exact: 0,
    drift: 0,
    failed: 0,
    driftProperties: {},
    driftSamples: [],
    failedSamples: [],
  };

  for (const entry of entries) {
    const verdict = classifyReadback(entry.expected, entry.actual);
    if (verdict === 'exact') { summary.exact++; continue; }
    if (verdict === 'failed') {
      summary.failed++;
      if (summary.failedSamples.length < sampleLimit) summary.failedSamples.push(entry);
      continue;
    }
    summary.drift++;
    if (summary.driftSamples.length < sampleLimit) summary.driftSamples.push(entry);
    for (const name of driftedProperties(entry.expected, normalizeBlockName(entry.actual ?? ''))) {
      const label = `${blockIdOf(entry.expected)} ${name}`;
      summary.driftProperties[label] = (summary.driftProperties[label] ?? 0) + 1;
    }
  }
  return summary;
}
