import { diffBlueprint } from './blueprint-plan.ts';
import { CHECK_BOX_CELL_CAP, evalAssert, type CheckResult, type CheckWorld, type CheckVerdict } from './check.ts';
import type { PositionXYZ } from './blueprint.ts';

const GOAL_PLAN_MAX_STEPS = 12;
const GOAL_PLAN_MAX_PROBES_PER_STEP = 8;
const GOAL_PLAN_MAX_PROBES = 24;

type GoalCompare = { op: '=' | '>=' | '<='; n: number };
type Region = { min: PositionXYZ; max: PositionXYZ; dimension: string };

type GoalProbe =
  | { source: 'block'; at: PositionXYZ; is: string }
  | { source: 'inventory'; item: string; count: GoalCompare }
  | { source: 'blueprint'; key: string; loaded: boolean | null; matched: GoalCompare | null }
  | { source: 'position'; region: Region }
  | { source: 'entity'; type: string; region: Region; count: GoalCompare }
  | { source: 'item'; item: string; region: Region; count: GoalCompare }
  | {
      source: 'status';
      field: 'health' | 'food' | 'oxygen' | 'burning';
      equals: boolean | GoalCompare;
    };

interface GoalEvidence {
  observedAt: number;
  connectionGeneration: number;
  realm: string;
  dimension: string;
  verdict: CheckVerdict;
  results: CheckResult[];
}

interface GoalJudgmentEvidence {
  judgedAt: number;
  note: string;
}

interface GoalPlanStep {
  do: string;
  verify: GoalProbe[] | null;
  judgment: string | null;
  state: 'pending' | 'verified' | 'judged';
  evidence: GoalEvidence | GoalJudgmentEvidence | null;
  completedAt: number | null;
}

export interface GoalPlan {
  steps: GoalPlanStep[];
  readyAnnounced: boolean;
}

export interface GoalEntityReading {
  type: string;
  position: PositionXYZ;
}

export interface GoalItemReading {
  item: string;
  count: number;
  position: PositionXYZ;
}

/** Current read facade. Every function is evaluated from the live Mineflayer state. */
export interface GoalProbeContext {
  observedAt: number;
  connectionGeneration: number;
  realm: string;
  dimension: string;
  world: CheckWorld;
  position(): readonly [number, number, number];
  status(): Readonly<{
    health: number;
    food: number;
    oxygen: number;
    burning: boolean;
  }>;
  entities(): readonly GoalEntityReading[];
  items(): readonly GoalItemReading[];
}

type GoalPlanTransition =
  | { kind: 'advance'; from: number; to: number; total: number; next: string | null; evidence: string[] }
  | { kind: 'regress'; from: number; to: number; total: number; step: number; evidence: string[] }
  | { kind: 'ready'; total: number };

interface GoalPlanCoordination {
  transitions: GoalPlanTransition[];
  completed: number;
  total: number;
  next: GoalPlanStep | null;
  ready: boolean;
  blocker: GoalEvidence | null;
}

const VEC3_SCHEMA = {
  type: 'array',
  minItems: 3,
  maxItems: 3,
  items: { type: 'integer' },
};

const REGION_SCHEMA = {
  type: 'array',
  minItems: 2,
  maxItems: 2,
  items: VEC3_SCHEMA,
  description: '两个角 [[x1,y1,z1],[x2,y2,z2]]；必须同时给 dimension。',
};

const COMPARE_SCHEMA = {
  type: ['number', 'string'],
  description: '非负数表示恰好；也可写 ">=8" / "<=2"。',
};

/** Flat fields stay visible to tool decoders that discard fields nested under oneOf. */
const GOAL_PROBE_SCHEMA = {
  type: 'object',
  description: '机械旁证。source 决定字段：block(at,is)；inventory(item,count)；blueprint(key,loaded?/matched?)；position(region,dimension)；entity(type,region,dimension,count)；item(item,region,dimension,count)；status(field,equals)。',
  properties: {
    source: {
      type: 'string',
      enum: ['block', 'inventory', 'blueprint', 'position', 'entity', 'item', 'status'],
    },
    at: VEC3_SCHEMA,
    is: { type: 'string', description: 'block 的精确方块 id。' },
    item: { type: 'string', description: 'inventory/item 的精确物品 id。' },
    type: { type: 'string', description: 'entity 的精确实体 id。' },
    count: COMPARE_SCHEMA,
    key: { type: 'string', description: 'blueprint 的蓝图键。' },
    loaded: { type: 'boolean', description: 'blueprint 是否已装载。' },
    matched: COMPARE_SCHEMA,
    region: REGION_SCHEMA,
    dimension: { type: 'string', description: 'region 所在维度，如 minecraft:overworld。' },
    field: { type: 'string', enum: ['health', 'food', 'oxygen', 'burning'] },
    equals: {
      type: ['number', 'string', 'boolean'],
      description: 'status 的目标值；数值状态也可写 ">=8" / "<=2"。',
    },
  },
  required: ['source'],
};

export const GOAL_PLAN_SCHEMA = {
  type: 'array',
  minItems: 1,
  maxItems: GOAL_PLAN_MAX_STEPS,
  description: '按执行顺序列里程碑。每步恰好给 verify 或 judgment；verify 数组按 AND 求值。',
  items: {
    type: 'object',
    properties: {
      do: { type: 'string', description: '这一步要实施什么。' },
      verify: {
        type: ['object', 'array'],
        description: '一个机械旁证，或最多 8 个旁证组成的 AND 数组。',
        properties: GOAL_PROBE_SCHEMA.properties,
        required: ['source'],
        items: GOAL_PROBE_SCHEMA,
        minItems: 1,
        maxItems: GOAL_PLAN_MAX_PROBES_PER_STEP,
      },
      judgment: {
        type: 'string',
        description: '说明为什么这一步只能由你现场判断；完成时再用 milestone 提交判断说明。',
      },
    },
    required: ['do'],
  },
};

function objectOf(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function unknownFields(body: Record<string, unknown>, allowed: readonly string[]): string[] {
  const keep = new Set(allowed);
  return Object.keys(body).filter((key) => !keep.has(key));
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null;
}

function exactId(value: unknown): string | null {
  const raw = text(value);
  return raw?.toLowerCase().replace(/^minecraft:/, '') ?? null;
}

function parsePos(value: unknown, path: string): PositionXYZ | { error: string } {
  if (!Array.isArray(value) || value.length !== 3) return { error: `${path} 要 [x,y,z] 三个整数` };
  if (value.some((part) => typeof part !== 'number' || !Number.isFinite(part))) {
    return { error: `${path} 要 [x,y,z] 三个整数` };
  }
  return value.map((part) => Math.floor(part as number)) as PositionXYZ;
}

function parseCompare(value: unknown, path: string): GoalCompare | { error: string } {
  if (typeof value === 'number' && Number.isFinite(value) && value >= 0) return { op: '=', n: value };
  if (typeof value === 'string') {
    const found = /^\s*(>=|<=|=)?\s*(\d+(?:\.\d+)?)\s*$/.exec(value);
    if (found) return { op: (found[1] ?? '=') as GoalCompare['op'], n: Number(found[2]) };
  }
  return { error: `${path} 要非负数或 ">=8" / "<=2"` };
}

function parseRegion(body: Record<string, unknown>, path: string): Region | { error: string } {
  if (!Array.isArray(body.region) || body.region.length !== 2) {
    return { error: `${path}.region 要 [[x1,y1,z1],[x2,y2,z2]]` };
  }
  const a = parsePos(body.region[0], `${path}.region[0]`);
  if ('error' in a) return a;
  const b = parsePos(body.region[1], `${path}.region[1]`);
  if ('error' in b) return b;
  const dimension = text(body.dimension);
  if (!dimension) return { error: `${path}.dimension 要明确写维度` };
  const min: PositionXYZ = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.min(a[2], b[2])];
  const max: PositionXYZ = [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.max(a[2], b[2])];
  const dx = max[0] - min[0] + 1;
  const dy = max[1] - min[1] + 1;
  const dz = max[2] - min[2] + 1;
  const cells = dx * dy * dz;
  if (cells > CHECK_BOX_CELL_CAP) {
    // 将体积上限换算成边长，并报告本次三条边长，供调用方缩小范围。
    const edge = Math.floor(Math.cbrt(CHECK_BOX_CELL_CAP));
    return {
      error: `${path}.region 共 ${cells} 格，超过一次能核的 ${CHECK_BOX_CELL_CAP} 格`
        + `(${CHECK_BOX_CELL_CAP} 格 ≈ ${edge}×${edge}×${edge};你这次是 ${dx}×${dy}×${dz})`,
    };
  }
  return { min, max, dimension };
}

function parseProbe(value: unknown, path: string): GoalProbe | { error: string } {
  const body = objectOf(value);
  if (!body) return { error: `${path} 要一个旁证对象` };
  const source = body.source;
  if (typeof source !== 'string') return { error: `${path}.source 要一个来源名` };
  const allowedBySource: Record<string, readonly string[]> = {
    block: ['source', 'at', 'is'],
    inventory: ['source', 'item', 'count'],
    blueprint: ['source', 'key', 'loaded', 'matched'],
    position: ['source', 'region', 'dimension'],
    entity: ['source', 'type', 'region', 'dimension', 'count'],
    item: ['source', 'item', 'region', 'dimension', 'count'],
    status: ['source', 'field', 'equals'],
  };
  const allowed = allowedBySource[source];
  if (!allowed) return { error: `${path}.source 不认识「${source}」` };
  const extras = unknownFields(body, allowed);
  if (extras.length > 0) return { error: `${path} 有不属于 ${source} 的字段: ${extras.join(', ')}` };

  if (source === 'block') {
    const at = parsePos(body.at, `${path}.at`);
    if ('error' in at) return at;
    const is = exactId(body.is);
    return is ? { source, at, is } : { error: `${path}.is 要精确方块 id` };
  }
  if (source === 'inventory') {
    const item = exactId(body.item);
    if (!item) return { error: `${path}.item 要精确物品 id` };
    const count = parseCompare(body.count, `${path}.count`);
    return 'error' in count ? count : { source, item, count };
  }
  if (source === 'blueprint') {
    const key = text(body.key);
    if (!key) return { error: `${path}.key 要蓝图键` };
    if (body.loaded !== undefined && typeof body.loaded !== 'boolean') {
      return { error: `${path}.loaded 只收 true/false` };
    }
    const matched = body.matched === undefined ? null : parseCompare(body.matched, `${path}.matched`);
    if (matched && 'error' in matched) return matched;
    const loaded = typeof body.loaded === 'boolean' ? body.loaded : null;
    if (loaded === null && matched === null) return { error: `${path} 至少给 loaded 或 matched` };
    if (loaded === false && matched !== null) return { error: `${path} 不能同时要求 loaded=false 和 matched` };
    return { source, key, loaded, matched };
  }
  if (source === 'position') {
    const region = parseRegion(body, path);
    return 'error' in region ? region : { source, region };
  }
  if (source === 'entity') {
    const type = exactId(body.type);
    if (!type) return { error: `${path}.type 要精确实体 id` };
    const region = parseRegion(body, path);
    if ('error' in region) return region;
    const count = parseCompare(body.count, `${path}.count`);
    return 'error' in count ? count : { source, type, region, count };
  }
  if (source === 'item') {
    const item = exactId(body.item);
    if (!item) return { error: `${path}.item 要精确物品 id` };
    const region = parseRegion(body, path);
    if ('error' in region) return region;
    const count = parseCompare(body.count, `${path}.count`);
    return 'error' in count ? count : { source, item, region, count };
  }
  const field = body.field;
  if (!['health', 'food', 'oxygen', 'burning'].includes(String(field))) {
    return { error: `${path}.field 只收 health/food/oxygen/burning` };
  }
  if (field === 'burning') {
    return typeof body.equals === 'boolean'
      ? { source: 'status', field, equals: body.equals }
      : { error: `${path}.equals 对 burning 只收 true/false` };
  }
  const equals = parseCompare(body.equals, `${path}.equals`);
  return 'error' in equals
    ? equals
    : { source: 'status', field: field as 'health' | 'food' | 'oxygen', equals };
}

export function parseGoalPlan(value: unknown): GoalPlan | { error: string } {
  if (!Array.isArray(value) || value.length === 0) return { error: 'add.plan 至少要一步' };
  if (value.length > GOAL_PLAN_MAX_STEPS) {
    return { error: `add.plan 一次最多 ${GOAL_PLAN_MAX_STEPS} 步` };
  }
  const steps: GoalPlanStep[] = [];
  let probeCount = 0;
  for (const [index, raw] of value.entries()) {
    const path = `add.plan[${index}]`;
    const body = objectOf(raw);
    if (!body) return { error: `${path} 要一个对象` };
    const extras = unknownFields(body, ['do', 'verify', 'judgment']);
    if (extras.length > 0) return { error: `${path} 有未知字段: ${extras.join(', ')}` };
    const action = text(body.do);
    if (!action) return { error: `${path}.do 不能空` };
    const hasVerify = body.verify !== undefined;
    const hasJudgment = body.judgment !== undefined;
    if (hasVerify === hasJudgment) return { error: `${path} 要恰好给 verify 或 judgment` };
    if (hasJudgment) {
      const judgment = text(body.judgment);
      if (!judgment) return { error: `${path}.judgment 不能空` };
      steps.push({ do: action, verify: null, judgment, state: 'pending', evidence: null, completedAt: null });
      continue;
    }
    const rawProbes = Array.isArray(body.verify) ? body.verify : [body.verify];
    if (rawProbes.length === 0 || rawProbes.length > GOAL_PLAN_MAX_PROBES_PER_STEP) {
      return { error: `${path}.verify 要 1..${GOAL_PLAN_MAX_PROBES_PER_STEP} 个旁证` };
    }
    probeCount += rawProbes.length;
    if (probeCount > GOAL_PLAN_MAX_PROBES) {
      return { error: `add.plan 一共最多 ${GOAL_PLAN_MAX_PROBES} 个旁证` };
    }
    const probes: GoalProbe[] = [];
    for (const [probeIndex, rawProbe] of rawProbes.entries()) {
      const parsed = parseProbe(rawProbe, `${path}.verify[${probeIndex}]`);
      if ('error' in parsed) return parsed;
      probes.push(parsed);
    }
    steps.push({ do: action, verify: probes, judgment: null, state: 'pending', evidence: null, completedAt: null });
  }
  return { steps, readyAnnounced: false };
}

function compare(actual: number, wanted: GoalCompare): boolean {
  return wanted.op === '=' ? actual === wanted.n : wanted.op === '>=' ? actual >= wanted.n : actual <= wanted.n;
}

function compareText(wanted: GoalCompare): string {
  return `${wanted.op}${wanted.n}`;
}

function intervalVerdict(min: number, max: number, wanted: GoalCompare): CheckVerdict {
  if (wanted.op === '=') {
    if (wanted.n < min || wanted.n > max) return 'bad';
    return min === max && min === wanted.n ? 'ok' : 'unknown';
  }
  if (wanted.op === '>=') return min >= wanted.n ? 'ok' : max < wanted.n ? 'bad' : 'unknown';
  return max <= wanted.n ? 'ok' : min > wanted.n ? 'bad' : 'unknown';
}

function inRegion(position: readonly [number, number, number], region: Region): boolean {
  return position.every((part, axis) => part >= region.min[axis] && part <= region.max[axis]);
}

function regionObservable(region: Region, world: CheckWorld): boolean {
  const y = Math.floor((region.min[1] + region.max[1]) / 2);
  const xs = new Set<number>([region.min[0], region.max[0]]);
  const zs = new Set<number>([region.min[2], region.max[2]]);
  for (let x = region.min[0]; x <= region.max[0]; x += 16) xs.add(x);
  for (let z = region.min[2]; z <= region.max[2]; z += 16) zs.add(z);
  for (const x of xs) for (const z of zs) if (world.cell(x, y, z) === null) return false;
  return true;
}

function evidenceResult(verdict: CheckVerdict, text: string): CheckResult {
  return { verdict, text };
}

function evaluateProbe(probe: GoalProbe, ctx: GoalProbeContext): CheckResult {
  if (probe.source === 'block') return evalAssert({ kind: 'at', at: probe.at, is: probe.is }, ctx.world);
  if (probe.source === 'inventory') {
    return evalAssert({ kind: 'inv', want: [{ item: probe.item, ...probe.count }] }, ctx.world);
  }
  if (probe.source === 'blueprint') {
    const site = ctx.world.site(probe.key);
    if (probe.loaded !== null && Boolean(site) !== probe.loaded) {
      return evidenceResult('bad', `蓝图「${probe.key}」loaded=${Boolean(site)}，要 ${probe.loaded}`);
    }
    if (!probe.matched) return evidenceResult('ok', `蓝图「${probe.key}」loaded=${Boolean(site)}`);
    if (!site) return evidenceResult('error', `蓝图「${probe.key}」没装载，读不到 matched`);
    if (!site.anchor) return evidenceResult('error', `蓝图「${probe.key}」还没绑工地锚点`);
    const diff = diffBlueprint(
      site.blueprint,
      site.plan,
      site.anchor,
      (x, y, z) => ctx.world.cell(x, y, z)?.state ?? null,
      { checkAir: true },
    );
    const verdict = intervalVerdict(diff.matched, diff.matched + diff.unknown, probe.matched);
    return evidenceResult(
      verdict,
      `蓝图「${probe.key}」现场对上 ${diff.matched}/${diff.total} 格，${diff.unknown} 格没加载（要 ${compareText(probe.matched)}）`,
    );
  }
  if (probe.source === 'position') {
    if (probe.region.dimension !== ctx.dimension) {
      return evidenceResult('unknown', `人在 ${ctx.dimension}，里程碑区域在 ${probe.region.dimension}`);
    }
    const position = ctx.position();
    const hit = inRegion(position, probe.region);
    return evidenceResult(hit ? 'ok' : 'bad', `位置 (${position.map((n) => Math.round(n)).join(', ')}) ${hit ? '在' : '不在'}指定区域`);
  }
  if (probe.source === 'status') {
    const actual = ctx.status()[probe.field];
    const hit = typeof probe.equals === 'boolean'
      ? actual === probe.equals
      : typeof actual === 'number' && compare(actual, probe.equals);
    return evidenceResult(hit ? 'ok' : 'bad', `${probe.field}=${String(actual)}（要 ${typeof probe.equals === 'boolean' ? String(probe.equals) : compareText(probe.equals)}）`);
  }
  const region = probe.region;
  if (region.dimension !== ctx.dimension) {
    return evidenceResult('unknown', `当前在 ${ctx.dimension}，计数区域在 ${region.dimension}`);
  }
  if (!regionObservable(region, ctx.world)) {
    return evidenceResult('unknown', '计数区域没有完整加载，当前实体表不能证明这里的总数');
  }
  if (probe.source === 'entity') {
    const actual = ctx.entities().filter((entity) => entity.type === probe.type && inRegion(entity.position, region)).length;
    return evidenceResult(compare(actual, probe.count) ? 'ok' : 'bad', `区域内 ${probe.type}=${actual}（要 ${compareText(probe.count)}）`);
  }
  const actual = ctx.items()
    .filter((item) => item.item === probe.item && inRegion(item.position, region))
    .reduce((sum, item) => sum + item.count, 0);
  return evidenceResult(compare(actual, probe.count) ? 'ok' : 'bad', `区域内掉落 ${probe.item}=${actual}（要 ${compareText(probe.count)}）`);
}

function evaluateGoalStep(step: GoalPlanStep, ctx: GoalProbeContext): GoalEvidence {
  const results = step.verify?.map((probe) => evaluateProbe(probe, ctx)) ?? [];
  const verdict: CheckVerdict = results.some((result) => result.verdict === 'error') ? 'error'
    : results.some((result) => result.verdict === 'bad') ? 'bad'
      : results.some((result) => result.verdict === 'unknown') ? 'unknown'
        : 'ok';
  return {
    observedAt: ctx.observedAt,
    connectionGeneration: ctx.connectionGeneration,
    realm: ctx.realm,
    dimension: ctx.dimension,
    verdict,
    results,
  };
}

export function completedGoalSteps(plan: GoalPlan): number {
  const first = plan.steps.findIndex((step) => step.state === 'pending');
  return first < 0 ? plan.steps.length : first;
}

export function goalPlanSummary(plan: GoalPlan): { completed: number; total: number; next: GoalPlanStep | null } {
  const completed = completedGoalSteps(plan);
  return { completed, total: plan.steps.length, next: plan.steps[completed] ?? null };
}

function latestMechanicalFrontier(plan: GoalPlan): number | null {
  const completed = completedGoalSteps(plan);
  const index = completed - 1;
  return index >= 0 && plan.steps[index].verify ? index : null;
}

function evidenceText(evidence: GoalEvidence): string[] {
  return evidence.results.map((result) => result.text);
}

export function coordinateGoalPlan(plan: GoalPlan, ctx: GoalProbeContext): GoalPlanCoordination {
  const transitions: GoalPlanTransition[] = [];
  const before = completedGoalSteps(plan);
  const sampled = new Map<number, GoalEvidence>();
  let cursor = before;
  while (cursor < plan.steps.length) {
    const step = plan.steps[cursor];
    if (!step.verify) break;
    const evidence = evaluateGoalStep(step, ctx);
    sampled.set(cursor, evidence);
    step.evidence = evidence;
    if (evidence.verdict !== 'ok') break;
    step.state = 'verified';
    step.completedAt = ctx.observedAt;
    cursor++;
  }
  const advanced = completedGoalSteps(plan);
  if (advanced > before) {
    const evidence: string[] = [];
    for (let index = before; index < advanced; index++) {
      const sampledEvidence = sampled.get(index);
      if (sampledEvidence) evidence.push(...evidenceText(sampledEvidence));
    }
    transitions.push({
      kind: 'advance', from: before, to: advanced, total: plan.steps.length,
      next: plan.steps[advanced]?.do ?? null, evidence,
    });
  }

  let blocker: GoalEvidence | null = null;
  const frontier = latestMechanicalFrontier(plan);
  if (frontier !== null) {
    const step = plan.steps[frontier];
    const evidence = sampled.get(frontier) ?? evaluateGoalStep(step, ctx);
    step.evidence = evidence;
    if (evidence.verdict === 'bad') {
      const from = completedGoalSteps(plan);
      step.state = 'pending';
      step.completedAt = null;
      for (let index = frontier + 1; index < plan.steps.length; index++) {
        if (plan.steps[index].state === 'verified') {
          plan.steps[index].state = 'pending';
          plan.steps[index].completedAt = null;
        }
      }
      const to = completedGoalSteps(plan);
      plan.readyAnnounced = false;
      transitions.push({
        kind: 'regress', from, to, total: plan.steps.length, step: frontier + 1,
        evidence: evidenceText(evidence),
      });
    } else if (evidence.verdict === 'unknown' || evidence.verdict === 'error') {
      blocker = evidence;
    }
  }

  const summary = goalPlanSummary(plan);
  const ready = summary.completed === summary.total && blocker === null;
  if (!ready) plan.readyAnnounced = false;
  if (ready && !plan.readyAnnounced) {
    plan.readyAnnounced = true;
    transitions.push({ kind: 'ready', total: summary.total });
  }
  return { transitions, ...summary, ready, blocker };
}

/** 一句话说清这一步登记的机械旁证要什么。只复述登记内容,不加判断。 */
function describeProbes(probes: GoalProbe[] | null): string {
  if (!probes || probes.length === 0) return '没有登记旁证';
  return probes.map((p) => {
    switch (p.source) {
      case 'block': return `${p.at.join(',')} 那一格是 ${p.is}`;
      case 'inventory': return `包里 ${p.item} ${compareText(p.count)}`;
      case 'blueprint': return `蓝图 ${p.key}`;
      case 'position': return '人在指定区域里';
      case 'entity': return `区域内 ${p.type} ${compareText(p.count)}`;
      case 'item': return `区域内掉落物 ${p.item} ${compareText(p.count)}`;
      default: return `状态 ${p.field}`;
    }
  }).join('、');
}

export function recordGoalJudgment(
  plan: GoalPlan,
  stepNumber: number,
  note: string,
  at: number,
): { ok: true; completed: number; total: number; next: GoalPlanStep | null } | { ok: false; error: string } {
  const index = stepNumber - 1;
  const step = plan.steps[index];
  if (!step) return { ok: false, error: `没有第 ${stepNumber} 个里程碑` };
  if (!step.judgment) {
    // 回执说明已登记的目标类型及其自动验收方式。
    const what = describeProbes(step.verify);
    const nextJudgment = plan.steps.findIndex((s, i) => i >= index && s.judgment !== null);
    return {
      ok: false,
      error: `第 ${stepNumber} 步登记的是机械核验(${what})，它会自己判定，不用也不能用判断代填`
        + (nextJudgment >= 0 ? `；能登记判断的是第 ${nextJudgment + 1} 步` : '；这条目标里没有判断型里程碑'),
    };
  }
  const trimmed = note.trim();
  if (!trimmed) return { ok: false, error: 'judgment 说明不能空' };
  const completed = completedGoalSteps(plan);
  if (completed !== index) {
    const blocker = plan.steps[completed];
    return {
      ok: false,
      error: `当前应处理第 ${completed + 1} 步，不能越过前面的里程碑`
        + (blocker ? `；第 ${completed + 1} 步是「${blocker.do}」`
          + `(${blocker.judgment ? '判断型，登记它就过' : `机械核验:${describeProbes(blocker.verify)}`})` : ''),
    };
  }
  step.state = 'judged';
  step.evidence = { judgedAt: at, note: trimmed };
  step.completedAt = at;
  plan.readyAnnounced = false;
  return { ok: true, ...goalPlanSummary(plan) };
}

export function reopenGoalJudgment(
  plan: GoalPlan,
  stepNumber: number,
): { ok: true; completed: number; total: number; next: GoalPlanStep | null } | { ok: false; error: string } {
  const step = plan.steps[stepNumber - 1];
  if (!step) return { ok: false, error: `没有第 ${stepNumber} 个里程碑` };
  if (!step.judgment) return { ok: false, error: `第 ${stepNumber} 步不是判断里程碑` };
  if (step.state !== 'judged') return { ok: false, error: `第 ${stepNumber} 步还没有判断记录` };
  step.state = 'pending';
  step.evidence = null;
  step.completedAt = null;
  plan.readyAnnounced = false;
  return { ok: true, ...goalPlanSummary(plan) };
}

export function goalPlanDoneIssue(plan: GoalPlan): string | null {
  const summary = goalPlanSummary(plan);
  if (summary.completed < summary.total) {
    return `只有 ${summary.completed}/${summary.total} 项里程碑完成；下一步 #${summary.completed + 1} ${summary.next?.do}`;
  }
  const frontier = latestMechanicalFrontier(plan);
  if (frontier !== null) {
    const evidence = plan.steps[frontier].evidence;
    if (!evidence || !('verdict' in evidence) || evidence.verdict !== 'ok') {
      const detail = evidence && 'results' in evidence ? evidence.results.map((result) => result.text).join('；') : '没有新鲜旁证';
      return `最后一项机械旁证还不能结案：${detail}`;
    }
  }
  return null;
}

export function renderGoalPlanTransition(transition: GoalPlanTransition): string {
  if (transition.kind === 'advance') {
    const evidence = transition.evidence.length > 0 ? `：${transition.evidence.join('；')}` : '';
    const next = transition.next ? `；下一步 ${transition.next}` : '';
    return `机械旁证推进到 ${transition.to}/${transition.total}${evidence}${next}`;
  }
  if (transition.kind === 'regress') {
    return `第 ${transition.step}/${transition.total} 项旁证已失效：${transition.evidence.join('；')}；进度退回 ${transition.to}/${transition.total}`;
  }
  return `${transition.total} 项里程碑都有旁证，可以用 mc_goal done 明确结案`;
}
