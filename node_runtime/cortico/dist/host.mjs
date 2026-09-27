// src/host.ts
import process2 from "node:process";
import { createInterface } from "node:readline";
import { randomUUID } from "node:crypto";

// ../../vendor/cortico/src/protocol/open-responses/generated.ts
var STREAM_EVENT_TYPES = /* @__PURE__ */ new Set(["response.created", "response.queued", "response.in_progress", "response.completed", "response.failed", "response.incomplete", "response.output_item.added", "response.output_item.done", "response.reasoning_summary_part.added", "response.reasoning_summary_part.done", "response.content_part.added", "response.content_part.done", "response.output_text.delta", "response.output_text.done", "response.refusal.delta", "response.refusal.done", "response.reasoning.delta", "response.reasoning.done", "response.reasoning_summary_text.delta", "response.reasoning_summary_text.done", "response.output_text.annotation.added", "response.function_call_arguments.delta", "response.function_call_arguments.done", "error"]);

// ../../vendor/cortico/src/protocol/open-responses/index.ts
function createResponse(id, request, now = Date.now()) {
  return {
    id,
    object: "response",
    created_at: Math.floor(now / 1e3),
    completed_at: null,
    status: "in_progress",
    incomplete_details: null,
    model: request.model ?? "",
    previous_response_id: request.previous_response_id ?? null,
    instructions: request.instructions ?? null,
    output: [],
    error: null,
    tools: request.tools ?? [],
    tool_choice: request.tool_choice ?? "auto",
    truncation: request.truncation ?? "disabled",
    parallel_tool_calls: request.parallel_tool_calls ?? false,
    text: request.text ?? { format: { type: "text" } },
    top_p: request.top_p ?? 1,
    presence_penalty: request.presence_penalty ?? 0,
    frequency_penalty: request.frequency_penalty ?? 0,
    top_logprobs: request.top_logprobs ?? 0,
    temperature: request.temperature ?? 1,
    reasoning: request.reasoning ? { effort: request.reasoning.effort ?? null, summary: request.reasoning.summary ?? null } : null,
    usage: null,
    max_output_tokens: request.max_output_tokens ?? null,
    max_tool_calls: request.max_tool_calls ?? null,
    store: request.store ?? false,
    background: request.background ?? false,
    service_tier: request.service_tier ?? "default",
    metadata: request.metadata ?? null,
    safety_identifier: request.safety_identifier ?? null,
    prompt_cache_key: request.prompt_cache_key ?? null
  };
}

// ../../vendor/cortico/src/protocol/open-responses/context.ts
function record(item, context = {}) {
  return { version: 2, item, context };
}
function message(role, text2, context = {}) {
  return record({
    type: "message",
    id: `msg_${crypto.randomUUID()}`,
    status: "completed",
    role,
    content: role === "assistant" ? [{ type: "output_text", text: text2, annotations: [] }] : [{ type: "input_text", text: text2 }]
  }, context);
}
function functionCall(callId, name, args, context = {}) {
  return record({ type: "function_call", id: `fc_${crypto.randomUUID()}`, call_id: callId, name, arguments: args, status: "completed" }, context);
}
function functionResult(callId, text2, context = {}) {
  return record({ type: "function_call_output", id: `fco_${crypto.randomUUID()}`, call_id: callId, status: "completed", output: text2 }, context);
}
function partsText(content) {
  if (typeof content === "string") return content;
  return (content ?? []).map((part) => {
    const p = part;
    return p.text ?? p.refusal ?? "";
  }).join("");
}
function itemText(item) {
  if (item.type === "message") return partsText(item.content);
  if (item.type === "function_call_output") return partsText(item.output);
  if (item.type === "reasoning") return partsText(item.content) || partsText(item.summary);
  return "";
}
function withText(entry, text2) {
  const item = entry.item;
  if (item.type === "function_call_output") return { ...entry, item: { ...item, output: text2 } };
  if (item.type !== "message") throw new Error(`Cannot replace text on ${item.type}`);
  return { ...entry, item: { ...item, content: text2 } };
}
function responseRecords(response, origin, context = {}) {
  return response.output.map((item) => record(structuredClone(item), {
    ...context,
    responseId: response.id,
    responseStatus: response.status,
    origin
  }));
}
function inputItem(entry) {
  const item = entry.item;
  if (item.type === "reasoning") {
    const reasoning = {
      type: "reasoning",
      summary: item.summary.filter((part) => part.type === "summary_text")
    };
    if (item.id) reasoning.id = item.id;
    if (item.encrypted_content) reasoning.encrypted_content = item.encrypted_content;
    return reasoning;
  }
  return structuredClone(item);
}

// ../../vendor/cortico/src/core/core.ts
import { existsSync as existsSync13, mkdirSync as mkdirSync11 } from "node:fs";
import { join as join10 } from "node:path";

// ../../vendor/cortico/src/core/util.ts
import { createHash } from "node:crypto";
import { appendFileSync, mkdirSync, existsSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

// ../../vendor/cortico/src/core/types.ts
var LOG_LEVEL_RANK = { trace: 0, debug: 1, info: 2, warn: 3, error: 4 };

// ../../vendor/cortico/src/core/log-context.ts
import { AsyncLocalStorage } from "node:async_hooks";
var storage = new AsyncLocalStorage();
function withAnchors(anchors, fn) {
  return storage.run({ ...storage.getStore(), ...anchors }, fn);
}
function setAnchors(patch) {
  const current = storage.getStore();
  if (!current) return;
  for (const [key, value] of Object.entries(patch)) {
    if (value === void 0) delete current[key];
    else current[key] = value;
  }
}
function currentAnchors() {
  return storage.getStore() ?? {};
}

// ../../vendor/cortico/src/protocol/open-responses/tokens.ts
function estimateTokens(text2) {
  let cjk = 0;
  let other = 0;
  for (const ch of text2) {
    const code = ch.codePointAt(0);
    if (code >= 19968 && code <= 40959 || code >= 12288 && code <= 12543 || code >= 65280 && code <= 65519)
      cjk++;
    else other++;
  }
  return Math.ceil(cjk * 0.6 + other * 0.3);
}
function estimateMessagesTokens(messages) {
  return messages.reduce(
    (total, { item }) => total + 8 + estimateTokens(item.type === "function_call" ? item.name + item.arguments : itemText(item)) + (item.type === "reasoning" && item.encrypted_content ? estimateTokens(item.encrypted_content) : 0),
    0
  );
}

// ../../vendor/cortico/src/core/util.ts
function prefixFingerprint(messages, count = PREFIX_FINGERPRINT_MESSAGES) {
  const parts = messages.slice(0, count).map(({ item }) => {
    const { id: _id, ...wire } = item;
    return JSON.stringify(wire);
  });
  return createHash("sha256").update(parts.join("\0"), "utf8").digest("hex").slice(0, 12);
}
var PREFIX_FINGERPRINT_MESSAGES = 8;
function withDeadline(work, ms, what = "\u8FD9\u4E00\u6B65") {
  return new Promise((resolve2, reject) => {
    const timer = setTimeout(() => reject(new Error(`${what}\u8D85\u65F6(${Math.round(ms / 1e3)}\u79D2)`)), ms);
    work.then(
      (v) => {
        clearTimeout(timer);
        resolve2(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      }
    );
  });
}
function nowIso(timezone, d = /* @__PURE__ */ new Date()) {
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  });
  const parts = `${fmt.format(d).replace(" ", "T")}.${String(d.getMilliseconds()).padStart(3, "0")}`;
  const offMin = -getTimezoneOffsetMinutes(timezone, d);
  const sign = offMin >= 0 ? "+" : "-";
  const abs = Math.abs(offMin);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${parts}${sign}${hh}:${mm}`;
}
function getTimezoneOffsetMinutes(timezone, d) {
  const utc = new Date(d.toLocaleString("en-US", { timeZone: "UTC" }));
  const loc = new Date(d.toLocaleString("en-US", { timeZone: timezone }));
  return (utc.getTime() - loc.getTime()) / 6e4;
}
function renderEventLines(events) {
  return events.map((e) => e.text).join("\n");
}
var FOLD_MS = 3e4;
var INCIDENT_GAP_MS = 6e4;
var RING_SIZE = 300;
var ROTATE_BYTES = 64 * 1024 * 1024;
var DEFAULT_LEVELS = { file: "debug", console: "info", areas: "" };
function normalizeError(value) {
  if (value instanceof Error) {
    return { name: value.name, message: value.message, ...value.stack ? { stack: value.stack } : {} };
  }
  if (typeof value === "string") return { name: "Error", message: value };
  if (value && typeof value === "object") {
    const v = value;
    if (typeof v.message === "string") {
      return {
        name: typeof v.name === "string" ? v.name : "Error",
        message: v.message,
        ...typeof v.stack === "string" ? { stack: v.stack } : {}
      };
    }
  }
  return { name: "Error", message: String(value) };
}
function parseAreaLevels(spec) {
  const out = [];
  for (const part of spec.split(",")) {
    const [rawArea, rawLevel] = part.split("=").map((s) => s.trim());
    if (!rawArea || !rawLevel) continue;
    if (!(rawLevel in LOG_LEVEL_RANK)) continue;
    const prefix = rawArea.endsWith(".*") ? rawArea.slice(0, -2) : rawArea.endsWith("*") ? rawArea.slice(0, -1) : rawArea;
    out.push({ prefix: prefix.replace(/\.$/, ""), level: rawLevel });
  }
  return out.sort((a, b) => b.prefix.length - a.prefix.length);
}
function foldKey(input) {
  return `${input.area}|${input.event ?? input.msg.replace(/\d+(\.\d+)?/g, "#").slice(0, 80)}`;
}
function slug(text2) {
  return text2.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 40) || "error";
}
var ANCHOR_KEYS = ["sess", "round", "resp", "call", "ev", "task"];
var Runlog = class {
  file;
  run;
  timezone;
  levels;
  incidentsDir;
  echo;
  seq = 0;
  bytes = 0;
  dirReady = false;
  areaSpec = "";
  areaLevels = [];
  ring = [];
  folds = /* @__PURE__ */ new Map();
  incidentAt = /* @__PURE__ */ new Map();
  writeListeners = [];
  constructor(file, opts = {}) {
    this.file = file;
    this.run = opts.run ?? "r-none";
    this.timezone = opts.timezone ?? "Asia/Shanghai";
    this.levels = opts.levels ?? (() => DEFAULT_LEVELS);
    this.incidentsDir = opts.incidentsDir ?? null;
    this.echo = opts.console ?? true;
    if (file) {
      const dir = dirname(file);
      if (!existsSync(dir)) mkdirSync(dir, { recursive: true });
      this.dirReady = true;
      try {
        this.bytes = existsSync(file) ? statSync(file).size : 0;
      } catch {
        this.bytes = 0;
      }
    }
  }
  get path() {
    return this.file;
  }
  get runId() {
    return this.run;
  }
  /** 日志追加订阅，供控制台实时观察。 */
  onWrite(cb) {
    this.writeListeners.push(cb);
  }
  /** 内存中最近的日志记录，包含未写入文件的记录。 */
  recent(limit = RING_SIZE) {
    return this.ring.slice(-limit);
  }
  fileThreshold(area) {
    const levels = this.levels();
    if (levels.areas !== this.areaSpec) {
      this.areaSpec = levels.areas;
      this.areaLevels = parseAreaLevels(levels.areas);
    }
    for (const entry of this.areaLevels) {
      if (area === entry.prefix || area.startsWith(`${entry.prefix}.`)) return entry.level;
    }
    return levels.file;
  }
  write(input) {
    const rank = LOG_LEVEL_RANK[input.level];
    const toFile = rank >= LOG_LEVEL_RANK[this.fileThreshold(input.area)];
    const toConsole = this.echo && rank >= LOG_LEVEL_RANK[this.levels().console];
    if (!toFile && !toConsole) return null;
    const record2 = this.build(input);
    if (rank >= LOG_LEVEL_RANK.warn && this.fold(record2)) return null;
    this.commit(record2, toFile, toConsole);
    if (record2.level === "error") this.incident(record2);
    return record2;
  }
  build(input) {
    const anchors = currentAnchors();
    const record2 = {
      ts: input.ts ?? nowIso(this.timezone),
      run: this.run,
      seq: ++this.seq,
      level: input.level,
      area: input.area,
      msg: input.msg
    };
    if (input.event !== void 0) record2.event = input.event;
    for (const key of ANCHOR_KEYS) {
      const value = input[key] ?? anchors[key];
      if (value !== void 0) record2[key] = value;
    }
    if (input.durMs !== void 0) record2.durMs = input.durMs;
    let data = input.data;
    let err = input.err;
    if (data instanceof Error) {
      err ??= data;
      data = void 0;
    } else if (data && typeof data === "object" && !Array.isArray(data)) {
      const bag = data;
      const carried = bag.err instanceof Error ? bag.err : bag.error instanceof Error ? bag.error : void 0;
      if (carried) {
        err ??= carried;
        const { err: _e, error: _error, ...rest } = bag;
        data = Object.keys(rest).length ? rest : void 0;
      }
    }
    if (data !== void 0) record2.data = data;
    if (err !== void 0) record2.err = normalizeError(err);
    return record2;
  }
  /** 窗口内重复的 warn/error 只累计计数；返回 true 表示本条无需另行写入。 */
  fold(record2) {
    const key = foldKey(record2);
    const open = this.folds.get(key);
    if (open) {
      open.count++;
      return true;
    }
    const timer = setTimeout(() => {
      const entry = this.folds.get(key);
      this.folds.delete(key);
      if (!entry || entry.count === 0) return;
      const summary = { ...entry.record, ts: nowIso(this.timezone), seq: ++this.seq, repeat: entry.count };
      this.commit(summary, true, this.echo);
    }, FOLD_MS);
    timer.unref?.();
    this.folds.set(key, { count: 0, record: record2, timer });
    return false;
  }
  commit(record2, toFile, toConsole) {
    this.ring.push(record2);
    if (this.ring.length > RING_SIZE) this.ring.shift();
    if (toFile && this.file) {
      try {
        if (!this.dirReady) {
          mkdirSync(dirname(this.file), { recursive: true });
          this.dirReady = true;
        }
        if (this.bytes > ROTATE_BYTES) this.rotate();
        const line2 = `${JSON.stringify(record2)}
`;
        appendFileSync(this.file, line2, "utf8");
        this.bytes += Buffer.byteLength(line2, "utf8");
      } catch {
      }
    }
    for (const cb of this.writeListeners) {
      try {
        cb(record2);
      } catch {
      }
    }
    if (!toConsole) return;
    const clock = record2.ts.slice(11, 23);
    const tag = record2.event ? `${record2.area}/${record2.event}` : record2.area;
    const line = `[${clock}] ${record2.level.toUpperCase().padEnd(5)} ${tag}: ${record2.msg}${record2.repeat ? ` (\xD7${record2.repeat + 1})` : ""}`;
    if (record2.level === "error") console.error(line, record2.err?.stack ?? record2.err?.message ?? "", record2.data ?? "");
    else if (record2.level === "warn") console.warn(line, record2.data ?? "");
    else console.log(line);
  }
  /** log.jsonl → log.1.jsonl,已有的代数各退一位 */
  rotate() {
    if (!this.file) return;
    const base = this.file.replace(/\.jsonl$/, "");
    let n = 1;
    while (existsSync(`${base}.${n}.jsonl`)) n++;
    for (let i = n - 1; i >= 1; i--) renameSync(`${base}.${i}.jsonl`, `${base}.${i + 1}.jsonl`);
    renameSync(this.file, `${base}.1.jsonl`);
    this.bytes = 0;
  }
  incident(record2) {
    if (!this.incidentsDir) return;
    const key = foldKey(record2);
    const now = Date.now();
    const last = this.incidentAt.get(key) ?? 0;
    if (now - last < INCIDENT_GAP_MS) return;
    this.incidentAt.set(key, now);
    try {
      mkdirSync(this.incidentsDir, { recursive: true });
      const name = `${record2.ts.slice(0, 23).replace(/[:.]/g, "-")}-${slug(record2.event ?? record2.msg)}.json`;
      writeFileSync(join(this.incidentsDir, name), JSON.stringify({ record: record2, anchors: currentAnchors(), recent: this.ring.slice(0, -1) }, null, 1), "utf8");
    } catch {
    }
  }
  logger(area) {
    return makeLogger(this, area);
  }
  /** 清空当前 run 的日志文件(web运维动作);之后照常append */
  clear() {
    if (!this.file) return;
    try {
      writeFileSync(this.file, "", "utf8");
      this.bytes = 0;
    } catch {
    }
  }
};
function makeLogger(runlog, area) {
  const emit = (level, msg, opts) => {
    runlog.write({ level, area, msg, ...opts });
  };
  return {
    trace: (m, d) => emit("trace", m, { data: d }),
    debug: (m, d) => emit("debug", m, { data: d }),
    info: (m, d) => emit("info", m, { data: d }),
    warn: (m, d) => emit("warn", m, { data: d }),
    error: (m, d) => emit("error", m, { data: d }),
    emit,
    child: (sub) => makeLogger(runlog, `${area}.${sub}`)
  };
}
function nullLogger() {
  const l = {
    trace: () => {
    },
    debug: () => {
    },
    info: () => {
    },
    warn: () => {
    },
    error: () => {
    },
    emit: () => {
    },
    child: () => l
  };
  return l;
}
function shortId(prefix = "") {
  return prefix + Math.random().toString(36).slice(2, 10);
}
function readTextFile(file) {
  const bytes = readFileSync(file);
  if (bytes.length >= 2 && bytes[0] === 255 && bytes[1] === 254) {
    return bytes.subarray(2).toString("utf16le");
  }
  if (bytes.length >= 3 && bytes[0] === 239 && bytes[1] === 187 && bytes[2] === 191) {
    return bytes.subarray(3).toString("utf8");
  }
  return bytes.toString("utf8");
}

// ../../vendor/cortico/src/core/event-store.ts
import { appendFileSync as appendFileSync3, closeSync, existsSync as existsSync3, fstatSync, mkdirSync as mkdirSync3, openSync, readFileSync as readFileSync3, readSync, rmSync, statSync as statSync2 } from "node:fs";
import { join as join3 } from "node:path";

// ../../vendor/cortico/src/core/run.ts
import { appendFileSync as appendFileSync2, existsSync as existsSync2, mkdirSync as mkdirSync2, readdirSync, readFileSync as readFileSync2, writeFileSync as writeFileSync2 } from "node:fs";
import { join as join2, resolve } from "node:path";
import { randomBytes } from "node:crypto";
var RUN_ID = /^r-\d{8}-\d{6}-[0-9a-f]{4}$/;
function runsDirOf(dataDir) {
  return join2(dataDir, "runs");
}
function listRuns(dataDir) {
  const dir = runsDirOf(dataDir);
  if (!existsSync2(dir)) return [];
  return readdirSync(dir).filter((name) => RUN_ID.test(name)).sort();
}
function gitSha(repoRoot) {
  if (!repoRoot) return null;
  try {
    const head = readFileSync2(join2(repoRoot, ".git", "HEAD"), "utf8").trim();
    if (!head.startsWith("ref:")) return head.slice(0, 12);
    const ref = head.slice(4).trim();
    const refFile = resolve(repoRoot, ".git", ref);
    if (existsSync2(refFile)) return readFileSync2(refFile, "utf8").trim().slice(0, 12);
    const packed = join2(repoRoot, ".git", "packed-refs");
    if (!existsSync2(packed)) return null;
    for (const line of readFileSync2(packed, "utf8").split("\n")) {
      const [sha, name] = line.trim().split(" ");
      if (name === ref) return sha.slice(0, 12);
    }
  } catch {
  }
  return null;
}
function openRun(dataDir, meta) {
  const runsDir = runsDirOf(dataDir);
  mkdirSync2(runsDir, { recursive: true });
  const previous = listRuns(dataDir);
  const startedAt = nowIso(meta.timezone);
  const stamp = startedAt.slice(0, 19).replace(/[-:T]/g, "");
  const id = `r-${stamp.slice(0, 8)}-${stamp.slice(8, 14)}-${randomBytes(2).toString("hex")}`;
  const dir = join2(runsDir, id);
  mkdirSync2(dir, { recursive: true });
  const previousRun = previous.length ? previous[previous.length - 1] : null;
  appendFileSync2(join2(runsDir, "index.jsonl"), JSON.stringify({
    run: id,
    startedAt,
    bot: meta.bot,
    pid: process.pid,
    gitSha: gitSha(meta.repoRoot),
    previousRun
  }) + "\n", "utf8");
  return { id, dir, runsDir, startedAt, previousRun };
}
function writeRunJson(run, data) {
  writeFileSync2(join2(run.dir, "run.json"), JSON.stringify({ run: run.id, startedAt: run.startedAt, previousRun: run.previousRun, ...data }, null, 2), "utf8");
}

// ../../vendor/cortico/src/core/event-store.ts
var EDGE_BYTES = 64 * 1024;
var EVENTS_FILE = "events.jsonl";
function parseLine(line) {
  try {
    const e = JSON.parse(line);
    return Number.isInteger(e.cursor) && typeof e.ts === "string" ? e : null;
  } catch {
    return null;
  }
}
function readEdges(file) {
  const fd = openSync(file, "r");
  try {
    const size = fstatSync(fd).size;
    if (size === 0) return null;
    const headLen = Math.min(size, EDGE_BYTES);
    const head = Buffer.alloc(headLen);
    readSync(fd, head, 0, headLen, 0);
    const headLines = head.toString("utf8").split("\n");
    const first = headLines.map((l) => l.trim()).filter(Boolean).map(parseLine).find((e) => e !== null);
    if (!first) return null;
    const tailStart = Math.max(0, size - EDGE_BYTES);
    const tail = Buffer.alloc(size - tailStart);
    readSync(fd, tail, 0, size - tailStart, tailStart);
    const tailLines = tail.toString("utf8").split("\n");
    if (tailStart > 0) tailLines.shift();
    const last = tailLines.map((l) => l.trim()).filter(Boolean).map(parseLine).reverse().find((e) => e !== null);
    return { first, last: last ?? first };
  } finally {
    closeSync(fd);
  }
}
function lowerBound(events, cursor) {
  let lo = 0;
  let hi = events.length;
  while (lo < hi) {
    const mid = lo + hi >> 1;
    if (events[mid].cursor < cursor) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}
var JsonlEventStore = class {
  log;
  run;
  segments = [];
  current;
  /** 下一条事件拿到的 cursor */
  next = 1;
  /**
   * 本实例记录的分片字节数；写入前的大小变化可能来自其他写入方。
   * 用 stat 比较大小，避免每次追加都读取全部文件。
   */
  expectedSize = 0;
  /** 文件大小不符的错误只报告一次。 */
  concurrencyReported = false;
  appendListeners = [];
  constructor(opts) {
    this.log = opts.log ?? nullLogger();
    this.run = opts.run;
    const runsDir = runsDirOf(opts.dataDir);
    for (const id of listRuns(opts.dataDir)) {
      if (id === this.run) continue;
      const file = join3(runsDir, id, EVENTS_FILE);
      if (!existsSync3(file)) continue;
      let edges;
      try {
        edges = readEdges(file);
      } catch (error) {
        this.log.warn("\u4E8B\u4EF6\u5206\u7247\u8BFB\u4E0D\u51FA\u5934\u5C3E,\u8DF3\u8FC7", { run: id, err: error });
        continue;
      }
      if (!edges) continue;
      this.segments.push({
        run: id,
        file,
        first: edges.first.cursor,
        last: edges.last.cursor,
        firstTs: edges.first.ts,
        lastTs: edges.last.ts,
        events: null
      });
      this.next = Math.max(this.next, edges.last.cursor + 1);
    }
    const currentFile = join3(runsDir, this.run, EVENTS_FILE);
    mkdirSync3(join3(runsDir, this.run), { recursive: true });
    this.current = { run: this.run, file: currentFile, first: 0, last: 0, firstTs: "", lastTs: "", events: [] };
    if (existsSync3(currentFile)) {
      const raw = readFileSync3(currentFile, "utf8");
      this.expectedSize = Buffer.byteLength(raw, "utf8");
      this.current.events = this.parseAll(raw, this.run);
      const events = this.current.events;
      if (events.length) {
        this.current.first = events[0].cursor;
        this.current.last = events[events.length - 1].cursor;
        this.current.firstTs = events[0].ts;
        this.current.lastTs = events[events.length - 1].ts;
        this.next = Math.max(this.next, this.current.last + 1);
      }
    }
    this.segments.push(this.current);
  }
  parseAll(raw, run) {
    const out = [];
    let skipped = 0;
    for (const line of raw.split("\n")) {
      const t = line.trim();
      if (!t) continue;
      const e = parseLine(t);
      if (!e) {
        skipped++;
        continue;
      }
      if (out.length && e.cursor <= out[out.length - 1].cursor) {
        skipped++;
        continue;
      }
      out.push(e);
    }
    if (skipped) this.log.warn("\u4E8B\u4EF6\u5206\u7247\u6709\u635F\u574F\u6216\u4E71\u5E8F\u884C,\u5DF2\u8DF3\u8FC7", { run, skipped });
    return out;
  }
  load(segment) {
    if (segment.events) return segment.events;
    let raw = "";
    try {
      raw = readFileSync3(segment.file, "utf8");
    } catch (error) {
      this.log.warn("\u4E8B\u4EF6\u5206\u7247\u8BFB\u53D6\u5931\u8D25", { run: segment.run, err: error });
    }
    segment.events = this.parseAll(raw, segment.run);
    return segment.events;
  }
  append(e) {
    this.checkExclusiveWrite();
    const envelope = { ...e, cursor: this.next++, run: this.run };
    const events = this.current.events;
    events.push(envelope);
    if (events.length === 1) {
      this.current.first = envelope.cursor;
      this.current.firstTs = envelope.ts;
    }
    this.current.last = envelope.cursor;
    this.current.lastTs = envelope.ts;
    const line = JSON.stringify(envelope) + "\n";
    appendFileSync3(this.current.file, line, "utf8");
    this.expectedSize += Buffer.byteLength(line, "utf8");
    for (const cb of this.appendListeners) {
      try {
        cb(envelope);
      } catch {
      }
    }
    return envelope;
  }
  /** 大小与本实例记录不符时报告文件变化，仍继续写入；独占检查由 instanceLock 负责。 */
  checkExclusiveWrite() {
    if (this.concurrencyReported) return;
    let onDisk = 0;
    try {
      onDisk = existsSync3(this.current.file) ? statSync2(this.current.file).size : 0;
    } catch {
      return;
    }
    if (onDisk === this.expectedSize) return;
    this.concurrencyReported = true;
    this.log.error("\u4E8B\u4EF6\u5E93\u88AB\u672C\u8FDB\u7A0B\u4E4B\u5916\u7684\u5199\u5165\u6539\u52A8\u8FC7,\u7591\u4F3C\u53E6\u4E00\u4E2A\u5B9E\u4F8B\u5728\u5199\u540C\u4E00\u4E2A\u4E8B\u4EF6\u5E93", {
      expectedSize: this.expectedSize,
      onDiskSize: onDisk,
      file: this.current.file
    });
    this.expectedSize = onDisk;
  }
  /** 事件追加订阅，供控制台实时观察。 */
  onAppend(cb) {
    this.appendListeners.push(cb);
  }
  /** 当前 run 分片里的条数 */
  currentCount() {
    return this.current.events.length;
  }
  get(cursor) {
    if (!Number.isInteger(cursor) || cursor < 1) return void 0;
    const segment = this.segments.find((s) => s.first <= cursor && cursor <= s.last);
    if (!segment) return void 0;
    const events = this.load(segment);
    const i = lowerBound(events, cursor);
    return events[i]?.cursor === cursor ? events[i] : void 0;
  }
  latestCursor() {
    return this.next - 1;
  }
  segmentsIn(q) {
    return this.segments.filter((s) => {
      if (s.last === 0) return s === this.current;
      if (q.fromCursor !== void 0 && s.last < q.fromCursor) return false;
      if (q.toCursor !== void 0 && s.first > q.toCursor) return false;
      if (q.fromTs !== void 0 && s.lastTs < q.fromTs) return false;
      if (q.toTs !== void 0 && s.firstTs > q.toTs) return false;
      return true;
    });
  }
  range(q) {
    const matched = [];
    for (const segment of this.segmentsIn(q)) {
      const events = this.load(segment);
      const start = q.fromCursor !== void 0 ? lowerBound(events, q.fromCursor) : 0;
      for (let i = start; i < events.length; i++) {
        const e = events[i];
        if (q.toCursor !== void 0 && e.cursor > q.toCursor) break;
        if (q.fromTs !== void 0 && e.ts < q.fromTs) continue;
        if (q.toTs !== void 0 && e.ts > q.toTs) continue;
        if (q.senderKey !== void 0 && e.senderKey !== q.senderKey) continue;
        if (q.source !== void 0 && e.source !== q.source) continue;
        if (q.origin !== void 0 && e.origin !== q.origin) continue;
        matched.push(e);
      }
    }
    if (q.limit !== void 0 && q.limit >= 0 && matched.length > q.limit) {
      return matched.slice(matched.length - q.limit);
    }
    return matched;
  }
  around(cursor, before, after) {
    const latest = this.latestCursor();
    if (latest === 0) return [];
    const center = Math.min(Math.max(cursor, 1), latest);
    return this.range({ fromCursor: center - Math.max(0, before), toCursor: center + Math.max(0, after) });
  }
  grep(q) {
    const kw = q.keyword.toLowerCase();
    const ctx = Math.max(0, q.context);
    const hits = [];
    for (const segment of this.segmentsIn(q)) {
      for (const e of this.load(segment)) {
        if (q.senderKey !== void 0 && e.senderKey !== q.senderKey) continue;
        if (q.source !== void 0 && e.source !== q.source) continue;
        if (q.origin !== void 0 && e.origin !== q.origin) continue;
        if (q.fromTs !== void 0 && e.ts < q.fromTs) continue;
        if (q.toTs !== void 0 && e.ts > q.toTs) continue;
        if (!e.text.toLowerCase().includes(kw)) continue;
        hits.push({ hitCursor: e.cursor, events: this.around(e.cursor, ctx, ctx) });
        if (q.limit !== void 0 && hits.length >= q.limit) return hits;
      }
    }
    return hits;
  }
  /**
   * 清空当前 run 的分片(web 运维动作):删文件与内存里这一段,游标不回退,
   * 更早的 run 不受影响。返回清掉的条数。
   */
  clear() {
    const n = this.current.events.length;
    this.current.events = [];
    this.current.first = 0;
    this.current.last = 0;
    this.current.firstTs = "";
    this.current.lastTs = "";
    if (existsSync3(this.current.file)) rmSync(this.current.file);
    this.expectedSize = 0;
    this.log.warn("\u5F53\u524D run \u7684\u4E8B\u4EF6\u5206\u7247\u5DF2\u6E05\u7A7A", { cleared: n, run: this.run });
    return n;
  }
};

// ../../vendor/cortico/src/core/bus.ts
var WakeBus = class {
  opts;
  queue = [];
  paused = false;
  gate = null;
  /** 一次整批投递许可;人工暂停的优先级更高。 */
  bypassGateOnce = false;
  /** 到期即投递的那一个定时器;每次 push 按四条判据重算 */
  timer = null;
  /** 本批首件与末件的到达时刻(队列空时为 null) */
  firstAt = null;
  lastAt = 0;
  /** 挂起中的消费者(单消费者,最多一个) */
  waiter = null;
  /** 已到投递条件但没有消费者在等:置真,消费者一来就取走 */
  ready = false;
  /** preempt 只报告机械时机；是否仍可安全取消由主循环裁决。 */
  preemptHandler = null;
  log;
  constructor(opts, log = nullLogger()) {
    this.opts = opts;
    this.log = log;
  }
  setPreemptHandler(handler) {
    this.preemptHandler = handler;
  }
  push(item, opts) {
    const origin = originOf(item);
    const trigger = opts?.trigger ?? (origin === "internal" ? "flush" : "debounce");
    const piggyback = trigger === "piggyback";
    this.queue.push({ item, piggyback });
    const gate = this.gate;
    if (gate) {
      this.clearTimers();
      if (piggyback) return;
      const gateText = textForGate(item);
      if (origin === "external" && gate.keyword !== void 0 && gateText?.includes(gate.keyword)) {
        gate.onKeyword();
        const permitted = this.gate !== gate || this.bypassGateOnce;
        this.log.emit("debug", "\u95F8\u95E8\u5173\u952E\u8BCD\u547D\u4E2D", { event: "gate-keyword", data: { gate: gate.id, permitted } });
        if (permitted) this.deliver(this.bypassGateOnce);
        this.notifyPreempt(trigger, permitted);
        return;
      }
      if (this.bypassGateOnce) {
        this.deliver(true);
        this.notifyPreempt(trigger, true);
        return;
      }
      if (origin === "external" && this.pendingEventCount() > gate.overflowLimit) {
        this.bypassGateOnce = true;
        this.log.emit("debug", "\u95F8\u95E8\u4E0B\u79EF\u538B\u8D8A\u8FC7\u6EA2\u51FA\u7EBF,\u6574\u6279\u653E\u884C", { event: "gate-overflow", data: { gate: gate.id, pending: this.pendingEventCount(), limit: gate.overflowLimit } });
        gate.onOverflow();
        this.deliver(true);
        this.notifyPreempt(trigger, true);
      }
      return;
    }
    if (trigger === "preempt") {
      const permitted = !this.blocked();
      this.deliver();
      this.notifyPreempt(trigger, permitted);
      return;
    }
    if (trigger === "flush") {
      this.deliver();
      return;
    }
    if (piggyback) return;
    const now = Date.now();
    if (this.firstAt === null) this.firstAt = now;
    this.lastAt = now;
    if (this.pendingEventCount() >= this.opts.maxBatchSize) {
      this.deliver();
      return;
    }
    this.arm();
  }
  /** 重新计算投递时间；配置修改在下一次 push 生效。 */
  arm() {
    if (this.firstAt === null) return;
    const { quietGapMs, minBatchAgeMs, maxBatchAgeMs } = this.opts;
    const at = Math.min(
      this.firstAt + maxBatchAgeMs,
      Math.max(this.firstAt + minBatchAgeMs, this.lastAt + quietGapMs)
    );
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.deliver(), Math.max(0, at - Date.now()));
  }
  /** 暂停或闸门(未获准整批放行)期间不投递。 */
  blocked() {
    return this.paused || this.gate !== null && !this.bypassGateOnce;
  }
  /** 已获准投递的 preempt 才能取消当前模型轮；暂停与闸门继续拥有更高优先级。 */
  notifyPreempt(trigger, permitted) {
    if (trigger === "preempt" && permitted && !this.paused) {
      this.log.emit("debug", "\u62A2\u5360:\u8BF7\u6C42\u53D6\u6D88\u5C1A\u672A\u5916\u5316\u7684\u5728\u9014\u6A21\u578B\u8F6E", { event: "preempt" });
      this.preemptHandler?.();
    }
  }
  /** 人工暂停/继续(控制台);继续时积压一次性投递 */
  setPaused(v) {
    if (v !== this.paused) this.log.emit("info", v ? "\u603B\u7EBF\u5DF2\u6682\u505C:\u4E8B\u4EF6\u7167\u5E38\u843D\u5E93,\u4E0D\u6295\u9012" : "\u603B\u7EBF\u7EE7\u7EED", { event: v ? "paused" : "resumed", data: { queued: this.queue.length } });
    this.paused = v;
    if (!this.paused && (this.ready || this.queue.length > 0)) {
      this.deliver(this.bypassGateOnce);
    }
  }
  isPaused() {
    return this.paused;
  }
  /**
   * 安装或更新投递闸门。若此前没有闸门,安装前已经积压的内容获准放行一次;
   * 闸门只约束安装之后到达的唤醒项。
   */
  setDeliveryGate(gate) {
    const hadGate = this.gate !== null;
    this.gate = gate;
    this.clearTimers();
    this.log.emit("debug", hadGate ? "\u6295\u9012\u95F8\u95E8\u5DF2\u66F4\u65B0" : "\u6295\u9012\u95F8\u95E8\u5DF2\u5B89\u88C5", { event: "gate-set", data: { gate: gate.id, queued: this.queue.length } });
    if (!hadGate && this.queue.length > 0) {
      this.deliver(true);
    }
  }
  /**
   * 只解除匹配id的闸门。deliverQueued=false用于"先解闸、再把到期通知和积压
   * 一起投递",避免拆成两个user回合。
   */
  clearDeliveryGate(id, deliverQueued = true) {
    if (this.gate?.id !== id) return false;
    this.gate = null;
    this.log.emit("debug", "\u6295\u9012\u95F8\u95E8\u5DF2\u89E3\u9664", { event: "gate-cleared", data: { gate: id, queued: this.queue.length, deliverQueued } });
    if (deliverQueued && this.queue.length > 0) {
      this.deliver(this.bypassGateOnce);
    }
    return true;
  }
  isDeliveryBlocked() {
    return this.gate !== null;
  }
  /** 当前积压条数(控制台可见性;含尚未成文的投递成文项) */
  pending() {
    return this.queue.length;
  }
  /** 供空闲判定使用：不计延迟渲染项和 piggyback 项。 */
  pendingImmediate() {
    let n = 0;
    for (const q of this.queue) {
      if (!q.piggyback && (q.item.event !== void 0 || q.item.candidate !== void 0)) n++;
    }
    return n;
  }
  /** 按原序取出匹配项，消费后不再投递。同步完成，不触发消费者或改变投递许可和计时器。 */
  drainPending(pred) {
    const drained = [];
    const kept = [];
    for (const q of this.queue) {
      if (pred(q.item)) drained.push(q.item);
      else kept.push(q);
    }
    this.queue = kept;
    if (!this.hasWakingItem()) {
      this.ready = false;
      this.bypassGateOnce = false;
      this.firstAt = null;
      this.clearTimers();
    }
    return drained;
  }
  /**
   * 仅在满足投递条件时同步取走整批，否则返回 null。
   * 供工具调用链在没有 nextBatch 消费者时接收已就绪的通知。
   */
  takeIfReady() {
    if (!this.ready || this.queue.length === 0 || this.blocked()) return null;
    this.ready = false;
    return this.take();
  }
  /** 取走整个队列；尚不可投递时等待。只允许一个等待中的消费者。 */
  nextBatch() {
    if (this.waiter) throw new Error("WakeBus\u53EA\u652F\u6301\u5355\u6D88\u8D39\u8005");
    if (this.ready && this.queue.length > 0 && !this.blocked()) {
      this.ready = false;
      return Promise.resolve(this.take());
    }
    return new Promise((resolve2) => {
      this.waiter = resolve2;
    });
  }
  deliver(bypassGate = false) {
    this.clearTimers();
    if (this.queue.length > 0 && !this.hasWakingItem()) return;
    if (bypassGate) this.bypassGateOnce = true;
    if (this.blocked()) {
      this.ready = true;
      return;
    }
    if (this.queue.length === 0) {
      this.bypassGateOnce = false;
      return;
    }
    if (this.waiter) {
      const w = this.waiter;
      this.waiter = null;
      this.ready = false;
      w(this.take());
    } else {
      this.ready = true;
    }
  }
  take() {
    const batch = this.queue.map((q) => q.item);
    this.log.emit("debug", "\u6295\u9012\u4E00\u6279", { event: "deliver", data: { count: batch.length, piggyback: this.queue.filter((q) => q.piggyback).length, ageMs: this.firstAt === null ? 0 : Date.now() - this.firstAt } });
    this.queue = [];
    this.bypassGateOnce = false;
    this.firstAt = null;
    return batch;
  }
  /** 供批次大小与闸门上限使用：只计外部即时事件和候选项，不计 piggyback。 */
  pendingEventCount() {
    let count = 0;
    for (const q of this.queue) {
      if (!q.piggyback && (q.item.event !== void 0 || q.item.candidate !== void 0) && originOf(q.item) === "external") count++;
    }
    return count;
  }
  hasWakingItem() {
    return this.queue.some((q) => !q.piggyback);
  }
  clearTimers() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
};
function originOf(item) {
  return item.event?.origin ?? item.deferred?.origin ?? item.candidate.origin;
}
function textForGate(item) {
  return item.event?.text ?? item.candidate?.gateText ?? null;
}

// ../../vendor/cortico/src/core/session.ts
import { join as join4 } from "node:path";

// ../../vendor/cortico/src/protocol/open-responses/context-log.ts
import { appendFileSync as appendFileSync4, closeSync as closeSync2, existsSync as existsSync4, fsyncSync, mkdirSync as mkdirSync4, openSync as openSync2, readFileSync as readFileSync4, renameSync as renameSync2, truncateSync, writeFileSync as writeFileSync3 } from "node:fs";
import { dirname as dirname2 } from "node:path";
function freeze(value) {
  if (value !== null && typeof value === "object") {
    for (const child of Object.values(value)) freeze(child);
    Object.freeze(value);
  }
  return value;
}
function isRecord(row) {
  const r = row;
  return !!r && r.version === 2 && !!r.item && typeof r.item === "object" && !Array.isArray(r.item) && !!r.context && typeof r.context === "object" && !Array.isArray(r.context);
}
var ContextLog = class {
  constructor(file, stamp) {
    this.file = file;
    this.stamp = stamp;
    mkdirSync4(dirname2(file), { recursive: true });
  }
  file;
  stamp;
  entries = Object.freeze([]);
  get records() {
    return this.entries;
  }
  /** Any other damaged line throws and leaves the file untouched. */
  load() {
    if (!existsSync4(this.file)) {
      this.entries = Object.freeze([]);
      return null;
    }
    const raw = readFileSync4(this.file, "utf8");
    let body = raw;
    let repair = null;
    if (raw.length > 0 && !raw.endsWith("\n")) {
      const cut = raw.lastIndexOf("\n") + 1;
      const tail = raw.slice(cut);
      let parsed = null;
      try {
        parsed = JSON.parse(tail);
      } catch {
      }
      if (isRecord(parsed)) repair = { kind: "unterminated-tail" };
      else {
        body = raw.slice(0, cut);
        repair = { kind: "torn-tail", bytes: Buffer.byteLength(tail, "utf8") };
      }
    }
    const rows = body.split(/\r?\n/).filter((line) => line.trim()).map((line, index) => {
      let row;
      try {
        row = JSON.parse(line);
      } catch {
        throw new Error(`Invalid session JSON at ${this.file}:${index + 1}`);
      }
      if (!isRecord(row)) throw new Error(`Invalid context record at ${this.file}:${index + 1}`);
      return freeze(row);
    });
    if (repair?.kind === "torn-tail") truncateSync(this.file, Buffer.byteLength(body, "utf8"));
    else if (repair) appendFileSync4(this.file, "\n");
    this.entries = Object.freeze(rows);
    return repair;
  }
  append(entry) {
    const next = structuredClone(entry);
    if (this.stamp && next.context.ts === void 0) next.context.ts = this.stamp();
    appendFileSync4(this.file, JSON.stringify(next) + "\n");
    this.entries = Object.freeze([...this.entries, freeze(next)]);
    return next;
  }
  reset(records) {
    const next = records.map((entry) => freeze(structuredClone(entry)));
    atomicContextWrite(this.file, next);
    this.entries = Object.freeze(next);
  }
};
function atomicContextWrite(path, records) {
  const temporary = `${path}.${process.pid}.tmp`;
  const fd = openSync2(temporary, "w");
  try {
    writeFileSync3(fd, records.map((row) => JSON.stringify(row)).join("\n") + (records.length ? "\n" : ""));
    fsyncSync(fd);
  } finally {
    closeSync2(fd);
  }
  renameSync2(temporary, path);
}

// ../../vendor/cortico/src/core/session.ts
var SessionLog = class {
  context;
  get records() {
    return this.context.records;
  }
  appendListeners = [];
  resetListeners = [];
  /** stamp:入库时刻的来源(config 时区的 ISO);不给则消息不带 ts */
  constructor(dataDir, fileName = "session-main.jsonl", stamp) {
    this.context = new ContextLog(join4(dataDir, fileName), stamp);
  }
  /** 每次 append 后通知 Web 调试监听器;监听器异常与会话写入隔离。 */
  onAppend(cb) {
    this.appendListeners.push(cb);
  }
  /** 截断/重置后回调(整个数组被替换) */
  onReset(cb) {
    this.resetListeners.push(cb);
  }
  append(msg) {
    this.context.append(msg);
    const stored = this.records[this.records.length - 1];
    for (const cb of this.appendListeners) {
      try {
        cb(stored, this.records.length - 1);
      } catch {
      }
    }
  }
  /** 返回对未写完末行的修复；其他损坏行抛错。 */
  load() {
    return this.context.load();
  }
  /** 整体替换：先写临时文件，再 rename 覆盖目标文件。 */
  reset(messages) {
    this.context.reset(messages);
    for (const cb of this.resetListeners) {
      try {
        cb([...this.records]);
      } catch {
      }
    }
  }
  estTokens() {
    return estimateMessagesTokens(this.records);
  }
};

// ../../vendor/cortico/src/core/state.ts
import { existsSync as existsSync5, mkdirSync as mkdirSync5, readFileSync as readFileSync5, renameSync as renameSync3, writeFileSync as writeFileSync4 } from "node:fs";
import { dirname as dirname3, join as join5 } from "node:path";
var DEFAULTS = {
  lastTruncateAt: null,
  lastDeliveredCursor: 0,
  llmStall: { since: 0, at: [] },
  persona: {},
  worldVisibility: {}
};
function freshDefaults() {
  return { ...DEFAULTS, llmStall: { since: 0, at: [] }, persona: {}, worldVisibility: {} };
}
function readStall(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { since: 0, at: [] };
  const r = raw;
  return {
    since: typeof r.since === "number" && Number.isFinite(r.since) ? r.since : 0,
    at: Array.isArray(r.at) ? r.at.filter((t) => typeof t === "number" && Number.isFinite(t)) : []
  };
}
var CoreState = class {
  file;
  // 各实例需独立的 Persona 状态对象，不能共享 DEFAULTS 中的引用。
  data = freshDefaults();
  constructor(dataDir) {
    this.file = join5(dataDir, "core-state.json");
  }
  load() {
    this.data = freshDefaults();
    if (!existsSync5(this.file)) return;
    try {
      const raw = JSON.parse(readFileSync5(this.file, "utf8"));
      this.data = {
        lastTruncateAt: raw.lastTruncateAt ?? DEFAULTS.lastTruncateAt,
        lastDeliveredCursor: Number.isInteger(raw.lastDeliveredCursor) ? raw.lastDeliveredCursor : DEFAULTS.lastDeliveredCursor,
        llmStall: readStall(raw.llmStall),
        persona: raw.persona && typeof raw.persona === "object" && !Array.isArray(raw.persona) ? raw.persona : {},
        worldVisibility: raw.worldVisibility && typeof raw.worldVisibility === "object" && !Array.isArray(raw.worldVisibility) ? Object.fromEntries(
          Object.entries(raw.worldVisibility).map(([k, v]) => [k, v !== false])
        ) : {}
      };
    } catch {
    }
  }
  save() {
    const dir = dirname3(this.file);
    if (!existsSync5(dir)) mkdirSync5(dir, { recursive: true });
    const tmp = this.file + ".tmp";
    writeFileSync4(tmp, JSON.stringify(this.data, null, 2), "utf8");
    renameSync3(tmp, this.file);
  }
  /**
   * 清除人格状态与截断标记并落盘。投递水位和运维可见性跨重置保留，避免重放
   * 已投递事件或改变 World 可见性。
   */
  clear() {
    this.data = {
      ...freshDefaults(),
      lastDeliveredCursor: this.data.lastDeliveredCursor,
      worldVisibility: this.data.worldVisibility
    };
    this.save();
  }
};

// ../../vendor/cortico/src/providers/registry.ts
import { existsSync as existsSync7, readdirSync as readdirSync2, readFileSync as readFileSync6 } from "node:fs";
import { join as join6 } from "node:path";
import { URL, fileURLToPath, pathToFileURL } from "node:url";

// ../../vendor/cortico/src/providers/pricebook.ts
import { createHash as createHash2 } from "node:crypto";
function snapshotPrice(definition, at) {
  const { models: _models, ...definitionBody } = definition;
  return { ...structuredClone(definitionBody), id: createHash2("sha256").update(JSON.stringify(definition)).digest("hex").slice(0, 20), capturedAt: at.startedAt };
}
function quotePrices(entry, request, at, defaults) {
  const byBasis = /* @__PURE__ */ new Map();
  for (const definition of [...defaults, ...entry.pricing ?? []]) {
    if (definition.models.includes("*") || definition.models.includes(request.model ?? "")) byBasis.set(definition.basis, definition);
  }
  return [...byBasis.values()].map((definition) => snapshotPrice(definition, at));
}

// ../../vendor/cortico/src/providers/registry.ts
import { createHash as createHash3 } from "node:crypto";

// ../../vendor/cortico/src/core/secrets.ts
import { existsSync as existsSync6 } from "node:fs";
function secretReader(file) {
  return (name) => {
    const fromEnv = process.env[name];
    if (fromEnv) return fromEnv;
    const m = new RegExp(`^\\s*${name}\\s*=\\s*(\\S+)`, "m").exec(existsSync6(file) ? readTextFile(file) : "");
    return m ? m[1] : "";
  };
}

// ../../vendor/cortico/src/providers/registry.ts
async function discoverProviderModules(root = fileURLToPath(new URL(".", import.meta.url))) {
  const modules = [];
  for (const dir of readdirSync2(root, { withFileTypes: true }).sort(
    (a, b) => a.name.localeCompare(b.name)
  )) {
    if (!dir.isDirectory()) continue;
    const entry = join6(root, dir.name, "index.ts");
    if (!existsSync7(entry)) continue;
    const module = (await import(pathToFileURL(entry).href)).default;
    if (module.id !== dir.name)
      throw new Error(`Provider module ID must match directory: ${dir.name}`);
    modules.push(module);
  }
  return modules;
}
var providerModules = await discoverProviderModules();
var byId = new Map(providerModules.map((module) => [module.id, module]));
function providerModule(kind) {
  const module = byId.get(kind);
  if (!module) throw new Error(`Unknown provider module: ${kind}`);
  return module;
}
var ProviderRegistry = class _ProviderRegistry {
  constructor(entries, host, modules = providerModules, secretOverrides = {}) {
    this.entries = entries;
    this.host = host;
    this.modules = modules;
    this.secretOverrides = secretOverrides;
  }
  entries;
  host;
  modules;
  secretOverrides;
  instances = /* @__PURE__ */ new Map();
  resources = /* @__PURE__ */ new Map();
  module(kind) {
    const module = this.modules.find((module2) => module2.id === kind);
    if (!module) throw new Error(`Unknown provider module: ${kind}`);
    return module;
  }
  /**
   * A registry over one detached entry. Its instances never enter the live cache; `secrets`
   * are the values the console holds but has not written to the endpoint's `.env`.
   */
  previewRegistry(name, entry, secrets = {}) {
    return new _ProviderRegistry(() => ({ [name]: entry }), this.host, this.modules, secrets);
  }
  preview(name, entry) {
    return this.previewRegistry(name, entry).resolve(name);
  }
  resolve(name) {
    const raw = this.entries()[name];
    if (!raw) throw new Error(`\u6CA1\u6709\u8FD9\u4E2A LLM provider: ${name}`);
    const module = this.module(raw.kind);
    const entry = module.normalize?.(structuredClone(raw)) ?? structuredClone(raw);
    const { pricing: _pricing, spec: _spec, ...transportEntry } = entry;
    const stateDir = join6(this.host.stateRoot, name);
    const envFile = join6(stateDir, ".env");
    const fingerprint = existsSync7(envFile) ? createHash3("sha256").update(readFileSync6(envFile)).digest("hex") : "";
    const key = JSON.stringify([transportEntry, fingerprint]);
    const previous = this.instances.get(name);
    if (previous?.key === key) return previous.value;
    const { stateRoot: _stateRoot, ...base } = this.host;
    const stored = secretReader(envFile);
    const value = module.create(name, entry, {
      ...base,
      stateDir,
      secret: (key2) => this.secretOverrides[key2] ?? stored(key2),
      currentEntry: () => module.normalize?.(structuredClone(this.entries()[name])) ?? this.entries()[name],
      resource: (resource, create) => {
        const id = JSON.stringify([module.id, name, resource]);
        if (!this.resources.has(id)) this.resources.set(id, create());
        return this.resources.get(id);
      }
    });
    this.instances.set(name, { key, value });
    return value;
  }
  bind(name) {
    const raw = this.entries()[name];
    if (!raw) throw new Error(`\u6CA1\u6709\u8FD9\u4E2A LLM provider: ${name}`);
    const module = this.module(raw.kind);
    const entry = module.normalize?.(structuredClone(raw)) ?? structuredClone(raw);
    const instance = this.resolve(name);
    const domain = () => createHash3("sha256").update(JSON.stringify([entry.kind, entry.baseUrl, instance.compatibilityKey?.() ?? null])).digest("hex");
    const client = {
      bind: () => client,
      respond: (request, options) => instance.client.respond(request, {
        ...options,
        quote: (at) => quotePrices(entry, request, at, module.prices?.(entry, request, at) ?? []),
        origin: {
          instance: name,
          module: entry.kind,
          model: request.model ?? "",
          compatibilityDomain: domain()
        }
      })
    };
    return client;
  }
  /** Drop the cached instance so the next resolve rebuilds it; `host.resource` objects survive. */
  invalidate(name) {
    this.instances.delete(name);
  }
  async start(name) {
    return this.resolve(name).start?.();
  }
  async stopAll() {
    await Promise.all([...this.instances.values()].map((instance) => instance.value.stop?.()));
  }
};

// ../../vendor/cortico/src/protocol/open-responses/context-helpers.ts
function hasRole(entry, role) {
  return entry.item.type === "message" && entry.item.role === role;
}
function textOf(entry) {
  return itemText(entry.item);
}
function withoutPastReasoning(entries) {
  return entries.filter((entry) => entry.item.type !== "reasoning" || entry.context.head);
}
function responseRequest(spec, context, tools = []) {
  return {
    model: spec.model,
    input: context.map(inputItem),
    // 只有协议声明的成员进线;运行时传进来的对象还带着分类标签,它归控制台与工具装配。
    tools: tools.map(({ name, description, parameters }) => ({ type: "function", name, description, parameters })),
    // effort 词表归端点(见 ModelSpec.reasoningEffort);协议枚举只覆盖 OpenAI 自己的取值。
    reasoning: spec.thinking ? { ...spec.reasoningEffort ? { effort: spec.reasoningEffort } : {} } : { effort: "none" },
    ...spec.temperature !== void 0 ? { temperature: spec.temperature } : {},
    ...spec.maxTokens !== void 0 ? { max_output_tokens: spec.maxTokens } : {}
  };
}
function usageCounters(meters) {
  return {
    promptTokens: meters.input ?? 0,
    completionTokens: meters.output ?? 0,
    cacheHitTokens: meters.cachedInput ?? 0,
    cacheMissTokens: meters.uncachedInput ?? 0,
    reasoningTokens: meters.reasoning ?? void 0
  };
}

// ../../vendor/cortico/src/protocol/open-responses/stream.ts
var ResponseProtocolError = class extends Error {
  constructor(message2) {
    super(message2);
    this.name = "ResponseProtocolError";
  }
};
function check(condition, message2) {
  if (!condition) throw new ResponseProtocolError(message2);
}
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${JSON.stringify(k)}:${canonical(v)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}
var ResponseAccumulator = class {
  response = null;
  items = /* @__PURE__ */ new Map();
  ids = /* @__PURE__ */ new Set();
  closed = /* @__PURE__ */ new Set();
  closedParts = /* @__PURE__ */ new Set();
  lastSequence = -1;
  terminal = false;
  accept(event) {
    check(event && STREAM_EVENT_TYPES.has(event.type), "Unknown Open Responses event type");
    check(!this.terminal, "Event after terminal response");
    check(Number.isInteger(event.sequence_number) && event.sequence_number > this.lastSequence, "Non-increasing event sequence");
    this.lastSequence = event.sequence_number;
    if (event.type === "response.created") {
      check(this.response === null, "Duplicate response.created");
      this.response = structuredClone(event.response);
      return;
    }
    check(this.response !== null, "Event before response.created");
    if ("response" in event) {
      check(event.response.id === this.response.id, "Response identity changed");
      const terminal = ["response.completed", "response.incomplete", "response.failed"].includes(event.type);
      if (terminal) {
        check(event.response.status === event.type.slice("response.".length), "Response terminal status disagrees with event");
        check(event.response.output.length === this.items.size, "Terminal response contains unannounced output items");
        for (const [index2, item2] of this.items) {
          const final = event.response.output[index2];
          check(final?.id === item2.id, "Terminal response changed output order");
          if (this.closed.has(index2)) check(canonical(item2) === canonical(final), "Terminal response changed a closed item");
        }
        this.terminal = true;
      }
      this.response = structuredClone(event.response);
      return;
    }
    if (event.type === "error") return;
    if (event.type === "response.output_item.added") {
      check(event.item !== null, "Missing output item");
      check(Number.isInteger(event.output_index) && event.output_index >= 0, "Invalid output index");
      check(!this.items.has(event.output_index) && !this.ids.has(event.item.id), "Duplicate output item");
      this.items.set(event.output_index, structuredClone(event.item));
      this.ids.add(event.item.id);
      return;
    }
    const item = this.items.get(event.output_index);
    check(item, "Event refers to an unknown output item");
    check(!this.closed.has(event.output_index), "Update after output_item.done");
    if (event.type === "response.output_item.done") {
      check(event.item !== null, "Missing output item");
      check(event.item.id === item.id && event.item.type === item.type, "Item identity changed");
      if (item.type === "function_call") {
        check(event.item.type === "function_call" && event.item.arguments === item.arguments, "Final function arguments disagree with deltas");
        check(event.item.call_id === item.call_id && event.item.name === item.name, "Final function identity changed");
      }
      for (const field2 of ["content", "summary"]) {
        if (item[field2]?.length) check(canonical(item[field2]) === canonical(event.item[field2]), `Final ${field2} disagrees with deltas`);
      }
      check(!("status" in event.item) || event.item.status !== "in_progress", "Done item is still in progress");
      this.items.set(event.output_index, structuredClone(event.item));
      this.closed.add(event.output_index);
      return;
    }
    check(event.item_id === item.id, "Item ID disagrees with output index");
    if (event.type === "response.function_call_arguments.delta") {
      check(item.type === "function_call", "Arguments on a non-function item");
      check(!this.closedParts.has(`${item.id}/arguments`), "Arguments after arguments.done");
      item.arguments = (item.arguments ?? "") + event.delta;
      return;
    }
    if (event.type === "response.function_call_arguments.done") {
      check(item.type === "function_call" && item.arguments === event.arguments, "Final function arguments disagree with deltas");
      const key2 = `${item.id}/arguments`;
      check(!this.closedParts.has(key2), "Duplicate arguments.done");
      this.closedParts.add(key2);
      return;
    }
    const summary = "summary_index" in event;
    const index = summary ? event.summary_index : "content_index" in event ? event.content_index : -1;
    check(Number.isInteger(index) && index >= 0, "Invalid content index");
    const parts = summary ? item.summary ??= [] : item.content ??= [];
    const key = `${item.id}/${summary ? "summary" : "content"}/${index}`;
    check(!this.closedParts.has(key), "Update after content part completion");
    if (event.type === "response.content_part.added" || event.type === "response.reasoning_summary_part.added") {
      check(parts[index] === void 0, "Duplicate content part");
      parts[index] = structuredClone(event.part);
      return;
    }
    const part = parts[index];
    check(part, "Delta before content part");
    if (event.type === "response.content_part.done" || event.type === "response.reasoning_summary_part.done") {
      check(canonical(part) === canonical(event.part), "Final content part disagrees with deltas");
      this.closedParts.add(key);
      return;
    }
    if (event.type === "response.output_text.annotation.added") {
      (part.annotations ??= []).push(structuredClone(event.annotation));
      return;
    }
    const field = event.type.startsWith("response.refusal.") ? "refusal" : "text";
    const textKey = `${key}/${field}`;
    if ("delta" in event) {
      check(!this.closedParts.has(textKey), "Text delta after text.done");
      part[field] = (part[field] ?? "") + event.delta;
    } else {
      const final = "text" in event ? event.text : "refusal" in event ? event.refusal : void 0;
      check(final !== void 0 && part[field] === final, "Final text disagrees with deltas");
      check(!this.closedParts.has(textKey), "Duplicate text.done");
      this.closedParts.add(textKey);
    }
  }
  snapshot() {
    if (!this.response) return null;
    if (this.terminal) return structuredClone(this.response);
    return { ...structuredClone(this.response), output: [...this.items.entries()].sort(([a], [b]) => a - b).map(([, item]) => structuredClone(item)) };
  }
  finish() {
    check(this.terminal, "Transport ended before a terminal response");
    return this.snapshot();
  }
};

// ../../vendor/cortico/src/core/generation.ts
var GenerationError = class extends Error {
  constructor(message2, attempts, partial, origin, status = 0, body = "", options) {
    super(message2, options);
    this.attempts = attempts;
    this.partial = partial;
    this.origin = origin;
    this.status = status;
    this.body = body;
    this.name = "GenerationError";
  }
  attempts;
  partial;
  origin;
  status;
  body;
};

// ../../vendor/cortico/src/core/markers.ts
var FOLD_PLACEHOLDER = "[result folded]";
var FOLD_ARGS_PLACEHOLDER = "[arguments folded]";
var OVERSIZE_PLACEHOLDER = "[turn too long, omitted]";
var MISSING_RESULT = "[result missing]";
var MISSING_RESULT_RESTART = "[result missing (process restart)]";
var UNKNOWN_TOOL = "[unknown tool]";
var forkUnknownTool = (name) => `[unknown tool ${name}] This thread wires a subset of the tools. Use the ones listed above.`;
var NOT_EXECUTED_INCOMPLETE = "[not executed: function call incomplete]";
var NOT_EXECUTED_BARRIER = "[not executed: review the preceding tool result first]";
var NOT_EXECUTED_THREAD_ENDED = "[not executed: this thread already ended]";
var NOT_EXECUTED_STREAM_ABORTED = "[not executed: stream aborted mid-response]";
var NOT_EXECUTED_LOOP_STOPPED = "[not executed: main loop stopped]";
var SHUTDOWN_INTERRUPTED = "[tool result unavailable: shutdown interrupted the round]";
var toolFailed = (detail) => `[tool failed] ${detail}`;
var TOOL_FAILED_BAD_ARGS = toolFailed("arguments are not valid JSON");
var eventFrameHeader = (count) => `[${count} new event${count === 1 ? "" : "s"}]`;

// ../../vendor/cortico/src/core/fork.ts
async function runForkLoop(opts) {
  const { id, llm, spec, tools, maxRounds, log } = opts;
  if (opts.turnPolicy) {
    const decision = await opts.turnPolicy();
    if (decision.kind === "silent") return "";
    if (decision.kind === "direct") return decision.text;
  }
  const messages = [...opts.messages];
  const observed = [...messages];
  opts.observeMessages?.(observed);
  const ctx = { role: id, log };
  const schemas = tools.map(({ name, description, parameters }) => ({ name, description, parameters }));
  const wrapUpAt = Math.min(Math.max(1, opts.softRounds ?? maxRounds - 1), Math.max(1, maxRounds - 1));
  const wrapUpHint = opts.wrapUpHint ?? "Wrap up: give your conclusion next round, no more tool calls.";
  let lastContent = "";
  const runRound = async (round) => {
    let draft = new ResponseAccumulator();
    const settledLength = observed.length;
    let generated;
    try {
      generated = await llm.respond(responseRequest(spec, messages, schemas), {
        role: id,
        sessionId: opts.track?.id,
        context: messages,
        nativeSpec: spec,
        onEvent: (event) => {
          if (event.type === "response.created") draft = new ResponseAccumulator();
          draft.accept(event);
          const snapshot = draft.snapshot();
          if (snapshot) {
            observed.splice(settledLength, observed.length - settledLength, ...snapshot.output.map((item) => ({ version: 2, item, context: { responseId: snapshot.id } })));
          }
        }
      });
    } catch (error) {
      if (error instanceof GenerationError) opts.track?.recordAttempts(error.attempts, observed);
      throw error;
    }
    const output = responseRecords(generated.response, generated.origin);
    messages.push(...output);
    observed.splice(settledLength, observed.length - settledLength, ...output);
    opts.track?.recordAttempts(generated.attempts, observed);
    const text2 = output.filter((entry) => entry.item.type === "message").map(textOf).join("");
    if (text2) lastContent = text2;
    const calls = generated.response.output.filter((item) => item.type === "function_call");
    if (!calls.length) return "done";
    let barrier = false;
    for (const [index, call] of calls.entries()) {
      const def = tools.find((tool) => tool.name === call.name);
      let out;
      let ended = false;
      if (barrier) out = NOT_EXECUTED_BARRIER;
      else if (call.status !== "completed") {
        out = NOT_EXECUTED_INCOMPLETE;
        barrier = true;
      } else if (!def) out = forkUnknownTool(call.name);
      else {
        try {
          const args = JSON.parse(call.arguments || "{}");
          const result = await def.handler(args, { ...ctx, callId: call.call_id });
          out = typeof result === "string" ? result : result.text;
          ended = def.endsTurn === true;
        } catch (error) {
          out = toolFailed(error instanceof Error ? error.message : String(error));
        }
        if (def.barrierAfter) barrier = true;
      }
      if (round === wrapUpAt) out += `
[system] ${wrapUpHint}`;
      const receipt = functionResult(call.call_id, out);
      messages.push(receipt);
      observed.push(receipt);
      if (ended || opts.stopWhen?.()) {
        for (const skipped of calls.slice(index + 1)) {
          const receipt2 = functionResult(skipped.call_id, NOT_EXECUTED_THREAD_ENDED);
          messages.push(receipt2);
          observed.push(receipt2);
        }
        return "done";
      }
    }
    return "continue";
  };
  let finished = false;
  for (let round = 1; round <= maxRounds; round++) {
    if (await runRound(round) === "done") {
      finished = true;
      break;
    }
  }
  if (!finished) log.warn("\u5DE5\u5177\u5FAA\u73AF\u8FBE\u5230\u786C\u4E0A\u9650,\u53D6\u6700\u540E\u5185\u5BB9\u4E3A\u7ED3\u679C", { maxRounds });
  if (opts.nudge && !opts.stopWhen?.() && opts.nudge.when(lastContent)) {
    const reminder = message("user", opts.nudge.message);
    messages.push(reminder);
    observed.push(reminder);
    await runRound(maxRounds);
  }
  if (!finished && opts.capNote) lastContent = lastContent ? `${lastContent}

${opts.capNote}` : opts.capNote;
  return lastContent;
}

// ../../vendor/cortico/src/core/blobs.ts
import { createHash as createHash4 } from "node:crypto";
import { existsSync as existsSync8, mkdirSync as mkdirSync6, readdirSync as readdirSync3, readFileSync as readFileSync7, rmSync as rmSync2, statSync as statSync3, writeFileSync as writeFileSync5 } from "node:fs";
import { join as join7 } from "node:path";
var LOG_SCHEME = "log:";
var MEM_SCHEME = "mem:";
var EXT_BY_MIME = {
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/gif": ".gif",
  "image/bmp": ".bmp",
  "image/webp": ".webp",
  "application/pdf": ".pdf",
  "audio/wav": ".wav",
  "audio/mpeg": ".mp3",
  "text/plain": ".txt",
  "application/json": ".json",
  "application/zip": ".zip"
};
var LOG_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
var LOG_PREFIX_RE = /^([0-9a-f]{8,40})(\.[A-Za-z0-9]+)?$/;
var LOG_HASH_CHARS = 20;
function blobScheme(handle) {
  if (handle.startsWith(MEM_SCHEME)) return "mem";
  if (handle.startsWith(LOG_SCHEME)) return "log";
  return null;
}
function mimeOfHandle(handle) {
  const dot = handle.lastIndexOf(".");
  const ext = dot >= 0 ? handle.slice(dot).toLowerCase() : "";
  for (const [mime, e] of Object.entries(EXT_BY_MIME)) if (e === ext) return mime;
  return "application/octet-stream";
}
function blobLine(ref) {
  return `[blob ${ref.handle} ${ref.mime}${ref.name ? ` ${ref.name}` : ""}] ${ref.fallbackText}`;
}
function withBlobLines(text2, refs) {
  if (!refs || refs.length === 0) return text2;
  const lines = refs.map(blobLine).join("\n");
  return text2 ? `${text2}
${lines}` : lines;
}
var LogBlobStore = class {
  dir;
  constructor(dataDir) {
    this.dir = join7(dataDir, "media");
  }
  /** 落盘并返回 `log:` 句柄。 */
  put(bytes, mime) {
    const hash = createHash4("sha256").update(bytes).digest("hex").slice(0, LOG_HASH_CHARS);
    const ext = EXT_BY_MIME[mime] ?? ".bin";
    const name = `${hash}${ext}`;
    const path = join7(this.dir, name);
    if (!existsSync8(path)) {
      if (!existsSync8(this.dir)) mkdirSync6(this.dir, { recursive: true });
      writeFileSync5(path, bytes);
    }
    return `${LOG_SCHEME}${name}`;
  }
  /** 现存份数与占用字节;目录还没建时都是 0。 */
  stat() {
    if (!existsSync8(this.dir)) return { count: 0, bytes: 0 };
    const names = readdirSync3(this.dir);
    return { count: names.length, bytes: names.reduce((sum, name) => sum + statSync3(join7(this.dir, name)).size, 0) };
  }
  /**
   * 删掉目录里的全部附件,返回删掉的份数。附件那一行正文在落库时已写定
   * (句柄、mime 与 fallbackText),此后 read() 返回 null,投递时不再附字节。
   */
  clear() {
    if (!existsSync8(this.dir)) return 0;
    let removed = 0;
    for (const name of readdirSync3(this.dir)) {
      rmSync2(join7(this.dir, name), { force: true });
      removed += 1;
    }
    return removed;
  }
  /** 按句柄取回;句柄不合形状、前缀不唯一或文件不在了返回 null。 */
  read(handle) {
    const name = this.resolveName(handle);
    if (!name) return null;
    try {
      return { bytes: readFileSync7(join7(this.dir, name)), mime: mimeOfHandle(name) };
    } catch {
      return null;
    }
  }
  resolveName(handle) {
    if (!handle.startsWith(LOG_SCHEME)) return null;
    const raw = handle.slice(LOG_SCHEME.length);
    if (!LOG_NAME_RE.test(raw)) return null;
    if (existsSync8(join7(this.dir, raw))) return raw;
    const m = LOG_PREFIX_RE.exec(raw);
    if (!m || !existsSync8(this.dir)) return null;
    const [, prefix, ext] = m;
    const hits = readdirSync3(this.dir).filter((f) => f.startsWith(prefix) && (!ext || f.endsWith(ext)));
    return hits.length === 1 ? hits[0] : null;
  }
};

// ../../vendor/cortico/src/core/timers.ts
import { existsSync as existsSync9, mkdirSync as mkdirSync7, readFileSync as readFileSync8, renameSync as renameSync4, writeFileSync as writeFileSync6 } from "node:fs";
import { dirname as dirname4, join as join8 } from "node:path";
var MAX_TIMEOUT = 2 ** 31 - 1;
var TimerStore = class {
  file;
  log;
  entries = [];
  timers = /* @__PURE__ */ new Map();
  started = false;
  dueHandler = null;
  /** 构造时即读盘,attach 阶段就能 list();到期定时在 start() 才布防。 */
  constructor(dataDir, log = nullLogger()) {
    this.file = join8(dataDir, "timers.json");
    this.log = log;
    this.load();
  }
  onDue(handler) {
    this.dueHandler = handler;
  }
  start() {
    if (this.started) return;
    this.started = true;
    for (const e of [...this.entries]) this.arm(e);
  }
  stop() {
    this.started = false;
    for (const t of this.timers.values()) clearTimeout(t);
    this.timers.clear();
  }
  set(atIso, payload = {}) {
    if (Number.isNaN(Date.parse(atIso))) {
      return { ok: false, error: `could not parse time "${atIso}"` };
    }
    const entry = { id: shortId("wake_"), atIso, payload };
    this.entries.push(entry);
    this.save();
    if (this.started) this.arm(entry, "next-tick");
    return { ok: true, id: entry.id };
  }
  cancel(id) {
    const idx = this.entries.findIndex((e) => e.id === id);
    if (idx < 0) return false;
    this.entries.splice(idx, 1);
    const t = this.timers.get(id);
    if (t) clearTimeout(t);
    this.timers.delete(id);
    this.save();
    return true;
  }
  list() {
    return this.entries;
  }
  clearAll() {
    const n = this.entries.length;
    this.entries = [];
    for (const t of this.timers.values()) clearTimeout(t);
    this.timers.clear();
    this.save();
    if (n > 0) this.log.warn("\u5B9A\u65F6\u5668\u5DF2\u5168\u90E8\u6E05\u9664", { cleared: n });
    return n;
  }
  /** 已到期的条目按 whenDue 立即回调或下一个宏任务回调;start() 用前者。 */
  arm(entry, whenDue = "now") {
    const delay = Date.parse(entry.atIso) - Date.now();
    if (delay <= 0 && whenDue === "now") {
      this.fire(entry.id);
      return;
    }
    const existing = this.timers.get(entry.id);
    if (existing) clearTimeout(existing);
    if (delay > MAX_TIMEOUT) {
      this.timers.set(entry.id, setTimeout(() => this.arm(entry), MAX_TIMEOUT));
    } else {
      this.timers.set(entry.id, setTimeout(() => this.fire(entry.id), Math.max(0, delay)));
    }
  }
  fire(id) {
    if (!this.started) return;
    const idx = this.entries.findIndex((e) => e.id === id);
    if (idx < 0) return;
    const entry = this.entries[idx];
    this.entries.splice(idx, 1);
    const t = this.timers.get(id);
    if (t) clearTimeout(t);
    this.timers.delete(id);
    this.save();
    if (this.dueHandler) this.dueHandler(entry);
    else this.log.warn("\u5B9A\u65F6\u5668\u5230\u671F\u4F46\u65E0\u4EBA\u8BA4\u9886", { id, atIso: entry.atIso });
  }
  load() {
    if (existsSync9(this.file)) {
      try {
        const raw = JSON.parse(readFileSync8(this.file, "utf8"));
        this.entries = Array.isArray(raw) ? raw : [];
      } catch {
        this.log.warn("timers.json\u635F\u574F,\u5DF2\u91CD\u7F6E\u4E3A\u7A7A");
        this.entries = [];
      }
    }
  }
  save() {
    const dir = dirname4(this.file);
    if (!existsSync9(dir)) mkdirSync7(dir, { recursive: true });
    const tmp = this.file + ".tmp";
    writeFileSync6(tmp, JSON.stringify(this.entries, null, 2), "utf8");
    renameSync4(tmp, this.file);
  }
};

// ../../vendor/cortico/src/core/sessions.ts
var CLOSED_KEEP = 8;
var SessionTracker = class {
  timezone;
  onRecord;
  entries = /* @__PURE__ */ new Map();
  listeners = [];
  seq = 0;
  /** onRecord=每次record时把一条持久化流水交出去(UsageLog.append),可选 */
  constructor(timezone, onRecord) {
    this.timezone = timezone;
    this.onRecord = onRecord;
  }
  /** 变化通知(open/record/close都触发;web侧接这里做推送) */
  onChange(cb) {
    this.listeners.push(cb);
  }
  /**
   * 注册一个session。opts.id指定固定id(常驻session用它的声明id);
   * opts.messagesRef=消息数组的惰性引用(查看消息流/条数用)。
   */
  open(role, label, opts) {
    const id = opts?.id ?? `${role}-${++this.seq}`;
    const entry = {
      stats: {
        id,
        role,
        label,
        startedAt: nowIso(this.timezone),
        endedAt: null,
        calls: 0,
        promptTokens: 0,
        completionTokens: 0,
        cacheHitTokens: 0,
        cacheMissTokens: 0,
        reasoningTokens: 0
      },
      messagesRef: opts?.messagesRef ?? null,
      pinned: opts?.id !== void 0
    };
    this.entries.set(id, entry);
    this.pruneClosed();
    this.emit();
    let closed = false;
    return {
      id,
      recordAttempts: (attempts, messagesRef, extra) => {
        if (messagesRef) entry.messagesRef = () => messagesRef;
        for (const source of attempts) {
          const attempt = structuredClone(source);
          if (extra?.outcome === "discarded" && (attempt.outcome === "completed" || attempt.outcome === "incomplete")) attempt.outcome = "discarded";
          const usage = usageCounters(attempt.meters);
          const stats = entry.stats;
          stats.calls++;
          stats.promptTokens += usage.promptTokens;
          stats.completionTokens += usage.completionTokens;
          stats.cacheHitTokens += usage.cacheHitTokens;
          stats.cacheMissTokens += usage.cacheMissTokens;
          stats.reasoningTokens += usage.reasoningTokens ?? 0;
          this.onRecord?.({
            version: 2,
            attempt,
            ts: nowIso(this.timezone, new Date(attempt.startedAt)),
            sessionId: id,
            role: stats.role,
            label: stats.label,
            model: attempt.origin.model,
            ...usage,
            reasoningTokens: usage.reasoningTokens ?? 0,
            failedAfterMs: attempt.elapsedMs,
            ...attempt.requestId ? { requestId: attempt.requestId } : {},
            ...attempt.status !== null ? { status: attempt.status } : {},
            ...attempt.outcome === "completed" || attempt.outcome === "incomplete" ? {} : { outcome: attempt.outcome === "discarded" ? "discarded" : "failed" },
            ...extra?.prefixHash ? { prefixHash: extra.prefixHash } : {}
          });
        }
        this.emit();
      },
      record: (usage, messagesRef, model, extra) => {
        if (closed) return;
        const s = entry.stats;
        s.calls++;
        s.promptTokens += usage.promptTokens;
        s.completionTokens += usage.completionTokens;
        s.cacheHitTokens += usage.cacheHitTokens;
        s.cacheMissTokens += usage.cacheMissTokens;
        s.reasoningTokens += usage.reasoningTokens ?? 0;
        if (messagesRef) entry.messagesRef = () => messagesRef;
        if (this.onRecord) {
          try {
            this.onRecord({
              ts: nowIso(this.timezone),
              sessionId: id,
              role: s.role,
              label: s.label,
              model: model ?? "",
              promptTokens: usage.promptTokens,
              completionTokens: usage.completionTokens,
              cacheHitTokens: usage.cacheHitTokens,
              cacheMissTokens: usage.cacheMissTokens,
              reasoningTokens: usage.reasoningTokens ?? 0,
              ...extra?.prefixHash ? { prefixHash: extra.prefixHash } : {},
              ...extra?.charges ? { charges: structuredClone(extra.charges) } : {}
            });
          } catch {
          }
        }
        this.emit();
      },
      close: () => {
        if (closed) return;
        closed = true;
        entry.stats.endedAt = nowIso(this.timezone);
        this.pruneClosed();
        this.emit();
      }
    };
  }
  /** 全部session统计(进行中在前,新的在前) */
  list() {
    const out = [];
    for (const e of this.entries.values()) {
      const s = e.stats;
      const denom = s.cacheHitTokens + s.cacheMissTokens;
      out.push({
        ...s,
        cacheHitRate: denom > 0 ? s.cacheHitTokens / denom : null,
        messageCount: this.countMessages(e)
      });
    }
    return out.sort((a, b) => {
      const ra = a.endedAt === null ? 0 : 1;
      const rb = b.endedAt === null ? 0 : 1;
      if (ra !== rb) return ra - rb;
      return b.startedAt.localeCompare(a.startedAt);
    });
  }
  /**
   * 统计清零(web运维动作):进行中的session保留条目但usage归零、
   * 计时重置(句柄继续有效);已结束的条目移除。
   */
  reset() {
    for (const [id, e] of [...this.entries]) {
      if (e.stats.endedAt !== null) {
        this.entries.delete(id);
        continue;
      }
      e.stats.calls = 0;
      e.stats.promptTokens = 0;
      e.stats.completionTokens = 0;
      e.stats.cacheHitTokens = 0;
      e.stats.cacheMissTokens = 0;
      e.stats.reasoningTokens = 0;
      e.stats.startedAt = nowIso(this.timezone);
    }
    this.emit();
  }
  /** 某session当前消息流(引用实时序列化);未知id或无引用→null */
  messages(id) {
    const e = this.entries.get(id);
    if (!e?.messagesRef) return null;
    try {
      return e.messagesRef();
    } catch {
      return null;
    }
  }
  countMessages(e) {
    if (!e.messagesRef) return 0;
    try {
      return e.messagesRef().length;
    } catch {
      return 0;
    }
  }
  /** 已结束session只留最近CLOSED_KEEP个(按结束时间;常驻条目永不清) */
  pruneClosed() {
    const closed = [...this.entries.values()].filter((e) => e.stats.endedAt !== null && !e.pinned).sort((a, b) => (b.stats.endedAt ?? "").localeCompare(a.stats.endedAt ?? ""));
    for (const e of closed.slice(CLOSED_KEEP)) {
      this.entries.delete(e.stats.id);
    }
  }
  emit() {
    for (const cb of this.listeners) {
      try {
        cb();
      } catch {
      }
    }
  }
};

// ../../vendor/cortico/src/core/usage-log.ts
import { appendFileSync as appendFileSync5, existsSync as existsSync10, mkdirSync as mkdirSync8, readFileSync as readFileSync9, writeFileSync as writeFileSync7 } from "node:fs";
import { dirname as dirname5 } from "node:path";
var UsageLog = class {
  constructor(file, report = console.error) {
    this.file = file;
    this.report = report;
  }
  file;
  report;
  pending = [];
  error = null;
  reconcile = false;
  append(rec) {
    this.pending.push(structuredClone({ ...rec, version: 2, recordId: rec.recordId ?? rec.attempt?.id ?? crypto.randomUUID() }));
    this.flush();
  }
  flush() {
    if (!this.pending.length) return;
    try {
      mkdirSync8(dirname5(this.file), { recursive: true });
      if (this.reconcile) {
        const ids = new Set(this.readDisk().map((record2) => record2.recordId ?? record2.attempt?.id));
        this.pending = this.pending.filter((record2) => !ids.has(record2.recordId));
        this.reconcile = false;
      }
      while (this.pending.length) {
        appendFileSync5(this.file, "\n" + JSON.stringify(this.pending[0]) + "\n", "utf8");
        this.pending.shift();
      }
      this.error = null;
    } catch (error) {
      this.reconcile = true;
      this.note(error);
    }
  }
  status() {
    return { pending: this.pending.length, error: this.error };
  }
  note(error) {
    const message2 = `Usage ledger ${this.file}: ${String(error)}`;
    if (message2 !== this.error) this.report(message2);
    this.error = message2;
  }
  readDisk() {
    if (!existsSync10(this.file)) return [];
    const out = [];
    const seen = /* @__PURE__ */ new Set();
    let damaged = 0;
    for (const line of readFileSync9(this.file, "utf8").split(/\r?\n/)) {
      if (!line.trim()) continue;
      let record2;
      try {
        record2 = JSON.parse(line);
      } catch {
        damaged++;
        continue;
      }
      if (!record2 || record2.version !== 2 || typeof record2.ts !== "string") {
        damaged++;
        continue;
      }
      const id = record2.recordId ?? record2.attempt?.id;
      if (id && seen.has(id)) continue;
      if (id) seen.add(id);
      out.push(record2);
    }
    if (damaged) this.note(`${damaged} damaged ledger lines retained on disk`);
    return out;
  }
  readAll() {
    let records = [];
    try {
      records = this.readDisk();
    } catch (error) {
      this.note(error);
    }
    const ids = new Set(records.map((record2) => record2.recordId ?? record2.attempt?.id));
    return [...records, ...this.pending.filter((record2) => !ids.has(record2.recordId))];
  }
  count() {
    return this.readAll().length;
  }
  clear() {
    const count = this.count();
    mkdirSync8(dirname5(this.file), { recursive: true });
    writeFileSync7(this.file, "", "utf8");
    this.pending = [];
    this.error = null;
    return count;
  }
};

// ../../vendor/cortico/src/core/tool-log.ts
import { appendFileSync as appendFileSync6, existsSync as existsSync11, mkdirSync as mkdirSync9, statSync as statSync4, writeFileSync as writeFileSync8 } from "node:fs";
import { dirname as dirname6 } from "node:path";
var RECEIPT_CHARS = 600;
var ToolCallLog = class {
  constructor(file, opts = {}) {
    this.file = file;
    this.timezone = opts.timezone ?? "Asia/Shanghai";
    this.run = opts.run ?? "r-none";
  }
  file;
  seq = 0;
  dirReady = false;
  timezone;
  run;
  write(input) {
    const anchors = currentAnchors();
    const entry = {
      seq: ++this.seq,
      ts: nowIso(this.timezone),
      run: this.run,
      ...anchors.round !== void 0 ? { round: anchors.round } : {},
      ...anchors.resp !== void 0 ? { resp: anchors.resp } : {},
      ...anchors.call !== void 0 ? { call: anchors.call } : {},
      ...input,
      receipt: input.receipt.slice(0, RECEIPT_CHARS)
    };
    this.append(entry);
    return entry;
  }
  /** 控制台存储清单的规模描述 */
  stat() {
    const size = this.bytes();
    return `${this.seq}\u6761 / ${size === null ? "(\u65E0\u6587\u4EF6)" : `${(size / 1024).toFixed(1)}KB`}`;
  }
  clear() {
    if (!this.file || !existsSync11(this.file)) return;
    try {
      writeFileSync8(this.file, "", "utf8");
    } catch {
    }
  }
  bytes() {
    if (!this.file || !existsSync11(this.file)) return null;
    try {
      return statSync4(this.file).size;
    } catch {
      return null;
    }
  }
  append(entry) {
    if (!this.file) return;
    try {
      if (!this.dirReady) {
        mkdirSync9(dirname6(this.file), { recursive: true });
        this.dirReady = true;
      }
      appendFileSync6(this.file, `${JSON.stringify(entry)}
`, "utf8");
    } catch {
    }
  }
};
function recordToolCall(log, role, tool, args, startedAt, out, mod) {
  if (!log) return;
  log.write({
    role,
    tool,
    ...mod ? { mod } : {},
    args,
    durMs: Date.now() - startedAt,
    chars: out.text.length,
    receipt: out.text,
    ...out.failed ? { failed: true } : {},
    ...out.blobs?.length ? { blobs: out.blobs.length } : {}
  });
}

// ../../vendor/cortico/src/core/transcript.ts
import { appendFileSync as appendFileSync7, mkdirSync as mkdirSync10 } from "node:fs";
import { dirname as dirname7 } from "node:path";
var Transcript = class {
  constructor(file, opts = {}) {
    this.file = file;
    this.run = opts.run ?? "r-none";
    this.timezone = opts.timezone ?? "Asia/Shanghai";
  }
  file;
  run;
  timezone;
  dirReady = false;
  item(record2, index) {
    const anchors = currentAnchors();
    this.append({
      kind: "item",
      ts: record2.context.ts ?? nowIso(this.timezone),
      run: this.run,
      ...anchors.sess !== void 0 ? { sess: anchors.sess } : {},
      ...anchors.round !== void 0 ? { round: anchors.round } : {},
      index,
      item: record2.item,
      context: record2.context
    });
  }
  boundary(event, data) {
    const anchors = currentAnchors();
    this.append({
      kind: "boundary",
      ts: nowIso(this.timezone),
      run: this.run,
      ...anchors.sess !== void 0 ? { sess: anchors.sess } : {},
      ...anchors.round !== void 0 ? { round: anchors.round } : {},
      event,
      data
    });
  }
  append(record2) {
    if (!this.file) return;
    try {
      if (!this.dirReady) {
        mkdirSync10(dirname7(this.file), { recursive: true });
        this.dirReady = true;
      }
      appendFileSync7(this.file, `${JSON.stringify(record2)}
`, "utf8");
    } catch {
    }
  }
};

// ../../vendor/cortico/src/core/prefix.ts
import { existsSync as existsSync12, readFileSync as readFileSync10 } from "node:fs";
import { join as join9 } from "node:path";

// ../../vendor/cortico/src/core/template.ts
var PLACEHOLDER = /\{\{\s*([\w.]+)\s*(?:\|([^}]*))?\}\}/g;
function renderTemplate(template, vars) {
  return template.replace(PLACEHOLDER, (whole, name, fallback) => {
    if (!Object.prototype.hasOwnProperty.call(vars, name)) return whole;
    const value = vars[name] ?? "";
    if (value !== "") return value;
    return fallback === void 0 ? "" : fallback.trim();
  });
}

// ../../vendor/cortico/src/core/prefix.ts
function envPromptOverridePath(dir, worldId) {
  return join9(dir, "worlds", worldId, "ENV_PROMPT.md");
}
function envPromptTemplateSource(doc, worldId, dirs) {
  for (const [dir, origin] of [
    [dirs?.deploymentDir, "deployment"],
    [dirs?.packageDir, "package"]
  ]) {
    if (!dir) continue;
    const override = envPromptOverridePath(dir, worldId);
    if (existsSync12(override)) return { path: override, origin };
  }
  return { path: doc.path, origin: "module" };
}
function envPromptDocOf(mod) {
  let decl;
  try {
    decl = mod.console?.();
  } catch {
    return void 0;
  }
  return decl?.promptDocs?.find((doc) => doc.role === "envPrompt");
}
async function renderWorldEnvPrompt(mod, dirs) {
  const vars = await mod.envPromptVars();
  const doc = vars === null ? void 0 : envPromptDocOf(mod);
  if (!doc) return { text: "" };
  const { path } = envPromptTemplateSource(doc, mod.id, dirs);
  const text2 = renderTemplate(readFileSync10(path, "utf8"), vars ?? {}).trim();
  return text2 ? { text: text2, sourceKey: doc.key } : { text: "" };
}
async function collectWorldContexts(worlds, dirs) {
  const sorted = [...worlds].sort((a, b) => a.id.localeCompare(b.id));
  return Promise.all(
    sorted.map(async (mod) => {
      const { text: text2, sourceKey } = await renderWorldEnvPrompt(mod, dirs);
      return {
        id: mod.id,
        envPrompt: text2,
        ...sourceKey ? { sourceKey } : {}
      };
    })
  );
}
async function assembleSystemSegments(deps) {
  const { persona, worlds, now, timezone, dirs } = deps;
  return persona.systemSegments({
    now,
    timezone,
    worlds: await collectWorldContexts(worlds, dirs)
  });
}
async function assembleSystem(deps) {
  const segments = await assembleSystemSegments(deps);
  return segments.map((segment) => segment.text).join("");
}

// ../../vendor/cortico/src/core/truncate.ts
var FOLD_THRESHOLD = 600;
function responseKey(entry) {
  return entry.context.responseId ?? null;
}
function rebuildTail(tail, budgetTokens, estimate = estimateMessagesTokens) {
  if (!tail.length) return [];
  const calls = new Set(tail.flatMap(({ item }) => item.type === "function_call" ? [item.call_id] : []));
  const folded = tail.map((entry) => {
    const item = entry.item;
    if (item.type === "function_call" && item.arguments.length > FOLD_THRESHOLD) {
      return { ...entry, item: { ...item, arguments: FOLD_ARGS_PLACEHOLDER } };
    }
    if (item.type === "function_call_output" && calls.has(item.call_id) && textOf(entry).length > FOLD_THRESHOLD) {
      return withText(entry, FOLD_PLACEHOLDER);
    }
    return entry;
  });
  const oversized = /* @__PURE__ */ new Set();
  let total = 0;
  let budgetStart = 0;
  for (let index = folded.length - 1; index >= 0; index--) {
    const tokens = estimate([folded[index]]);
    if (tokens > budgetTokens && index < folded.length - 1) {
      oversized.add(index);
      continue;
    }
    if (total + tokens > budgetTokens && total > 0) {
      budgetStart = index + 1;
      break;
    }
    total += tokens;
  }
  let start = folded.findIndex((entry, index) => index >= budgetStart && hasRole(entry, "user"));
  if (start < 0) start = budgetStart;
  const key = responseKey(folded[start]);
  while (start > 0 && key !== null && responseKey(folded[start - 1]) === key) start--;
  const kept = folded.slice(start).map((entry, offset) => {
    if (!oversized.has(start + offset)) return entry;
    const item = entry.item;
    if (item.type === "message" || item.type === "function_call_output") return withText(entry, OVERSIZE_PLACEHOLDER);
    if (item.type === "reasoning") return { ...entry, item: { type: "reasoning", id: item.id ?? "rs_folded", summary: [{ type: "summary_text", text: OVERSIZE_PLACEHOLDER }] } };
    return entry;
  });
  return fixPairing(kept);
}
function fixPairing(records) {
  const out = [];
  const open = /* @__PURE__ */ new Set();
  let group = null;
  const close = () => {
    for (const id of open) out.push(functionResult(id, MISSING_RESULT));
    open.clear();
  };
  for (const entry of records) {
    const item = entry.item;
    if (item.type === "function_call_output") {
      if (open.delete(item.call_id)) out.push(entry);
      continue;
    }
    const key = responseKey(entry);
    if (hasRole(entry, "user") || hasRole(entry, "system") || hasRole(entry, "developer") || key !== null && group !== null && key !== group) close();
    if (key !== null) group = key;
    out.push(entry);
    if (item.type === "function_call") open.add(item.call_id);
  }
  close();
  return out;
}

// ../../vendor/cortico/src/core/loop.ts
function toolSignature(mod) {
  return mod.tools().map((t) => t.name).join(",");
}
var DEFAULT_RESUBMIT = { maxConsecutive: 2, maxPerBatch: 4, backoffMs: [2e3, 1e4] };
var LARGE_RESULT_WARN_CHARS = 8e3;
var EXTERNAL_EVENT_FRAME = "external_event_frame";
var STALL_WINDOW_MS = 36e5;
var STALL_ALERT_THRESHOLD = 5;
var RESERVED_FRAME_NAMES = /* @__PURE__ */ new Set([EXTERNAL_EVENT_FRAME]);
function frameEventRefs(events, base) {
  let start = base;
  return events.map((e) => {
    const ref = { cursor: e.cursor, ts: e.ts, type: e.type, source: e.source, start, chars: e.text.length };
    if (e.tags?.length) ref.tags = e.tags;
    start += e.text.length + 1;
    return ref;
  });
}
function eventBlobs(events) {
  return events.flatMap((e) => e.blobs ?? []);
}
var MAX_REQUEUE = 200;
var WATERMARK_AUDIT_INTERVAL_MS = 12e4;
var WATERMARK_STALL_MS = 3e5;
var WATERMARK_RESTATE_MS = [15 * 6e4, 60 * 6e4];
var RENDER_DEADLINE_MS = 3e3;
var RENDER_TIMED_OUT = /* @__PURE__ */ Symbol("render-timed-out");
var MainLoop = class {
  d;
  running = false;
  stopFn = null;
  toolDefs = [];
  batchesHandled = 0;
  roundsLastBatch = 0;
  /** 跨唤醒批次单调递增的轮序号;每建一份工具 ctx 加一,透传给 ToolCallContext.round */
  roundSeq = 0;
  lastUsage = null;
  /** 主session的观察句柄(tracker未接线时null) */
  mainTrack = null;
  /** 截断是单实例事务；手动触发和阈值检查并发时复用同一个Promise。 */
  truncatePromise = null;
  /** 截断与前缀重载共用的维护串行链，避免两个 session.reset 互相覆盖。 */
  maintenanceChain = Promise.resolve();
  prefixReloadPromise = null;
  clearSessionPromise = null;
  /** 在一轮处理中请求的前缀重载与清空，等自然回合边界再释放。 */
  releaseAtBoundary = [];
  /** 当前正在处理一个事件批；手动交接必须等到该批自然结束，不能重置半轮session。 */
  processingBatch = false;
  handoffRequested = false;
  /** onDelivery 执行期间（含其 Promise 完成前），injectInternal 的即时项加入当前批，不经过总线。 */
  deliveryCollector = null;
  /** 已投递但前面仍有外部缺口的游标；水位只越过连续前缀。 */
  deliveredCursors = /* @__PURE__ */ new Set();
  /**
   * 已由候选处理函数处理的原始归档位置，包含选中及丢弃项。
   * 未处理的归档项阻止水位越过；该集合不持久化，重启时根据已生成事件的来源引用恢复。
   */
  settledArchives = /* @__PURE__ */ new Set();
  /**
   * 窗口内的 LLM 失败时刻，单位为毫秒。保存在 state.data.llmStall，
   * 跨重启保留；恢复时通知 Persona，World 可按时间窗口查询。
   */
  get stallAt() {
    return this.d.state.data.llmStall.at;
  }
  /** 当前这串连续失败的第一次发生时刻;0 = 此刻没在失败串里 */
  get stallSince() {
    return this.d.state.data.llmStall.since;
  }
  set stallSince(at) {
    this.d.state.data.llmStall.since = at;
  }
  /** 当前连续失败是否已告警；恢复后解除，同一串不重复告警。 */
  stallAlarmActive = false;
  /** run() 启动水位巡查，stop() 取消。 */
  watermarkAudit = null;
  /**
   * 已报告停滞的水位，-1 表示未报告。水位推进后重置；
   * 同一水位按 WATERMARK_RESTATE_MS 间隔再次报告。
   */
  watermarkStallAt = -1;
  /** 当前这次停滞的首报时刻(退避重报的基准) */
  watermarkStallSince = 0;
  /** 首报时的积压量，后续报告据此计算增长量。 */
  watermarkStallBehind = 0;
  /** 同一次停滞已报次数(首报计 1) */
  watermarkStallReports = 0;
  /**
   * 最近成功请求的输入与输出 token 总数，覆盖前 records 条（含响应）。
   * 新增条目使用本地估算，下次成功后更新计数；上下文整体重写后失效。
   */
  anchor = null;
  /** 当前 system 前缀和工具表采用的可见 World 集合。 */
  appliedVisibleWorlds = null;
  /** 当前前缀中各可见 World 的工具签名，用于检测工具表漂移。 */
  appliedWorldTools = /* @__PURE__ */ new Map();
  /** 当前模型轮；非 reasoning 增量一旦外流，本轮不再接受自动抢占。 */
  currentRound = null;
  /** 每次 stop 都使此前捕获的异步 continuation 永久失效。 */
  generation = 0;
  stopped = false;
  /** 主循环退出或 drain 超时后封住持久化出口，迟到的 provider/tool promise 只能在内存中结束。 */
  sealed = false;
  /** 已落库、但尚未配齐结果的当前 assistant 工具调用。 */
  pendingToolCalls = /* @__PURE__ */ new Set();
  /** stop() 提前结束重试等待，由 active() 决定退出。 */
  backoffWake = null;
  /**
   * 工具信号合并关机信号与当前模型调用信号。
   * 自动抢占仅发生在没有外部输出、尚未执行工具时；工具执行期间仅关机或循环换代会取消。
   */
  shutdown = new AbortController();
  constructor(deps) {
    this.d = deps;
    deps.session.onReset(() => {
      this.anchor = null;
    });
  }
  active(generation) {
    return !this.stopped && !this.sealed && this.generation === generation;
  }
  activeNow() {
    return this.active(this.generation);
  }
  /** 尝试取消尚未输出的当前模型调用；无可取消调用时返回 false。 */
  abortCurrentRound() {
    if (!this.activeNow()) return false;
    const round = this.currentRound;
    if (!round || round.externalized) return false;
    round.abortReason = "preempt";
    round.controller.abort(new Error("\u6A21\u578B\u8F6E\u88AB\u65B0\u8F93\u5165\u62A2\u5360"));
    return true;
  }
  /**
   * 工具 schema 与 handler 来自 session 声明；此处去重、稳定排序并按名称过滤隐藏 World 工具。
   * World 之间、与 Persona 声明的自有工具及保留帧重名时，装配层拒绝挂载。
   * Persona 未声明自有工具名时，此处保留先注册项并告警。
   */
  assembleTools(hiddenToolNames) {
    const { decl, log } = this.d;
    const defs = [];
    const seen = /* @__PURE__ */ new Set();
    for (const def of decl.tools()) {
      if (RESERVED_FRAME_NAMES.has(def.name)) {
        log.warn(`\u5DE5\u5177\u540D\u4E0E\u4FDD\u7559\u5E27\u649E\u540D,\u62D2\u7EDD\u6CE8\u518C: ${def.name}`);
        continue;
      }
      if (hiddenToolNames.has(def.name)) continue;
      if (seen.has(def.name)) {
        log.warn(`\u5DE5\u5177\u91CD\u540D,\u8DF3\u8FC7\u540E\u8005: ${def.name}`);
        continue;
      }
      if (def.tags.length === 0 && !this.warnedUntagged.has(def.name)) {
        this.warnedUntagged.add(def.name);
        log.warn(`\u5DE5\u5177\u672A\u5206\u7C7B(tags\u4E3A\u7A7A,\u4E0D\u53C2\u4E0E\u4EFB\u4F55tag\u8FC7\u6EE4): ${def.name}`);
      }
      seen.add(def.name);
      defs.push(def);
    }
    this.toolDefs = defs;
  }
  /** 空 tags 只报告一次。 */
  warnedUntagged = /* @__PURE__ */ new Set();
  /** 按当前可见性重建工具表并记录所用 World 集合；重启恢复前缀时也执行。 */
  bindWorlds() {
    const { worlds } = this.d;
    const visible = worlds.visible();
    const visibleIds = new Set(visible.map((m) => m.id));
    const hiddenToolNames = new Set(
      worlds.all().filter((m) => !visibleIds.has(m.id)).flatMap((m) => m.tools().map((t) => t.name))
    );
    this.assembleTools(hiddenToolNames);
    this.appliedVisibleWorlds = visibleIds;
    this.appliedWorldTools = new Map(visible.map((m) => [m.id, toolSignature(m)]));
    return visible;
  }
  /**
   * 组装 system 前缀,并在同一时刻换成匹配的工具表。两者同属请求缓存前缀,
   * 必须同步更新。
   */
  async buildSystem() {
    const { persona, cfg, dirs } = this.d;
    const content = await assembleSystem({
      persona,
      worlds: this.bindWorlds(),
      now: /* @__PURE__ */ new Date(),
      timezone: cfg.timezone,
      dirs
    });
    return message("system", content);
  }
  /**
   * 在持久上下文的 system 消息后插入合成开头，生成请求与快照使用的副本。
   * 继承快照的 fork 保留相同的请求前缀；开头为空时仅复制原上下文。
   */
  outboundMessages() {
    const msgs = this.d.session.records;
    const head = this.sessionHead();
    if (head.length === 0) return [...msgs];
    let at = 0;
    while (at < msgs.length && hasRole(msgs[at], "system")) at++;
    return [...msgs.slice(0, at), ...head, ...msgs.slice(at)];
  }
  /**
   * Persona 的合成开头,每次现取:system 与 developer 项丢弃,工具配对补齐,全部带不落盘标记。
   * Persona 没提供或抛错时为空。
   */
  sessionHead() {
    const { persona, log } = this.d;
    let items;
    try {
      items = persona.sessionHead?.() ?? [];
    } catch (e) {
      log.warn("sessionHead \u8BFB\u53D6\u5931\u8D25,\u672C\u6B21\u4E0D\u6CE8\u5165", { err: e });
      return [];
    }
    const kept = items.filter((item) => !(item.type === "message" && (item.role === "system" || item.role === "developer")));
    if (kept.length !== items.length) log.warn("sessionHead \u91CC\u7684 system/developer \u9879\u5DF2\u4E22\u5F03", { dropped: items.length - kept.length });
    return fixPairing(kept.map((item) => record(item, { head: true }))).map((entry) => entry.context.head ? entry : { ...entry, context: { ...entry.context, head: true } });
  }
  /**
   * 比较当前 World 可见性及工具名称与构建前缀时的记录，供控制台提示重载。
   * 工具名可同步读取，因此用它检测 World 功能变化，不直接读取异步环境模板。
   */
  modulePrefixDrift() {
    const applied = this.appliedVisibleWorlds;
    if (!applied) return [];
    const visible = new Map(this.d.worlds.visible().map((m) => [m.id, m]));
    return this.d.worlds.all().map((m) => m.id).filter((id) => {
      const mod = visible.get(id);
      if (applied.has(id) !== !!mod) return true;
      return !!mod && this.appliedWorldTools.get(id) !== toolSignature(mod);
    });
  }
  /** 工具回执落库:附件内部化,每份的文本形态接在正文后。 */
  toolResult(callId, out) {
    const blobs = this.d.blobs.intern(out.blobs);
    return functionResult(callId, withBlobLines(out.text, blobs), blobs ? { blobs } : {});
  }
  /** 一轮结束时先通知 Persona，再通知可见 World。 */
  finishTurn() {
    if (!this.activeNow()) return;
    const { persona, worlds, log } = this.d;
    try {
      persona.onTurnEnded?.();
    } catch (e) {
      log.warn("onTurnEnded\u94A9\u5B50\u5F02\u5E38", { err: e });
    }
    for (const m of worlds.visible()) {
      try {
        m.onTurnEnded?.();
      } catch (e) {
        log.warn("World \u56DE\u5408\u6536\u675F\u94A9\u5B50\u5F02\u5E38", { id: m.id, err: e });
      }
    }
  }
  /** 外部正文落在上下文的哪个区(声明里没写=工具回执区)。 */
  eventDelivery() {
    return this.d.decl.eventDelivery ?? "tool";
  }
  /**
   * 将一批事件写入主 session。即时事件在前，候选生成内容与延迟渲染内容在后。
   * 候选按 source、origin 和处理函数分组，再按来源项在批次中的顺序生成正文。
   * 正文归档后调用并等待 onDelivery；钩子完成前注入的内部项追加到内部行末尾、外部正文之前。
   * 内部行合成一条 user 消息；外部正文按 eventDelivery 进入合成工具回执或同一条 user 消息。
   */
  async deliverBatch(batch, generation) {
    if (!this.active(generation)) return false;
    const { session, persona, store, cfg, log } = this.d;
    const projections = this.prepareCandidateProjections(batch, generation);
    if (!this.active(generation)) return false;
    for (const item of batch) {
      for (const event of item.candidate?.sourceEvents ?? []) this.settledArchives.add(event.cursor);
    }
    const delivered = [];
    for (const item of batch) {
      if (item.event) delivered.push(item.event);
    }
    for (let index = 0; index < batch.length; index++) {
      for (const projection of projections.get(index) ?? []) {
        delivered.push(store.append({
          ...projection.event,
          ts: nowIso(cfg.timezone),
          source: projection.source,
          origin: projection.origin,
          contextDelivery: "deliver",
          meta: {
            ...projection.event.meta,
            sourceCursors: projection.sourceCursors
          }
        }));
      }
      const deferred = batch[index].deferred;
      if (!deferred) continue;
      const rendered = await this.renderDeferred(deferred, generation);
      if (!this.active(generation)) return false;
      if (rendered === null) continue;
      const body = typeof rendered === "string" ? { text: rendered } : rendered;
      const blobs = this.d.blobs.intern(body.blobs);
      delivered.push(store.append({
        type: deferred.type,
        ts: nowIso(cfg.timezone),
        source: deferred.source,
        origin: deferred.origin,
        contextDelivery: "deliver",
        text: withBlobLines(body.text, blobs),
        ...blobs ? { blobs } : {},
        senderKey: deferred.senderKey,
        meta: deferred.meta,
        tags: deferred.tags
      }));
    }
    if (!this.active(generation)) return false;
    if (delivered.length > 0) {
      const injected = [];
      this.deliveryCollector = injected;
      try {
        const pending = persona.onDelivery?.({ events: [...delivered] });
        if (pending) await pending;
      } catch (e) {
        log.warn("onDelivery\u94A9\u5B50\u5F02\u5E38", { err: e });
      } finally {
        this.deliveryCollector = null;
      }
      delivered.push(...injected);
    }
    const lines = [];
    const events = [];
    const internals = [];
    let ephemeralCount = 0;
    for (const e of delivered) {
      if (e.origin === "internal") {
        lines.push(e.text);
        internals.push(e);
        if (e.ephemeral) ephemeralCount++;
      } else events.push(e);
    }
    const inUser = this.eventDelivery() === "user";
    if (events.length > 0 && inUser) lines.push(renderEventLines(events));
    const ephemeral = ephemeralCount > 0 && ephemeralCount === internals.length && events.length === 0;
    if (!this.active(generation)) return false;
    this.dropEphemeral(generation);
    if (lines.length > 0) {
      const msg = message("user", lines.join("\n"));
      if (ephemeral) msg.context.ephemeral = true;
      if (events.length > 0 && inUser) {
        const base = lines.slice(0, -1).reduce((n, l) => n + l.length + 1, 0);
        msg.context.frame = { events: frameEventRefs(events, base) };
      }
      const blobs = eventBlobs(inUser ? [...internals, ...events] : internals);
      if (blobs.length > 0) msg.context.blobs = blobs;
      session.append(msg);
    }
    if (events.length > 0 && !inUser) this.appendEventFrame(events, generation);
    this.noteHandled(delivered, generation);
    const changed = lines.length > 0 || events.length > 0;
    if (changed) this.batchesHandled++;
    return changed;
  }
  /** 候选选择由来源 World 决定；Core 组批、校验来源引用并收集输出。 */
  prepareCandidateProjections(batch, generation) {
    const groups = [];
    for (let batchIndex = 0; batchIndex < batch.length; batchIndex++) {
      const candidate = batch[batchIndex].candidate;
      if (!candidate) continue;
      let group = groups.find((value) => value.source === candidate.source && value.origin === candidate.origin && value.project === candidate.project);
      if (!group) {
        group = { source: candidate.source, origin: candidate.origin, project: candidate.project, entries: [] };
        groups.push(group);
      }
      group.entries.push({ batchIndex, candidate });
    }
    const prepared = /* @__PURE__ */ new Map();
    for (const group of groups) {
      try {
        const projected = group.project(group.entries.map((entry) => entry.candidate));
        if (!this.active(generation)) return /* @__PURE__ */ new Map();
        const claimed = /* @__PURE__ */ new Set();
        for (const projection of projected) {
          const indexes = [...new Set(projection.candidateIndexes)].sort((a, b) => a - b);
          const invalid = indexes.length === 0 || indexes.some((index) => !Number.isInteger(index) || index < 0 || index >= group.entries.length || claimed.has(index));
          if (invalid) {
            this.d.log.warn("\u5019\u9009\u6295\u5F71\u542B\u65E0\u6548\u6216\u91CD\u590D\u6E90\u5F15\u7528,\u5DF2\u8DF3\u8FC7\u6574\u6761\u6295\u5F71", { source: group.source });
            continue;
          }
          for (const index of indexes) claimed.add(index);
          const anchor = group.entries[indexes[0]].batchIndex;
          const sourceCursors = indexes.flatMap((index) => group.entries[index].candidate.sourceEvents.map((event) => event.cursor));
          const list = prepared.get(anchor) ?? [];
          list.push({
            source: group.source,
            origin: group.origin,
            event: projection.event,
            sourceCursors
          });
          prepared.set(anchor, list);
        }
      } catch (error) {
        this.d.log.warn("\u5019\u9009\u6295\u5F71\u5931\u8D25,\u672C\u6279\u5019\u9009\u53EA\u4FDD\u7559\u5F52\u6863", {
          source: group.source,
          err: error
        });
      }
    }
    return prepared;
  }
  /** 每批投递前删除带 ephemeral 标记的旧消息；重启读回的标记同样有效。 */
  dropEphemeral(generation) {
    if (!this.active(generation)) return;
    const { session } = this.d;
    if (!session.records.some((m) => m.context.ephemeral)) return;
    const kept = session.records.filter((m) => !m.context.ephemeral);
    const dropped = session.records.length - kept.length;
    session.reset(kept);
    this.d.transcript?.boundary("ephemeral-drop", { dropped });
  }
  /** 延迟渲染应读取当前状态；null、超时或异常均不归档、不投递，超时与异常记录日志。 */
  async renderDeferred(spec, generation) {
    if (!this.active(generation)) return null;
    const { log } = this.d;
    let timer = null;
    try {
      const timeout = new Promise((resolve2) => {
        timer = setTimeout(() => resolve2(RENDER_TIMED_OUT), RENDER_DEADLINE_MS);
      });
      const out = await Promise.race([Promise.resolve(spec.render()), timeout]);
      if (!this.active(generation)) return null;
      if (out === RENDER_TIMED_OUT) {
        log.warn("\u5EF6\u8FDF\u6E32\u67D3\u8D85\u65F6\uFF0C\u8BE5\u9879\u672A\u5F52\u6863\u3001\u672A\u6295\u9012", { type: spec.type, source: spec.source });
        return null;
      }
      return out;
    } catch (e) {
      log.warn("\u5EF6\u8FDF\u6E32\u67D3\u5931\u8D25\uFF0C\u8BE5\u9879\u672A\u5F52\u6863\u3001\u672A\u6295\u9012", { type: spec.type, source: spec.source, err: e });
      return null;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }
  /**
   * 以合成调用及回执承载外部正文，不新增模型请求。
   * 该模式下 user 消息仅承载内部文本。
   */
  appendEventFrame(events, generation) {
    if (!this.active(generation)) return;
    const { session } = this.d;
    const id = `evf_${events[events.length - 1].cursor}`;
    session.append(functionCall(id, EXTERNAL_EVENT_FRAME, "{}"));
    const header = eventFrameHeader(events.length);
    const blobs = eventBlobs(events);
    session.append(functionResult(id, [header, renderEventLines(events)].join("\n"), {
      frame: { events: frameEventRefs(events, header.length + 1) },
      ...blobs.length > 0 ? { blobs } : {}
    }));
  }
  /**
   * 丢弃模型返回的保留帧调用并记录日志，其余调用照常执行。
   * 删除后没有工具调用的响应按自然结束处理。
   */
  dropReservedCalls(records) {
    return records.filter((entry) => {
      const item = entry.item;
      if (item.type !== "function_call" || !RESERVED_FRAME_NAMES.has(item.name)) return true;
      this.d.log.info("\u6A21\u578B\u4EFF\u9020\u4FDD\u7559\u5E27\u8C03\u7528,\u5DF2\u4E22\u5F03", { name: item.name, callId: item.call_id });
      return false;
    });
  }
  /**
   * 投递水位仅推进已了结事件的连续前缀，不跨越未投递外部事件。遍历和推进均使用存储位置游标，不使用信封自报的 cursor。
   */
  noteHandled(delivered, generation) {
    if (!this.active(generation)) return;
    const { state, store } = this.d;
    for (const event of delivered) this.deliveredCursors.add(event.cursor);
    let top = state.data.lastDeliveredCursor;
    const latest = store.latestCursor();
    for (let c = top + 1; c <= latest; c++) {
      const next = store.get(c);
      if (next) {
        const skippable = next.origin === "internal" || next.contextDelivery === "archive-only" && this.settledArchives.has(c);
        if (!skippable && !this.deliveredCursors.has(c)) break;
      }
      this.deliveredCursors.delete(c);
      this.settledArchives.delete(c);
      top = c;
    }
    if (top === state.data.lastDeliveredCursor) return;
    state.data.lastDeliveredCursor = top;
    state.save();
  }
  /** session 开场时调用 Persona 钩子；未注入时不添加开场文本。 */
  pushOpening(reason) {
    const { persona, log } = this.d;
    try {
      persona.onOpening?.({ reason });
    } catch (e) {
      log.warn("onOpening\u94A9\u5B50\u5F02\u5E38", { err: e });
    }
  }
  /**
   * 重启时补投水位之后的外部事件；内部事件不跨重启投递。
   * archive-only 已被投影引用则不重复投递，未被引用则按原文补投。超过条数上限时只入队最近一段，更早事件结清水位。
   */
  requeueUndelivered() {
    const { bus, state, store, log } = this.d;
    const from = state.data.lastDeliveredCursor + 1;
    if (from > store.latestCursor()) {
      this.noteHandled([], this.generation);
      return;
    }
    const after = store.range({ fromCursor: from });
    const referenced = /* @__PURE__ */ new Set();
    for (const event of after) {
      if (event.contextDelivery !== "deliver") continue;
      const cursors = event.meta?.sourceCursors;
      if (!Array.isArray(cursors)) continue;
      for (const c of cursors) if (typeof c === "number") referenced.add(c);
    }
    for (const c of referenced) this.settledArchives.add(c);
    this.noteHandled([], this.generation);
    const pending = after.filter((event) => event.origin === "external" && (event.contextDelivery !== "archive-only" || !referenced.has(event.cursor)));
    if (pending.length === 0) return;
    const skipped = Math.max(0, pending.length - MAX_REQUEUE);
    const kept = skipped > 0 ? pending.slice(skipped) : pending;
    if (skipped > 0) {
      const stale = pending.slice(0, skipped);
      state.data.lastDeliveredCursor = Math.max(state.data.lastDeliveredCursor, kept[0].cursor - 1);
      state.save();
      log.warn("\u91CD\u542F\u8865\u6295\u8D85\u8FC7\u4E0A\u9650,\u66F4\u65E9\u7684\u4E00\u6BB5\u6309\u4E0A\u4E00\u4E16\u4EE3\u7ED3\u6E05,\u4E0D\u8FDB\u4E0A\u4E0B\u6587", {
        skipped,
        requeued: kept.length,
        max: MAX_REQUEUE,
        earliestTs: stale[0].ts,
        latestTs: stale[stale.length - 1].ts
      });
    }
    for (const event of kept) bus.push({ event }, { trigger: "piggyback" });
    log.info("\u91CD\u542F\u8865\u6295:\u6C34\u4F4D\u4E4B\u540E\u8FD8\u6CA1\u8FDB\u8FC7 session \u7684\u5916\u90E8\u4E8B\u4EF6\u5DF2\u91CD\u65B0\u5165\u961F", {
      count: kept.length,
      fromCursor: kept[0].cursor
    });
    const originals = kept.filter((event) => event.contextDelivery === "archive-only");
    if (originals.length > 0) {
      log.warn("\u8865\u6295\u91CC\u6709\u6CA1\u7B49\u5230\u6295\u5F71\u7684\u539F\u59CB\u5F52\u6863,\u6309\u539F\u6587\u8865\u6295", {
        count: originals.length,
        sources: [...new Set(originals.map((event) => event.source))],
        earliestTs: originals[0].ts,
        latestTs: originals[originals.length - 1].ts
      });
    }
  }
  async bootstrap(generation) {
    if (!this.active(generation)) return;
    const { session, log } = this.d;
    if (this.pruneStalls()) this.d.state.save();
    if (this.stallSince !== 0) {
      const carried = this.stallAt.filter((t) => t >= this.stallSince).length;
      log.warn("\u5DF2\u6062\u590D\u4E0A\u4E00\u8FDB\u7A0B\u7684 LLM \u8FDE\u7EED\u5931\u8D25\u8BB0\u5F55", {
        since: new Date(this.stallSince).toISOString(),
        count: carried
      });
      this.stallAlarmActive = carried >= STALL_ALERT_THRESHOLD;
    }
    this.requeueUndelivered();
    if (session.records.length === 0) {
      const system = await this.buildSystem();
      if (!this.active(generation)) return;
      session.append(system);
      this.pushOpening("new");
      log.info("bootstrap:\u5168\u65B0session");
      return;
    }
    const unanswered = /* @__PURE__ */ new Set();
    for (const { item } of session.records) {
      if (item.type === "function_call") unanswered.add(item.call_id);
      if (item.type === "function_call_output") unanswered.delete(item.call_id);
    }
    for (const id of unanswered) session.append(functionResult(id, MISSING_RESULT_RESTART));
    this.pushOpening("restarted");
    log.info("bootstrap:\u91CD\u542F\u6062\u590D");
  }
  async run() {
    if (!this.activeNow()) return;
    const generation = this.generation;
    const { bus, log, persona, decl } = this.d;
    this.running = true;
    try {
      this.mainTrack = this.d.tracker?.open(decl.id, decl.label, {
        id: decl.id,
        messagesRef: () => this.d.session.records
      }) ?? null;
      this.bindWorlds();
      await this.bootstrap(generation);
      if (!this.active(generation)) return;
      const stopSignal = new Promise((resolve2) => {
        this.stopFn = () => resolve2("stop");
      });
      this.watermarkAudit = setInterval(() => {
        try {
          this.auditDeliveryWatermark();
        } catch (e) {
          log.warn("\u6C34\u4F4D\u81EA\u68C0\u5F02\u5E38", { err: e });
        }
      }, WATERMARK_AUDIT_INTERVAL_MS);
      this.watermarkAudit.unref?.();
      while (this.running) {
        const got = await Promise.race([bus.nextBatch(), stopSignal]);
        if (got === "stop" || !this.running) break;
        const batch = got;
        await this.maintenanceChain;
        if (!this.active(generation)) break;
        this.processingBatch = true;
        try {
          const changed = await this.deliverBatch(batch, generation);
          if (!this.active(generation)) break;
          if (changed) {
            await this.rounds(generation);
            if (!this.active(generation)) break;
            await this.flushRequestedHandoff(generation);
            if (!this.active(generation)) break;
            await this.batchEndCheck(generation);
            if (!this.active(generation)) break;
          }
          if (bus.pendingImmediate() === 0 && persona.onIdle) {
            try {
              await persona.onIdle();
            } catch (e) {
              log.warn("onIdle\u94A9\u5B50\u5F02\u5E38", { err: e });
            }
            if (!this.active(generation)) break;
          }
          await this.flushRequestedHandoff(generation);
        } finally {
          this.processingBatch = false;
        }
        await this.flushBoundaryMaintenance();
      }
    } finally {
      this.stop();
      this.seal();
    }
  }
  /** 本批模型调用共享 sess 关联字段；每轮更新 round、resp 和 call。 */
  rounds(generation) {
    return withAnchors({ sess: this.d.decl.id }, () => this.roundsInScope(generation));
  }
  async roundsInScope(generation) {
    if (!this.active(generation)) return;
    const { llm, session, log, bus, decl } = this.d;
    const schemas = this.getToolSchemas();
    const caps = decl.rounds();
    this.roundsLastBatch = 0;
    const tap = decl.outputTap;
    const resubmit = this.d.resubmit ?? DEFAULT_RESUBMIT;
    let consecutiveFailures = 0;
    let resubmits = 0;
    for (let round = 1; ; round++) {
      if (!this.active(generation)) return;
      this.roundsLastBatch = round;
      let spec;
      try {
        spec = this.d.spec();
      } catch (error) {
        log.warn("\u6A21\u578B\u914D\u7F6E\u4E0D\u53EF\u7528", { error: String(error) });
        return;
      }
      if (round > 1) {
        const hard = this.d.context.hardTokens();
        if (hard !== null && this.estTokens() > hard) {
          log.warn("\u8BA1\u6570\u8D8A\u8FC7\u6A21\u578B\u4E0A\u4E0B\u6587\u4E0A\u9650,\u672C\u6279\u5728\u8F6E\u8FB9\u754C\u6536\u675F,\u6279\u672B\u4EA4\u63A5", { round, estTokens: this.estTokens(), hardTokens: hard });
          this.finishTurn();
          return;
        }
      }
      const queuedEvents = [];
      const roundNo = ++this.roundSeq;
      setAnchors({ round: roundNo, resp: void 0, call: void 0 });
      const flight = {
        controller: new AbortController(),
        externalized: false,
        abortReason: null
      };
      this.currentRound = flight;
      const ctx = {
        role: decl.id,
        log,
        round: roundNo,
        // 关机或循环换代取消工具；自动抢占不取消工具。
        signal: AbortSignal.any([flight.controller.signal, this.shutdown.signal]),
        queueExternalEvents: (events) => {
          if (this.active(generation)) queuedEvents.push(...events);
        }
      };
      const eager = tap ? new EagerDispatch(
        () => this.toolDefs,
        ctx,
        log,
        decl.id,
        this.d.toolLog,
        () => this.active(generation) && !flight.controller.signal.aborted,
        (name) => this.d.toolOwner?.(name)
      ) : null;
      const roundStart = Date.now();
      let ttftMs = null;
      let llmMs = null;
      let toolMs = 0;
      const noteRound = (outcome, extra = {}) => {
        log.emit("debug", "\u4E00\u8F6E\u6536\u675F", { event: "round", data: {
          round: roundNo,
          outcome,
          llmMs,
          ttftMs,
          outputTokens: meters?.output ?? null,
          toolMs,
          ...extra
        } });
      };
      const tapEvents = tap ? {
        onEvent: (event) => {
          if (!this.active(generation) || flight.controller.signal.aborted) return;
          if (event.type === "response.created") setAnchors({ resp: event.response.id });
          if (ttftMs === null && ("delta" in event || event.type === "response.output_item.added")) ttftMs = Date.now() - roundStart;
          const tappedEffect = tap.externalizes ? tap.externalizes(event) : event.type === "response.output_text.delta" || event.type === "response.refusal.delta" || event.type === "response.output_item.added" && event.item?.type === "function_call";
          if (tappedEffect || event.type === "response.output_item.done" && event.item?.type === "function_call" && event.item.status === "completed") flight.externalized = true;
          eager?.onEvent(event);
          try {
            tap.onEvent(event);
          } catch (error) {
            log.warn("outputTap.onEvent\u5F02\u5E38", { err: error });
          }
        }
      } : void 0;
      let assistant;
      let meters = null;
      const outbound = this.outboundMessages();
      const prefixHash = prefixFingerprint(outbound);
      try {
        const llmStart = Date.now();
        let res;
        try {
          res = await llm.respond(responseRequest(spec, outbound, schemas), {
            context: outbound,
            nativeSpec: spec,
            ...tapEvents ?? {},
            role: decl.id,
            sessionId: this.mainTrack?.id,
            signal: flight.controller.signal
          });
        } finally {
          llmMs = Date.now() - llmStart;
        }
        assistant = responseRecords(res.response, res.origin);
        setAnchors({ resp: res.response.id });
        if (!this.active(generation) || flight.controller.signal.aborted) {
          this.mainTrack?.recordAttempts(res.attempts, void 0, { outcome: "discarded", prefixHash });
          try {
            tap?.onAbort?.("core \u6B63\u5728\u5173\u673A");
          } catch (tapErr) {
            log.warn("outputTap.onAbort\u5F02\u5E38", { err: tapErr });
          }
          noteRound("discarded");
          this.finishTurn();
          return;
        }
        meters = res.attempts[res.attempts.length - 1].meters;
        this.lastUsage = usageCounters(meters);
        this.mainTrack?.recordAttempts(res.attempts, void 0, { prefixHash });
        this.noteStallsRecovered();
        consecutiveFailures = 0;
      } catch (e) {
        if (flight.controller.signal.aborted) {
          this.recordFailedUsage(e, prefixHash);
          try {
            tap?.onAbort?.(flight.abortReason === "shutdown" ? "core \u6B63\u5728\u5173\u673A" : "\u6A21\u578B\u8F6E\u88AB\u65B0\u8F93\u5165\u62A2\u5360");
          } catch (tapErr) {
            log.warn("outputTap.onAbort\u5F02\u5E38", { err: tapErr });
          }
          log.info(flight.abortReason === "shutdown" ? "\u6A21\u578B\u8F6E\u968F\u5173\u673A\u7EC8\u6B62" : "\u5C1A\u672A\u5916\u5316\u7684\u6A21\u578B\u8F6E\u5DF2\u88AB\u65B0\u8F93\u5165\u62A2\u5360");
          noteRound(flight.abortReason === "shutdown" ? "shutdown" : "preempted");
          this.finishTurn();
          return;
        }
        this.recordFailedUsage(e, prefixHash);
        if (tap && e instanceof GenerationError && e.partial) {
          await this.recordAbortedStream(responseRecords(e.partial, e.origin), eager, generation);
          if (!this.active(generation)) {
            try {
              tap.onAbort?.("core \u6B63\u5728\u5173\u673A");
            } catch (tapErr) {
              log.warn("outputTap.onAbort\u5F02\u5E38", { err: tapErr });
            }
            return;
          }
          try {
            tap.onAbort?.(e.message);
          } catch (tapErr) {
            log.warn("outputTap.onAbort\u5F02\u5E38", { err: tapErr });
          }
        }
        for (const event of queuedEvents) {
          bus.push({ event }, { trigger: "flush" });
        }
        if (e instanceof GenerationError && this.d.context.contextOverflow(e)) {
          log.warn("\u4E0A\u6E38\u62D2\u7EDD:\u8F93\u5165\u8D85\u8FC7\u6A21\u578B\u4E0A\u4E0B\u6587,\u672C\u6279\u7ED3\u675F\u5373\u4EA4\u63A5", { estTokens: this.estTokens(), hardTokens: this.d.context.hardTokens() });
          this.handoffRequested = true;
          noteRound("overflow");
          this.finishTurn();
          return;
        }
        this.noteStalled();
        consecutiveFailures++;
        const detail = {
          err: e,
          // 4xx 正文截断后记录；流内失败保留协议层提供的失败事件。
          ...e instanceof GenerationError && e.body ? { body: e.body.slice(0, 500) } : {},
          ...e instanceof GenerationError ? { status: e.status } : {},
          attempt: consecutiveFailures
        };
        const retryable = e instanceof GenerationError && (e.status === 0 || e.status === 429 || e.status >= 500);
        if (retryable && consecutiveFailures <= resubmit.maxConsecutive && resubmits < resubmit.maxPerBatch && round < caps.hard) {
          resubmits++;
          const delayMs = resubmit.backoffMs[Math.min(consecutiveFailures, resubmit.backoffMs.length) - 1] ?? 0;
          log.warn("LLM \u8C03\u7528\u5931\u8D25\uFF0C\u9000\u907F\u540E\u5728\u672C\u6279\u5185\u91CD\u8BD5", { ...detail, resubmits, delayMs });
          noteRound("failed", { resubmit: true, delayMs });
          await this.backoff(delayMs);
          if (!this.active(generation)) return;
          const ready = bus.takeIfReady();
          if (ready) {
            await this.deliverBatch(ready, generation);
            if (!this.active(generation)) return;
          }
          continue;
        }
        log.error("LLM\u8C03\u7528\u5931\u8D25,\u672C\u8F6E\u81EA\u7136\u7ED3\u675F", detail);
        noteRound("failed", { resubmit: false });
        this.finishTurn();
        return;
      } finally {
        if (this.currentRound === flight) this.currentRound = null;
      }
      if (!this.active(generation)) return;
      assistant = this.dropReservedCalls(assistant);
      const calls = assistant.flatMap((entry) => entry.item.type === "function_call" ? [entry.item] : []);
      this.pendingToolCalls = new Set(calls.map((call) => call.call_id));
      for (const entry of assistant) session.append(entry);
      if (meters && meters.input !== null && meters.output !== null) {
        this.anchor = { records: session.records.length, tokens: meters.input + meters.output, reasoningTokens: meters.reasoning ?? 0 };
      }
      if (!this.active(generation)) return;
      if (tap) {
        try {
          tap.onRoundEnd?.();
        } catch (e) {
          log.warn("outputTap.onRoundEnd\u5F02\u5E38", { err: e });
        }
      }
      if (calls.length === 0) {
        noteRound("completed");
        this.finishTurn();
        return;
      }
      const results = [];
      let barrierHit = false;
      let turnEnded = false;
      const toolsStart = Date.now();
      for (const call of calls) {
        if (!this.active(generation)) return;
        if (call.status !== "completed") {
          results.push(functionResult(call.call_id, NOT_EXECUTED_INCOMPLETE));
          barrierHit = true;
          continue;
        }
        if (barrierHit) {
          results.push(functionResult(call.call_id, NOT_EXECUTED_BARRIER));
          continue;
        }
        let out;
        const def = this.toolDefs.find((t) => t.name === call.name);
        if (!def) {
          out = { text: UNKNOWN_TOOL };
          withAnchors({ call: call.call_id }, () => recordToolCall(this.d.toolLog, decl.id, call.name, null, Date.now(), out));
        } else {
          const eagerOut = eager?.take(call.call_id);
          if (eagerOut !== void 0) {
            out = await eagerOut;
            if (!this.active(generation)) return;
          } else {
            const args = parseToolArgs(call.arguments);
            if (args === null) {
              out = { text: TOOL_FAILED_BAD_ARGS, failed: true };
              withAnchors({ call: call.call_id }, () => recordToolCall(this.d.toolLog, decl.id, def.name, null, Date.now(), out, this.d.toolOwner?.(def.name)));
              results.push(functionResult(call.call_id, out.text));
              if (def.barrierAfter) barrierHit = true;
              continue;
            }
            out = await runToolHandler(
              def,
              args,
              ctx,
              call.call_id,
              decl.id,
              this.d.toolLog,
              () => this.active(generation),
              this.d.toolOwner?.(def.name)
            );
            if (!this.active(generation)) return;
          }
          if (def.barrierAfter) barrierHit = true;
          if (def.endsTurn) turnEnded = true;
        }
        if (out.text.length > LARGE_RESULT_WARN_CHARS) {
          log.warn("\u5DE5\u5177\u56DE\u6267\u8FC7\u957F,\u4F53\u79EF\u5F52 World \u7BA1", { tool: call.name, chars: out.text.length, limit: LARGE_RESULT_WARN_CHARS });
        }
        results.push(this.toolResult(call.call_id, out));
      }
      toolMs = Date.now() - toolsStart;
      if (!this.active(generation)) return;
      if (round === caps.soft && results.length > 0) {
        const hint = caps.softHint?.();
        if (hint) results[results.length - 1] = withText(results[results.length - 1], `${textOf(results[results.length - 1])}
${hint}`);
      }
      for (const result of results) session.append(result);
      this.pendingToolCalls.clear();
      const arrived = queuedEvents.map((event) => ({ event }));
      if (round < caps.hard && !turnEnded) {
        const ready = bus.takeIfReady();
        if (ready) arrived.push(...ready);
      }
      if (arrived.length > 0) {
        if (round >= caps.hard || turnEnded) {
          for (const item of arrived) bus.push(item, { trigger: "flush" });
        } else {
          await this.deliverBatch(arrived, generation);
          if (!this.active(generation)) return;
        }
      }
      if (turnEnded) {
        noteRound("ended", { toolCalls: calls.length, arrived: arrived.length });
        this.finishTurn();
        return;
      }
      if (round >= caps.hard) {
        log.warn("\u786C\u4E0A\u9650\u5F3A\u5236\u7ED3\u675F\u672C\u6B21\u5524\u9192", { round });
        noteRound("hard-cap", { toolCalls: calls.length, arrived: arrived.length });
        this.finishTurn();
        return;
      }
      noteRound("continue", { toolCalls: calls.length, arrived: arrived.length });
    }
  }
  /** 重新请求前等待；stop() 通过 backoffWake 提前结束等待。 */
  backoff(ms) {
    if (ms <= 0) return Promise.resolve();
    return new Promise((resolve2) => {
      const timer = setTimeout(() => {
        this.backoffWake = null;
        resolve2();
      }, ms);
      this.backoffWake = () => {
        clearTimeout(timer);
        this.backoffWake = null;
        resolve2();
      };
    });
  }
  /**
   * 保存已经发送的部分响应。已执行调用使用实际结果；
   * 未执行调用补充未执行标记，保持后续请求的工具配对。
   */
  async recordAbortedStream(partial, eager, generation) {
    if (!this.active(generation)) return;
    const { session } = this.d;
    partial = this.dropReservedCalls(partial);
    const calls = partial.flatMap((entry) => entry.item.type === "function_call" ? [entry.item] : []);
    this.pendingToolCalls = new Set(calls.map((call) => call.call_id));
    for (const entry of partial) session.append(entry);
    for (const call of calls) {
      const ran = eager?.take(call.call_id);
      const out = ran !== void 0 ? await ran : { text: NOT_EXECUTED_STREAM_ABORTED };
      if (!this.active(generation)) return;
      session.append(this.toolResult(call.call_id, out));
      this.pendingToolCalls.delete(call.call_id);
    }
    this.pendingToolCalls.clear();
  }
  /** 运维显式丢弃的即时事件也结清水位，但不写入 session。 */
  acknowledgeDiscarded(events) {
    this.noteHandled(events, this.generation);
  }
  /** 按请求内容估算，排除不会回传的历史推理。 */
  estimateOutbound(msgs) {
    const view = this.d.cfg.context.keepPastThinking ? msgs : withoutPastReasoning(msgs);
    return this.d.context.estimateTokens(view);
  }
  /**
   * 使用上次成功请求的 token 计数，加上此后新增条目的本地估算。
   * 禁用历史推理时扣除上次输出中的推理量；无上游计数时估算完整请求，含合成首轮对话。
   */
  estTokens() {
    const { anchor } = this;
    const records = this.d.session.records;
    if (anchor && records.length >= anchor.records) {
      const keep = this.d.cfg.context.keepPastThinking;
      return anchor.tokens - (keep ? 0 : anchor.reasoningTokens) + this.estimateOutbound(records.slice(anchor.records));
    }
    return this.estimateOutbound(this.outboundMessages());
  }
  /** 上游已计数的部分；全部由本地估算时为 0。 */
  countedTokens() {
    const { anchor } = this;
    if (!anchor || this.d.session.records.length < anchor.records) return 0;
    return anchor.tokens - (this.d.cfg.context.keepPastThinking ? 0 : anchor.reasoningTokens);
  }
  /** 主 session 的计数与物理上限(sessionInfo 查询面的数据源)。 */
  contextGauge() {
    return { estTokens: this.estTokens(), hardTokens: this.d.context.hardTokens() };
  }
  /** 一批结束后调用 Persona 钩子，再检查是否超过模型容量；超限时强制交接。 */
  async batchEndCheck(generation) {
    if (!this.active(generation)) return;
    const { persona, log } = this.d;
    try {
      persona.onBatchEnd?.();
    } catch (e) {
      log.warn("onBatchEnd\u94A9\u5B50\u5F02\u5E38", { err: e });
    }
    if (await this.flushRequestedHandoff(generation)) return;
    if (!this.active(generation)) return;
    const hard = this.d.context.hardTokens();
    if (hard !== null && this.estTokens() > hard) {
      log.warn("\u8BA1\u6570\u8D8A\u8FC7\u6A21\u578B\u4E0A\u4E0B\u6587\u4E0A\u9650,\u5F3A\u5236\u4EA4\u63A5", { estTokens: this.estTokens(), hardTokens: hard, model: this.d.spec().model });
      await this.handoffContext();
    }
  }
  /**
   * 统一交接入口。事务是单实例的:阈值触发与运维手动请求复用同一个
   * Promise,Persona的策略因此不会被重复拉起。
   */
  handoffContext() {
    const generation = this.generation;
    if (!this.active(generation)) return Promise.resolve();
    if (this.truncatePromise) return this.truncatePromise;
    let tracked;
    tracked = this.enqueueMaintenance(() => this.performHandoff(generation), generation).finally(() => {
      if (this.truncatePromise === tracked) this.truncatePromise = null;
    });
    this.truncatePromise = tracked;
    return tracked;
  }
  enqueueMaintenance(task, generation) {
    const guarded = () => this.active(generation) ? task() : Promise.resolve();
    const run = this.maintenanceChain.then(guarded, guarded);
    this.maintenanceChain = run.then(() => void 0, () => void 0);
    return run;
  }
  /**
   * 运维入口：在安全回合边界强制一次交接。正在处理批次时只登记请求，
   * 由run()在assistant自然结束后兑现；空闲时可立即开始。
   */
  requestContextHandoff() {
    if (!this.activeNow()) return false;
    if (this.truncatePromise || this.handoffRequested) return false;
    if (this.processingBatch) {
      this.handoffRequested = true;
      return true;
    }
    void this.handoffContext().catch((error) => {
      this.d.log.error("\u624B\u52A8\u4E0A\u4E0B\u6587\u4EA4\u63A5\u5931\u8D25", { err: error });
    });
    return true;
  }
  async flushRequestedHandoff(generation) {
    if (!this.active(generation)) return false;
    if (!this.handoffRequested) return false;
    this.handoffRequested = false;
    await this.handoffContext();
    return this.active(generation);
  }
  /**
   * Persona.onHandoff 提供保留内容；事务期间停止投递，钩子注入项进入新 session 的首批。
   * 策略失败或返回内容越界时使用默认重建结果。
   */
  async performHandoff(generation) {
    if (!this.active(generation)) return;
    const { cfg, session, state, log, persona } = this.d;
    const snapshot = this.outboundMessages();
    const before = this.estTokens();
    let result = { tail: null };
    try {
      if (persona.onHandoff) result = await persona.onHandoff(snapshot, { hardTokens: this.d.context.hardTokens() });
    } catch (e) {
      log.error("\u4E0A\u4E0B\u6587\u4EA4\u63A5\u7B56\u7565\u5931\u8D25,\u7EE7\u7EED\u673A\u68B0\u91CD\u5EFA", { err: e });
    }
    if (!this.active(generation)) return;
    const sysMsg = await this.buildSystem();
    if (!this.active(generation)) return;
    const newTail = this.clampTail(result, snapshot, [sysMsg, ...this.sessionHead()]);
    session.reset([sysMsg, ...newTail]);
    for (const m of this.d.worlds.visible()) {
      try {
        m.onHandoffEnded?.();
      } catch (e) {
        log.warn("World \u4EA4\u63A5\u94A9\u5B50\u5F02\u5E38", { id: m.id, err: e });
      }
    }
    state.data.lastTruncateAt = nowIso(cfg.timezone);
    state.save();
    const summary = { beforeTokens: before, afterTokens: this.estTokens(), kept: newTail.length, dropped: Math.max(0, snapshot.length - newTail.length) };
    this.d.transcript?.boundary("handoff", summary);
    log.emit("info", "\u4E0A\u4E0B\u6587\u4EA4\u63A5\u5B8C\u6210", { event: "handoff", data: summary });
  }
  /**
   * 修复保留内容的工具配对，并将新前缀与保留内容限制在 hardTokens 内。
   * null 从快照末尾重建；上限未知时仅修复配对。trim 表示候选内容允许超限后裁剪。
   */
  clampTail(result, snapshot, prefix) {
    const { log, context } = this.d;
    const { tail } = result;
    const hard = context.hardTokens();
    const budget = hard === null ? null : Math.max(0, hard - context.estimateTokens(prefix));
    const estimate = (records) => context.estimateTokens(records);
    if (tail === null) {
      let start = 0;
      while (start < snapshot.length && hasRole(snapshot[start], "system")) start++;
      const candidate = snapshot.slice(start).filter((m) => !m.context.head);
      return budget === null ? fixPairing(candidate) : rebuildTail(candidate, budget, estimate);
    }
    const paired = fixPairing(tail.filter((m) => !hasRole(m, "system") && !m.context.head));
    if (budget === null || estimate(paired) <= budget) return paired;
    if (!result.trim) log.warn("\u4EA4\u63A5\u7B56\u7565\u8FD4\u56DE\u7684\u52A8\u6001\u5C3E\u8D8A\u8FC7\u6A21\u578B\u4E0A\u4E0B\u6587\u4E0A\u9650,\u6309\u673A\u68B0\u9ED8\u8BA4\u88C1\u526A", { budget });
    return rebuildTail(paired, budget, estimate);
  }
  /**
   * 清空主 session，重建 system 前缀并调用 Persona 开场钩子；事件库保留。
   * 正在处理批次时等到该批自然结束，不重置半轮 session；并发请求复用同一 Promise。
   */
  clearSession() {
    const generation = this.generation;
    if (!this.active(generation)) return Promise.resolve();
    if (this.clearSessionPromise) return this.clearSessionPromise;
    let tracked;
    tracked = this.safeBoundary().then(() => this.enqueueMaintenance(() => this.performClearSession(generation), generation)).finally(() => {
      if (this.clearSessionPromise === tracked) this.clearSessionPromise = null;
    });
    this.clearSessionPromise = tracked;
    return tracked;
  }
  async performClearSession(generation) {
    if (!this.active(generation)) return;
    const { session, log } = this.d;
    const sysMsg = await this.buildSystem();
    if (!this.active(generation)) return;
    session.reset([sysMsg]);
    this.d.transcript?.boundary("clear", {});
    this.finishTurn();
    this.pushOpening("cleared");
    log.emit("warn", "session\u5DF2\u6E05\u7A7A\u91CD\u5F00", { event: "session-cleared" });
  }
  /**
   * 通过 Persona.systemSegments 和 World 环境模板重建 system 前缀。
   * 只替换 system 消息，保留既有 user、assistant 和工具记录。
   */
  reloadSystemPrefix() {
    const generation = this.generation;
    if (!this.active(generation)) return Promise.resolve();
    if (this.prefixReloadPromise) return this.prefixReloadPromise;
    let tracked;
    tracked = this.safeBoundary().then(() => this.enqueueMaintenance(() => this.performSystemPrefixReload(generation), generation)).finally(() => {
      if (this.prefixReloadPromise === tracked) this.prefixReloadPromise = null;
    });
    this.prefixReloadPromise = tracked;
    return tracked;
  }
  /** 空闲时立即；正在处理批次时等 run() 在批末释放，或 stop() 释放。 */
  safeBoundary() {
    if (!this.processingBatch) return Promise.resolve();
    return new Promise((resolve2) => {
      this.releaseAtBoundary.push(resolve2);
    });
  }
  releaseBoundary() {
    const waiting = this.releaseAtBoundary;
    this.releaseAtBoundary = [];
    for (const release of waiting) release();
  }
  async flushBoundaryMaintenance() {
    if (this.releaseAtBoundary.length === 0) return false;
    this.releaseBoundary();
    await Promise.all([this.prefixReloadPromise, this.clearSessionPromise]);
    return true;
  }
  async performSystemPrefixReload(generation) {
    if (!this.active(generation)) return;
    const { session, log } = this.d;
    const sysMsg = await this.buildSystem();
    if (!this.active(generation)) return;
    const snapshot = [...session.records];
    let tailStart = 0;
    while (tailStart < snapshot.length && hasRole(snapshot[tailStart], "system")) tailStart++;
    session.reset([sysMsg, ...snapshot.slice(tailStart)]);
    this.d.transcript?.boundary("prefix-reload", { keptMessages: snapshot.length - tailStart });
    log.emit("warn", "\u5F53\u524Dsession\u7CFB\u7EDF\u524D\u7F00\u5DF2\u91CD\u8F7D", { event: "prefix-reload", data: { keptMessages: snapshot.length - tailStart } });
  }
  /** 每次已发出的 HTTP 尝试均记账；未报告的 token 维度保留为未知。 */
  recordFailedUsage(error, prefixHash) {
    if (error instanceof GenerationError) this.mainTrack?.recordAttempts(error.attempts, void 0, { prefixHash });
  }
  /** 记录失败时刻与连续失败起点，并持久化。 */
  noteStalled() {
    const now = Date.now();
    if (this.stallSince === 0) this.stallSince = now;
    this.stallAt.push(now);
    this.pruneStalls(now);
    this.d.state.save();
    if (!this.stallAlarmActive && this.stallSince !== 0) {
      const count = this.stallAt.filter((t) => t >= this.stallSince).length;
      if (count >= STALL_ALERT_THRESHOLD) {
        this.stallAlarmActive = true;
        this.d.log.error(
          `[\u544A\u8B66] LLM \u8FDE\u7EED\u5931\u8D25 ${count} \u6B21\uFF1B\u8BF7\u68C0\u67E5\u8BF7\u6C42\u9519\u8BEF\u4E0E\u4E0A\u6E38\u72B6\u6001`,
          {
            count,
            since: new Date(this.stallSince).toISOString(),
            threshold: STALL_ALERT_THRESHOLD
          }
        );
      }
    }
  }
  /** 清除窗口外的失败时刻；窗口内已无失败记录时同时清除连续失败起点。 */
  pruneStalls(now = Date.now()) {
    const stall = this.d.state.data.llmStall;
    const cutoff = now - STALL_WINDOW_MS;
    const before = stall.at.length;
    while (stall.at.length > 0 && stall.at[0] < cutoff) stall.at.shift();
    const cleared = stall.at.length === 0 && stall.since !== 0;
    if (cleared) stall.since = 0;
    return before !== stall.at.length || cleared;
  }
  /**
   * 首次成功后将连续失败次数与时长交给 Persona.onStallsRecovered，并清除起点。
   * 未提供钩子或未返回正文时不注入恢复通知。
   */
  noteStallsRecovered() {
    this.pruneStalls();
    if (this.stallSince === 0) {
      if (this.stallAlarmActive) {
        this.stallAlarmActive = false;
        this.d.log.warn("[\u89E3\u9664] LLM \u8FDE\u8D25\u544A\u8B66\u89E3\u9664:\u5931\u8D25\u4E32\u5DF2\u8D85\u51FA\u7EDF\u8BA1\u7A97\u53E3");
      }
      return;
    }
    const count = this.stallAt.filter((t) => t >= this.stallSince).length;
    const quietMs = Date.now() - this.stallSince;
    this.stallSince = 0;
    this.d.state.save();
    if (this.stallAlarmActive) {
      this.stallAlarmActive = false;
      this.d.log.warn("[\u89E3\u9664] LLM \u8FDE\u8D25\u544A\u8B66\u89E3\u9664:\u8C03\u7528\u5DF2\u6062\u590D\u6210\u529F", { count, quietMs });
    }
    const text2 = this.d.persona.onStallsRecovered?.({ count, quietMs });
    if (!text2) return;
    this.d.bus.push(this.internalItem("core", "core.stall", text2));
  }
  /** 水位积压扫描:该进上下文却还没投递的外部事件计数与最老一条(巡查与状态面共用)。 */
  watermarkBacklog() {
    const { state, store } = this.d;
    const latest = store.latestCursor();
    let behind = 0;
    let oldest = null;
    for (let c = state.data.lastDeliveredCursor + 1; c <= latest; c++) {
      const e = store.get(c);
      if (!e) continue;
      if (e.origin !== "external" || e.contextDelivery === "archive-only") continue;
      behind++;
      if (!oldest) oldest = e;
    }
    return { behind, oldest };
  }
  /**
   * 最老的待投递外部事件等待超过 WATERMARK_STALL_MS 时报告 error，不自动修复。
   * 人工暂停或投递 gate 生效时不告警；仅含内部事件或 archive-only 原文的积压不触发该告警。等待 projector 的原文仍须由连续水位规则保护。
   * 公开入口供巡查、测试与控制台调用。
   */
  auditDeliveryWatermark() {
    if (!this.activeNow()) return;
    const { bus, state, store, log } = this.d;
    const watermark = state.data.lastDeliveredCursor;
    if (bus.isPaused() || bus.isDeliveryBlocked()) return;
    const latest = store.latestCursor();
    const { behind, oldest } = this.watermarkBacklog();
    const stalledForMs = oldest ? Date.now() - Date.parse(oldest.ts) : 0;
    const stalled = oldest !== null && Number.isFinite(stalledForMs) && stalledForMs > WATERMARK_STALL_MS;
    if (!stalled) {
      if (this.watermarkStallAt >= 0 && this.watermarkStallAt !== watermark) {
        log.warn("\u6295\u9012\u6C34\u4F4D\u505C\u6EDE\u5DF2\u89E3\u9664:\u6C34\u4F4D\u53C8\u5F00\u59CB\u63A8\u8FDB\u4E86", {
          stalledAtCursor: this.watermarkStallAt,
          lastDeliveredCursor: watermark,
          caughtUp: watermark - this.watermarkStallAt
        });
        this.watermarkStallAt = -1;
      }
      return;
    }
    if (oldest === null) return;
    if (this.watermarkStallAt === watermark) {
      const idx = this.watermarkStallReports - 1;
      if (idx >= WATERMARK_RESTATE_MS.length) return;
      const sinceFirstReportMs = Date.now() - this.watermarkStallSince;
      if (sinceFirstReportMs < WATERMARK_RESTATE_MS[idx]) return;
      this.watermarkStallReports++;
      log.error("\u6295\u9012\u6C34\u4F4D\u4ECD\u5728\u505C\u6EDE:\u540C\u4E00\u6C34\u4F4D\u6301\u7EED\u672A\u63A8\u8FDB", {
        behind,
        behindDelta: behind - this.watermarkStallBehind,
        sinceFirstReportMs,
        stalledForMs,
        lastDeliveredCursor: watermark,
        latestCursor: latest,
        report: this.watermarkStallReports
      });
      return;
    }
    this.watermarkStallAt = watermark;
    this.watermarkStallSince = Date.now();
    this.watermarkStallBehind = behind;
    this.watermarkStallReports = 1;
    log.error("\u6295\u9012\u6C34\u4F4D\u505C\u6EDE:\u6709\u8BE5\u8FDB\u4E0A\u4E0B\u6587\u7684\u5916\u90E8\u4E8B\u4EF6\u957F\u65F6\u95F4\u6CA1\u88AB\u6295\u9012,\u6C34\u4F4D\u6CA1\u6709\u63A8\u8FDB", {
      behind,
      stalledForMs,
      thresholdMs: WATERMARK_STALL_MS,
      lastDeliveredCursor: watermark,
      latestCursor: latest,
      oldestCursor: oldest.cursor,
      oldestTs: oldest.ts,
      oldestSource: oldest.source,
      oldestText: oldest.text.slice(0, 200)
    });
  }
  /** 查询最近 withinMs 毫秒内的模型失败次数。 */
  llmStalls(withinMs) {
    const from = Date.now() - Math.max(0, withinMs);
    return this.stallAt.filter((t) => t >= from).length;
  }
  /** 注入 Persona 提供的内部文本。onDelivery 完成前加入当前批，其余时刻进入总线。 */
  injectInternal(text2, kind = "notice") {
    if (!this.activeNow()) return;
    const item = this.internalItem("persona", kind, text2);
    if (this.deliveryCollector) {
      this.deliveryCollector.push(item.event);
      return;
    }
    this.d.bus.push(item);
  }
  /** 注入 Persona 提供的外部正文；source=persona、origin=external，按 eventDelivery 投递。 */
  injectExternal(text2, kind = "note") {
    if (!this.activeNow()) return;
    const { store, cfg } = this.d;
    const event = store.append({
      type: kind,
      ts: nowIso(cfg.timezone),
      source: "persona",
      origin: "external",
      contextDelivery: "deliver",
      text: text2
    });
    this.d.bus.push({ event });
  }
  /** 内部项在投递时渲染并归档；投递正文与归档正文一致。 */
  injectDeferred(kind, render) {
    if (!this.activeNow()) return;
    this.d.bus.push({ deferred: { type: kind, source: "persona", origin: "internal", render } });
  }
  /**
   * 内部项与外部事件共用事件库和游标，origin 标记为 internal；调用方决定投递时机。
   * source 记录生产方。
   */
  internalItem(source, type, text2) {
    const { store, cfg } = this.d;
    const event = store.append({
      type,
      ts: nowIso(cfg.timezone),
      source,
      origin: "internal",
      text: text2
    });
    return { event };
  }
  /** 当前工具 schema，供模型与控制台使用；run() 前为空。tags 保留声明方的分类。 */
  getToolSchemas() {
    return this.toolDefs.map(({ name, description, parameters, tags }) => ({
      name,
      description,
      parameters,
      tags
    }));
  }
  getStatus() {
    return {
      running: this.running,
      truncating: this.truncatePromise !== null || this.handoffRequested,
      messageCount: this.d.session.records.length,
      estTokens: this.estTokens(),
      context: {
        hardTokens: this.d.context.hardTokens(),
        countedTokens: this.countedTokens(),
        keepPastThinking: this.d.cfg.context.keepPastThinking
      },
      batchesHandled: this.batchesHandled,
      roundsLastBatch: this.roundsLastBatch,
      lastTruncateAt: this.d.state.data.lastTruncateAt,
      paused: this.d.bus.isPaused(),
      scheduleBlocked: this.d.bus.isDeliveryBlocked(),
      lastUsage: this.lastUsage,
      lastDeliveredCursor: this.d.state.data.lastDeliveredCursor,
      behind: this.watermarkBacklog().behind
    };
  }
  stop() {
    if (this.stopped) return;
    this.running = false;
    this.stopped = true;
    this.generation++;
    if (this.watermarkAudit) clearInterval(this.watermarkAudit);
    this.watermarkAudit = null;
    this.completePendingToolCallsForShutdown();
    this.backoffWake?.();
    if (!this.shutdown.signal.aborted) this.shutdown.abort(new Error("core \u6B63\u5728\u5173\u673A"));
    this.handoffRequested = false;
    this.releaseBoundary();
    this.stopFn?.();
    const round = this.currentRound;
    if (round && !round.controller.signal.aborted) {
      round.abortReason = "shutdown";
      round.controller.abort(new Error("core \u6B63\u5728\u5173\u673A"));
    }
  }
  /** 主循环已退出或 drain 超时；阻止迟到异步链继续写 session、工具账或结束钩子。 */
  seal() {
    this.sealed = true;
  }
  /** stop 的同步边界闭合已经落库的工具调用；异步 handler 的迟到结果一律丢弃。 */
  completePendingToolCallsForShutdown() {
    const failed = [];
    for (const callId of this.pendingToolCalls) {
      try {
        this.d.session.append(functionResult(callId, SHUTDOWN_INTERRUPTED));
      } catch {
        failed.push(callId);
      }
    }
    this.pendingToolCalls.clear();
    if (failed.length > 0) {
      this.d.log.error("\u5173\u673A\u65F6\u5DE5\u5177\u8C03\u7528\u914D\u5BF9\u8BB0\u5F55\u5199\u5165\u5931\u8D25", { callIds: failed });
    }
  }
};
function parseToolArgs(raw) {
  try {
    return JSON.parse(raw || "{}");
  } catch {
    return null;
  }
}
function runToolHandler(def, args, ctx, callId, role, toolLog, canRecord = () => true, mod) {
  const startedAt = Date.now();
  return withAnchors({ call: callId }, () => Promise.resolve().then(() => def.handler(args, { ...ctx, callId })).then((out) => typeof out === "string" ? { text: out } : out).catch((e) => ({
    text: toolFailed(e instanceof Error ? e.message : String(e)),
    failed: true
  })).then((out) => {
    if (canRecord()) recordToolCall(toolLog, role, def.name, args, startedAt, out, mod);
    return out;
  }));
}
var EagerDispatch = class {
  constructor(defs, ctx, log, role, toolLog, active = () => true, owner = () => void 0) {
    this.defs = defs;
    this.ctx = ctx;
    this.log = log;
    this.role = role;
    this.toolLog = toolLog;
    this.active = active;
    this.owner = owner;
  }
  defs;
  ctx;
  log;
  role;
  toolLog;
  active;
  owner;
  ready = /* @__PURE__ */ new Map();
  results = /* @__PURE__ */ new Map();
  chain = Promise.resolve();
  barrierHit = false;
  nextIndex = 0;
  onEvent(event) {
    if (!this.active()) return;
    if (event.type === "response.created") {
      this.ready.clear();
      this.nextIndex = 0;
      return;
    }
    if (event.type !== "response.output_item.done" || !event.item) return;
    this.ready.set(event.output_index, event.item);
    while (this.ready.has(this.nextIndex)) {
      const item = this.ready.get(this.nextIndex);
      this.ready.delete(this.nextIndex++);
      if (item.type !== "function_call") continue;
      if (item.status !== "completed") {
        this.barrierHit = true;
        continue;
      }
      this.dispatch({ id: item.call_id, name: item.name, args: item.arguments });
    }
  }
  dispatch(call) {
    if (!this.active()) return;
    if (this.barrierHit) return;
    if (RESERVED_FRAME_NAMES.has(call.name)) return;
    if (!call.id) {
      this.log.warn("tool_call \u7F3A id,\u8DF3\u8FC7\u63D0\u524D\u6D3E\u53D1", { name: call.name });
      return;
    }
    const def = this.defs().find((t) => t.name === call.name);
    if (!def) return;
    if (def.barrierAfter) this.barrierHit = true;
    const args = parseToolArgs(call.args);
    if (args === null) return;
    const run = this.chain.then(() => this.active() ? runToolHandler(def, args, this.ctx, call.id, this.role, this.toolLog, this.active, this.owner(def.name)) : { text: NOT_EXECUTED_LOOP_STOPPED });
    this.chain = run.then(() => void 0);
    this.results.set(call.id, run);
  }
  /** 取走某次调用的执行结果;没提前派发过返回 undefined(一次性,防重复配对) */
  take(callId) {
    const p = this.results.get(callId);
    this.results.delete(callId);
    return p;
  }
};

// ../../vendor/cortico/src/core/core.ts
var MODULE_STOP_MS = 2e4;
var LOOP_DRAIN_MS = 1e3;
var HIDDEN_PUSH_NOTE_GAP_MS = 10 * 6e4;
var Core = class {
  loaded;
  /** 本次进程运行的标识与日志目录。 */
  run;
  runlog;
  transcript;
  store;
  bus;
  session;
  state;
  timers;
  loop;
  llm;
  /** 媒体库：字节保存在 data/media/，回执与事件只存引用。 */
  logBlobs;
  /** 各agent session的观察注册表(web面板数据源) */
  sessions;
  /** 每次LLM调用的持久化流水(跨重启;用量·成本页数据源) */
  usageLog;
  /** 主循环每次模型工具调用的持久化流水(工具名/原始参数/耗时/回执) */
  toolLog;
  /** Persona注册的 session 声明;core 只按 id 查表,不对值分支 */
  sessionDecls = /* @__PURE__ */ new Map();
  /** 挂载表。与装配层共用同一个数组:运行中挂载/卸载就地增删。 */
  worlds;
  persona;
  log;
  runPromise = null;
  /** start() 已跑过 World 启动循环;之后挂载的 World 立即 start,之前的等 start() 统一起。 */
  started = false;
  /** 每个声明当前运行的 fork 实例数，用于并发记账。 */
  forkRunning = /* @__PURE__ */ new Map();
  /** 各 World 在途的认知请求数；并发限制由 Persona 决定。 */
  cognitionRunning = /* @__PURE__ */ new Map();
  /** 接收事件的主 session 声明。 */
  mainDecl;
  /** World 自愿上报用量的常驻仪表条目(每 World 一条) */
  moduleUsageTracks = /* @__PURE__ */ new Map();
  /** 隐藏 World 照常落库的事件计数与上次回报时刻(每 World 一条) */
  hiddenPushes = /* @__PURE__ */ new Map();
  providers;
  moduleHostLeases = /* @__PURE__ */ new Map();
  constructor(loaded, deps) {
    this.loaded = loaded;
    const cfg = loaded.config;
    const dataDir = loaded.dataDir;
    if (!existsSync13(dataDir)) mkdirSync11(dataDir, { recursive: true });
    this.run = openRun(dataDir, { timezone: cfg.timezone, bot: cfg.displayName, repoRoot: loaded.repoRoot });
    this.runlog = new Runlog(join10(this.run.dir, "log.jsonl"), {
      run: this.run.id,
      timezone: cfg.timezone,
      levels: () => cfg.logging,
      incidentsDir: join10(this.run.dir, "incidents")
    });
    this.log = this.runlog.logger("core");
    this.store = new JsonlEventStore({ dataDir, run: this.run.id, log: this.log.child("store") });
    this.bus = new WakeBus(cfg.batching, this.log.child("bus"));
    this.session = new SessionLog(dataDir, "session-main.jsonl", () => nowIso(cfg.timezone));
    this.transcript = new Transcript(join10(this.run.dir, "transcript.jsonl"), { run: this.run.id, timezone: cfg.timezone });
    this.session.onAppend((record2, index) => this.transcript.item(record2, index));
    this.state = new CoreState(dataDir);
    this.state.load();
    this.worlds = deps.worlds;
    this.persona = deps.persona;
    this.logBlobs = new LogBlobStore(dataDir);
    this.providers = new ProviderRegistry(() => cfg.providers, {
      // 同一部署根下的部署共享端点配置和状态目录。
      stateRoot: loaded.providersDir ?? join10(loaded.rootDir, "providers"),
      repoRoot: loaded.repoRoot ?? process.cwd(),
      readBlob: (handle) => {
        const bytes = this.resolveBlob(handle)?.bytes;
        return bytes ? Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength) : null;
      },
      keepThinking: () => cfg.context.keepPastThinking,
      log: this.log.child("llm")
    });
    this.llm = deps.llm ?? this.makeProviderRouter();
    this.timers = new TimerStore(dataDir, this.log.child("timer"));
    this.usageLog = new UsageLog(join10(dataDir, "usage.jsonl"), (message2) => this.log.error(message2));
    this.toolLog = new ToolCallLog(join10(this.run.dir, "toolcalls.jsonl"), { timezone: cfg.timezone, run: this.run.id });
    this.sessions = new SessionTracker(cfg.timezone, (rec) => {
      const { round } = currentAnchors();
      this.usageLog.append({ ...rec, run: this.run.id, ...round !== void 0 ? { round } : {} });
    });
    this.persona.attach(this.makeApi());
    const decls = this.persona.declareSessions();
    for (const decl of decls) this.sessionDecls.set(decl.id, decl);
    const main2 = decls.filter((d) => d.receivesEvents && d.persistent);
    if (main2.length !== 1) {
      throw new Error(
        `Persona\u5FC5\u987B\u6070\u597D\u58F0\u660E\u4E00\u4E2A\u63A5\u6536\u4E8B\u4EF6\u6295\u9012\u7684\u5E38\u9A7Bsession,\u5F53\u524D${main2.length}\u4E2A`
      );
    }
    this.mainDecl = main2[0];
    this.loop = new MainLoop({
      cfg,
      llm: this.llm,
      persona: deps.persona,
      decl: main2[0],
      spec: () => this.activeSpec(),
      context: this.contextFacts(),
      blobs: { intern: (inputs) => this.internBlobs(inputs) },
      worlds: {
        all: () => this.worlds,
        visible: () => this.worlds.filter((m) => this.isWorldVisible(m.id))
      },
      dirs: { packageDir: loaded.packageDir ?? loaded.rootDir, deploymentDir: loaded.rootDir },
      bus: this.bus,
      session: this.session,
      store: this.store,
      state: this.state,
      log: this.log.child("loop"),
      tracker: this.sessions,
      toolLog: this.toolLog,
      transcript: this.transcript,
      toolOwner: (name) => this.worlds.find((m) => m.tools().some((t) => t.name === name))?.id
    });
    this.bus.setPreemptHandler(() => {
      this.loop.abortCurrentRound();
    });
  }
  makeApi() {
    return {
      injectInternal: (text2, kind) => this.loop.injectInternal(text2, kind),
      injectDeferred: (kind, render) => this.loop.injectDeferred(kind, render),
      injectExternal: (text2, kind) => this.loop.injectExternal(text2, kind),
      requestContextHandoff: () => this.loop.requestContextHandoff(),
      spawnFork: (opts) => this.spawnFork(opts),
      sessionInfo: (id) => this.sessionInfo(id),
      llm: this.llm,
      timers: this.timers,
      deliveryGate: {
        set: (gate) => this.bus.setDeliveryGate(gate),
        clear: (id, deliverQueued) => this.bus.clearDeliveryGate(id, deliverQueued),
        isBlocked: () => this.bus.isDeliveryBlocked()
      },
      personaState: () => this.state.data.persona,
      savePersonaState: () => this.state.save(),
      toolsTagged: (tag) => new Set(this.loop.getToolSchemas().filter((t) => t.tags.includes(tag)).map((t) => t.name)),
      blob: (handle) => this.resolveBlob(handle),
      log: this.log.child("persona")
    };
  }
  /**
   * 按 scheme 解析句柄:`log:` 查日志附件库,`mem:` 问Persona的记忆。
   * 认不出或不在 → null。
   */
  resolveBlob(handle) {
    const scheme = blobScheme(handle);
    if (scheme === "log") return this.logBlobs.read(handle);
    if (scheme === "mem") return this.persona.blobs.get(handle);
    return null;
  }
  /**
   * 新附件字节写入日志附件库并转换为 log: 句柄；已有句柄补充 mime 和名称。
   * 无附件时返回 undefined，避免保存空数组。
   */
  internBlobs(inputs) {
    if (!inputs || inputs.length === 0) return void 0;
    return inputs.map((input) => {
      if ("bytes" in input) {
        const handle = this.logBlobs.put(input.bytes, input.mime);
        return { handle, mime: input.mime, ...input.name ? { name: input.name } : {}, fallbackText: input.fallbackText };
      }
      const known = "mime" in input ? input : null;
      const resolved = known ? null : this.resolveBlob(input.handle);
      const mime = known?.mime ?? resolved?.mime ?? mimeOfHandle(input.handle);
      const name = known?.name ?? input.handle.slice(input.handle.lastIndexOf("/") + 1).replace(/^[a-z]+:/, "");
      return { handle: input.handle, mime, name, fallbackText: input.fallbackText };
    });
  }
  /** 丢弃已发生的事件与候选票据；历史保留，重启不再补投。 */
  discardPendingEvents() {
    const dropped = this.bus.drainPending((item) => item.event !== void 0 || item.candidate !== void 0);
    this.loop.acknowledgeDiscarded(
      dropped.flatMap((item) => item.event ? [item.event] : [])
    );
    return dropped.length;
  }
  sessionInfo(id) {
    const decl = this.sessionDecls.get(id);
    const isMainLoop = decl?.persistent === true && decl.receivesEvents;
    const gauge = isMainLoop ? this.loop.contextGauge() : null;
    return {
      id,
      running: this.forkRunning.get(id) ?? 0,
      // 包含合成首轮对话，使继承该快照的 fork 使用相同的请求前缀。
      snapshot: isMainLoop ? this.loop.outboundMessages() : null,
      estTokens: gauge?.estTokens ?? null,
      hardTokens: gauge?.hardTokens ?? null
    };
  }
  /**
   * 生效上下文窗口:Provider 实例探到的上游自报值与档位手填值取小。两者都缺席时
   * undefined——core 不猜窗口。
   */
  contextWindowOf(spec) {
    const { name } = this.activeProviderEntry();
    const detected = this.providers.resolve(name).contextWindow?.(spec.model);
    const manual = spec.contextWindow;
    if (detected === void 0) return manual;
    return manual === void 0 ? detected : Math.min(detected, manual);
  }
  /** 按当前活跃端点读取模型上下文事实。 */
  contextFacts() {
    const module = () => {
      const entry = this.config.providers[this.config.activeProvider];
      return entry ? providerModules.find((module2) => module2.id === entry.kind) : void 0;
    };
    return {
      hardTokens: () => {
        if (!module() || !this.config.providers[this.config.activeProvider]?.spec) return null;
        const spec = this.activeSpec();
        const window = this.contextWindowOf(spec);
        return window === void 0 ? null : Math.max(0, window - (spec.maxTokens ?? 0));
      },
      estimateTokens: (records) => module()?.estimateTokens?.(records, this.activeSpec()) ?? estimateMessagesTokens(records),
      contextOverflow: (error) => module()?.contextOverflow?.(error) ?? false
    };
  }
  /**
   * 创建临时 session；在创建时绑定当前活跃端点与模型，工具和轮数来自声明或调用参数。
   * 记录并发数与用量；并发限制由 Persona 决定。
   */
  async spawnFork(opts) {
    const decl = this.sessionDecls.get(opts.id);
    if (!decl) throw new Error(`\u672A\u58F0\u660E\u7684session: ${opts.id}`);
    let observedMessages = opts.messages;
    const track = this.sessions.open(decl.id, decl.label, {
      messagesRef: () => observedMessages
    });
    this.forkRunning.set(decl.id, (this.forkRunning.get(decl.id) ?? 0) + 1);
    try {
      return await runForkLoop({
        id: decl.id,
        llm: this.llm.bind?.() ?? this.llm,
        spec: this.activeSpec(),
        messages: opts.messages,
        tools: opts.tools ?? decl.tools(),
        maxRounds: decl.rounds().hard,
        softRounds: decl.rounds().soft,
        log: this.log.child(`fork.${decl.id}`),
        stopWhen: opts.stopWhen,
        // [STELLA PATCH] turn-policy 透传（见 patches/turn-policy.patch）
        turnPolicy: opts.turnPolicy,
        wrapUpHint: opts.wrapUpHint,
        capNote: opts.capNote,
        nudge: opts.nudge,
        track,
        observeMessages: (messages) => {
          observedMessages = messages;
        }
      });
    } finally {
      this.forkRunning.set(decl.id, Math.max(0, (this.forkRunning.get(decl.id) ?? 1) - 1));
      track.close();
    }
  }
  /**
   * Persona 提供且启用 cognition 时，WorldHost 才提供该接口。
   * 请求只能列出该 World 的工具；不合法的请求返回错误，不调用 Persona。
   * Core 记录在途数供 Persona 决定并发策略。经 spawnFork 产生的用量在 fork 中记录，此处不重复计量。
   */
  makeCognition(mod, active) {
    const impl = this.persona.cognition;
    if (!impl) return void 0;
    if (impl.enabled && !impl.enabled()) return void 0;
    const log = this.runlog.logger(`worlds.${mod.id}`);
    return {
      request: async (req) => {
        if (!active()) return { error: "\u5BBF\u4E3B\u751F\u547D\u5468\u671F\u5DF2\u7ED3\u675F" };
        const brief = typeof req?.brief === "string" ? req.brief.trim() : "";
        if (!brief) return { error: "\u8BA4\u77E5\u8BF7\u6C42\u6CA1\u6709 brief:\u8981\u60F3\u7684\u662F\u4EC0\u4E48,\u5F97\u7531 World \u81EA\u5DF1\u8BF4\u6E05\u695A" };
        const own = new Set(mod.tools().map((t) => t.name));
        const named = req.tools ?? [];
        const outsiders = named.filter((name) => !own.has(name));
        if (outsiders.length > 0) {
          log.warn("\u8BA4\u77E5\u8BF7\u6C42\u8D8A\u6743\u70B9\u540D\u5DE5\u5177,\u5DF2\u9A73\u56DE", { tools: outsiders });
          return {
            error: `\u8BA4\u77E5\u8BF7\u6C42\u53EA\u80FD\u70B9\u540D\u672C World \u81EA\u5DF1\u7684\u5DE5\u5177,\u8FD9\u4E9B\u4E0D\u662F: ${outsiders.join(" / ")}(\u672C World \u73B0\u6709: ${[...own].join(" / ") || "(\u65E0)"})`
          };
        }
        const tools = named.map((name) => mod.tools().find((t) => t.name === name));
        const running = (this.cognitionRunning.get(mod.id) ?? 0) + 1;
        this.cognitionRunning.set(mod.id, running);
        try {
          return await impl.request({ ...req, brief }, { worldId: mod.id, tools, running });
        } catch (e) {
          log.warn("\u8BA4\u77E5\u8BF7\u6C42\u53D7\u7406\u5931\u8D25", { err: e });
          return { error: e instanceof Error ? e.message : String(e) };
        } finally {
          this.cognitionRunning.set(mod.id, Math.max(0, (this.cognitionRunning.get(mod.id) ?? 1) - 1));
        }
      }
    };
  }
  /** 各 World 当下在途的认知外包请求数(控制台/诊断用;没有在途的 World 不出现) */
  cognitionInFlight() {
    const out = {};
    for (const [id, n] of this.cognitionRunning) if (n > 0) out[id] = n;
    return out;
  }
  get config() {
    return this.loaded.config;
  }
  /**
   * World 隐藏后继续运行，事件仅归档且重新显示时不补投。
   * 事件投递立即停止；环境前缀与工具表在下一次前缀重建时一同更新。
   */
  setWorldVisible(id, visible) {
    if (!this.worlds.some((m) => m.id === id)) throw new Error(`\u672A\u6302\u8F7D\u7684 World: ${id}`);
    this.state.data.worldVisibility[id] = visible;
    this.state.save();
    this.log.warn(`World \u5BF9 agent ${visible ? "\u53EF\u89C1" : "\u9690\u85CF"}: ${id}`);
  }
  isWorldVisible(id) {
    return this.state.data.worldVisibility[id] !== false;
  }
  /** 隐藏 World 的推送按 HIDDEN_PUSH_NOTE_GAP_MS 限频报告，计数保留在日志中。 */
  noteHiddenPush(id) {
    const note = this.hiddenPushes.get(id) ?? { count: 0, notedAtMs: 0 };
    note.count += 1;
    this.hiddenPushes.set(id, note);
    const now = Date.now();
    if (note.notedAtMs > 0 && now - note.notedAtMs < HIDDEN_PUSH_NOTE_GAP_MS) return;
    note.notedAtMs = now;
    this.log.warn(
      `\u9690\u85CF World \u7684\u4E8B\u4EF6\u4EC5\u5F52\u6863: ${id}(\u672C\u8F6E\u7B2C ${note.count} \u6761)\u3002\u9700\u8981\u6295\u9012\u65F6\u8BF7\u5F00\u542F\u8BE5 World \u7684\u53EF\u89C1\u6027`
    );
  }
  /** 全部已挂载 World 的可见性 + 前缀是否已经跟上 */
  worldVisibility() {
    const visibility = {};
    for (const mod of this.worlds) visibility[mod.id] = this.isWorldVisible(mod.id);
    return { visibility, driftedWorlds: this.loop.modulePrefixDrift() };
  }
  /** 用于控制台状态和启动信息的当前模型配置。 */
  mainSessionSpec() {
    return this.activeSpec();
  }
  /** 按 activeProvider 读取模型配置；端点未配置模型时抛错。 */
  activeSpec() {
    const { name, entry } = this.activeProviderEntry();
    if (!entry.spec) {
      throw new Error(`LLM provider ${name} \u8FD8\u6CA1\u9009\u6A21\u578B(\u53BB\u63A7\u5236\u53F0\u8BE5 Provider \u7684\u300C\u5B9E\u4F8B\u4E0E\u6A21\u578B\u300D\u9762\u677F\u586B\u6A21\u578B\u540D\u5E76\u4FDD\u5B58)`);
    }
    return entry.spec;
  }
  activeProviderEntry() {
    const cfg = this.loaded.config;
    const name = cfg.activeProvider;
    const entry = cfg.providers?.[name];
    if (!entry) {
      const known = Object.keys(cfg.providers ?? {}).join(" / ") || "(\u7A7A)";
      throw new Error(`\u6CA1\u6709\u8FD9\u4E2A LLM provider: ${name}(config.json providers \u6BB5\u73B0\u6709: ${known})`);
    }
    return { name, entry };
  }
  /** The selected instance is resolved once at the start of each request. */
  makeProviderRouter() {
    const bind = () => this.providers.bind(this.activeProviderEntry().name);
    return { bind, respond: async (request, options) => bind().respond(request, options) };
  }
  /** 模型事实(按当前活跃端点实时读,不做启动期快照) */
  modelFacts() {
    const spec = () => this.activeSpec();
    return {
      model: () => spec().model,
      accepts: (mime) => {
        if (!this.loaded.config.activeProvider) return false;
        const { entry } = this.activeProviderEntry();
        if (!entry.spec) return false;
        return providerModule(entry.kind).accepts?.(entry, entry.spec, mime) ?? (entry.multimodal === true && mime.startsWith("image/"));
      },
      contextWindow: () => this.contextWindowOf(spec())
    };
  }
  /** World 宿主接口;每个 World 使用以自身 id 命名的子 logger。 */
  makeHost(mod) {
    const previous = this.moduleHostLeases.get(mod);
    if (previous) previous.active = false;
    const lease = { active: true };
    this.moduleHostLeases.set(mod, lease);
    const self = this;
    return {
      // origin 由 World 指定，默认 external；决定后续投递方式。
      pushEvent: async (e, opts) => {
        if (!lease.active) throw new Error(`World ${mod.id} \u7684\u5BBF\u4E3B\u751F\u547D\u5468\u671F\u5DF2\u7ED3\u675F`);
        const deliver = opts?.deliver !== false && this.isWorldVisible(mod.id);
        const blobs = this.internBlobs(e.blobs);
        const envelope = this.store.append({
          ...e,
          text: withBlobLines(e.text, blobs),
          ...blobs ? { blobs } : {},
          origin: e.origin ?? "external",
          contextDelivery: deliver ? "deliver" : "archive-only"
        });
        if (deliver) {
          this.bus.push({ event: envelope }, { trigger: opts?.trigger });
        } else {
          this.loop.acknowledgeDiscarded([envelope]);
          if (opts?.deliver !== false) this.noteHiddenPush(mod.id);
        }
        return envelope;
      },
      pushDeferred: (e, opts) => {
        if (!lease.active) return;
        if (!this.isWorldVisible(mod.id)) return;
        this.bus.push(
          { deferred: { ...e, source: mod.id, origin: e.origin ?? "external" } },
          { trigger: opts?.trigger }
        );
      },
      pushCandidate: async (spec, opts) => {
        if (!lease.active) throw new Error(`World ${mod.id} \u7684\u5BBF\u4E3B\u751F\u547D\u5468\u671F\u5DF2\u7ED3\u675F`);
        if (spec.sourceEvents.length === 0) throw new Error("\u5019\u9009\u7968\u636E\u81F3\u5C11\u9700\u8981\u4E00\u6761\u539F\u59CB\u4E8B\u4EF6");
        const origin = spec.origin ?? "external";
        const sourceEvents = spec.sourceEvents.map((event) => this.store.append({
          ...event,
          source: mod.id,
          origin,
          contextDelivery: "archive-only"
        }));
        if (this.isWorldVisible(mod.id)) {
          this.bus.push({
            candidate: {
              source: mod.id,
              origin,
              sourceEvents,
              gateText: spec.gateText,
              value: spec.value,
              project: spec.project
            }
          }, { trigger: opts?.trigger });
        } else {
          this.loop.acknowledgeDiscarded(sourceEvents);
        }
        return sourceEvents;
      },
      store: this.store,
      drainPendingEvents: async (filter) => {
        if (!lease.active) return [];
        const taken = this.bus.drainPending((it) => it.event?.origin === "external" && filter(it.event)).map((it) => it.event);
        if (taken.length > 0) this.loop.acknowledgeDiscarded(taken);
        return taken;
      },
      modelFacts: this.modelFacts(),
      blob: (handle) => this.resolveBlob(handle),
      reportUsage: (usage, opts) => {
        if (lease.active) this.reportWorldUsage(mod.id, usage, opts);
      },
      llmStalls: async (withinMs) => this.loop.llmStalls(withinMs),
      // 每次访问重新检查 Persona 开关，关闭后 getter 立即返回 undefined。
      get cognition() {
        return lease.active ? self.makeCognition(mod, () => lease.active) : void 0;
      },
      log: this.runlog.logger(`worlds.${mod.id}`)
    };
  }
  /**
   * World 上报的用量按 `worlds.<World>` 仪表项计入 session 统计和 usage.jsonl。
   * 用量标签不携带模型用途语义。
   */
  reportWorldUsage(worldId, usage, opts) {
    const id = `worlds.${worldId}`;
    let track = this.moduleUsageTracks.get(id);
    if (!track) {
      track = this.sessions.open(id, opts?.label ?? `${worldId}World \u81EA\u5E26\u6A21\u578B`, { id });
      this.moduleUsageTracks.set(id, track);
    }
    track.record(usage, void 0, opts?.model, { charges: opts?.charges });
  }
  async start() {
    const dataDir = this.loaded.dataDir;
    if (!existsSync13(dataDir)) mkdirSync11(dataDir, { recursive: true });
    const repair = this.session.load();
    if (repair) {
      this.log.warn(
        repair.kind === "torn-tail" ? "session \u672B\u884C\u672A\u5199\u5B8C,\u5DF2\u622A\u6389" : "session \u672B\u884C\u7F3A\u6362\u884C,\u5DF2\u8865\u4E0A",
        { ...repair, file: "session-main.jsonl" }
      );
    }
    for (const mod of this.worlds) {
      try {
        await mod.start(this.makeHost(mod));
      } catch (error) {
        const lease = this.moduleHostLeases.get(mod);
        if (lease) lease.active = false;
        throw error;
      }
      this.log.info(`World \u5DF2\u542F\u52A8: ${mod.id}`);
    }
    this.started = true;
    if (this.worlds.length === 0) this.log.warn("\u6CA1\u6709\u6302\u8F7D\u4EFB\u4F55 World:agent \u6536\u4E0D\u5230\u5916\u90E8\u4E8B\u4EF6");
    this.timers.start();
    this.runPromise = this.loop.run().catch((e) => {
      this.timers.stop();
      this.log.error("\u4E3B\u5FAA\u73AF\u5F02\u5E38\u9000\u51FA", { err: e });
    });
    writeRunJson(this.run, {
      bot: this.loaded.config.displayName,
      worlds: this.worlds.map((m) => m.id),
      activeProvider: this.loaded.config.activeProvider
    });
    this.log.emit("info", "core\u5DF2\u542F\u52A8", { event: "started", data: { run: this.run.id } });
  }
  /** 先终止主循环，再并发停止 World；各步骤有独立期限，失败写入返回结果。 */
  /**
   * 运行中挂载一个 World:入表,core 已启动则立即 start,并重建 system 前缀
   * (环境提示词段与工具表同属缓存前缀,挂载必须连带换掉)。start 抛错时不入表。
   */
  async mountWorld(mod) {
    if (this.worlds.some((m) => m.id === mod.id)) throw new Error(`World \u5DF2\u6302\u8F7D: ${mod.id}`);
    if (this.started) {
      try {
        await mod.start(this.makeHost(mod));
      } catch (error) {
        const lease = this.moduleHostLeases.get(mod);
        if (lease) lease.active = false;
        throw error;
      }
      this.log.info(`World \u5DF2\u542F\u52A8: ${mod.id}`);
    }
    this.worlds.push(mod);
    if (this.started) await this.loop.reloadSystemPrefix();
  }
  /** 停止 World 后使租约失效、移出挂载表并重建前缀；停止失败或超时仍继续卸载。 */
  async unmountWorld(id) {
    const index = this.worlds.findIndex((m) => m.id === id);
    if (index < 0) throw new Error(`\u672A\u6302\u8F7D\u7684 World: ${id}`);
    const mod = this.worlds[index];
    let failure = null;
    if (this.started) {
      try {
        await withDeadline(mod.stop(), MODULE_STOP_MS);
      } catch (e) {
        const detail = e instanceof Error ? e.message : String(e);
        this.log.warn(`World \u505C\u6B62\u5931\u8D25: ${mod.id}`, { err: detail });
        failure = { worldId: mod.id, detail };
      }
    }
    const lease = this.moduleHostLeases.get(mod);
    if (lease) lease.active = false;
    this.worlds.splice(this.worlds.indexOf(mod), 1);
    this.log.info(`World \u5DF2\u5378\u8F7D: ${mod.id}`);
    if (this.started) await this.loop.reloadSystemPrefix();
    return failure;
  }
  async stop() {
    this.started = false;
    this.loop.stop();
    this.timers.stop();
    const failures = [];
    if (this.runPromise) {
      try {
        await withDeadline(this.runPromise, LOOP_DRAIN_MS, "\u4E3B\u5FAA\u73AF\u7EC8\u6B62");
      } catch (e) {
        const detail = e instanceof Error ? e.message : String(e);
        this.log.warn("\u4E3B\u5FAA\u73AF\u672A\u5728\u5173\u673A\u671F\u9650\u5185\u7ED3\u675F", { err: detail });
        failures.push({ worldId: "core.loop", detail });
      } finally {
        this.loop.seal();
        this.runPromise = null;
      }
    } else {
      this.loop.seal();
    }
    const moduleFailures = (await Promise.all(this.worlds.map(async (mod) => {
      try {
        await withDeadline(mod.stop(), MODULE_STOP_MS);
        return null;
      } catch (e) {
        const detail = e instanceof Error ? e.message : String(e);
        this.log.warn(`World \u505C\u6B62\u5931\u8D25: ${mod.id}`, { err: detail });
        return { worldId: mod.id, detail };
      } finally {
        const lease = this.moduleHostLeases.get(mod);
        if (lease) lease.active = false;
      }
    }))).filter((failure) => failure !== null);
    failures.push(...moduleFailures);
    this.usageLog.flush();
    const ledger = this.usageLog.status();
    if (ledger.pending) failures.push({ worldId: "core.usage", detail: `${ledger.pending} usage records remain unwritten: ${ledger.error}` });
    this.log.info("core\u5DF2\u505C\u6B62");
    return failures;
  }
};

// src/stella-persona.ts
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join as join11 } from "node:path";
var StellaPersona = class {
  core = null;
  /** 隔离目录：Persona 自身不落任何数据，仅满足 Core 的路径要求。 */
  memoryDir = mkdtempSync(join11(tmpdir(), "stella-persona-"));
  blobs = {
    put: (name) => `mem:${name}`,
    get: () => null,
    list: () => []
  };
  attach(core) {
    this.core = core;
  }
  async systemSegments() {
    return [{ title: "STELLA", text: "Stella projection-owned runtime." }];
  }
  declareSessions() {
    const turnRounds = { soft: 1, hard: 1, softHint: () => null };
    return [
      {
        id: "main",
        label: "stella-main",
        rounds: () => turnRounds,
        persistent: true,
        receivesEvents: true,
        tools: () => []
      },
      {
        // fork 模板：恰好一次 provider 调用、零工具（BC-1/BC-2 的结构保险）。
        id: "turn",
        label: "stella-turn",
        rounds: () => turnRounds,
        persistent: false,
        receivesEvents: false,
        tools: () => []
      }
    ];
  }
};

// src/host.ts
var PROTOCOL_VERSION = 1;
var MAX_FRAME_BYTES = 4 * 1024 * 1024;
var HOST_VERSION = 1;
var DRAIN_TIMEOUT_MS = 3e4;
var BRIDGE_ORIGIN = {
  instance: "stella-rpc-bridge",
  module: "stella-rpc-bridge",
  model: "python-provider",
  compatibilityDomain: "stella-rpc-bridge"
};
var protoWrite = process2.stdout.write.bind(process2.stdout);
process2.stdout.write = ((chunk, ...rest) => {
  process2.stderr.write(chunk, ...rest);
  return true;
});
function send(env) {
  const line = JSON.stringify(env);
  if (Buffer.byteLength(line, "utf8") + 1 > MAX_FRAME_BYTES) {
    process2.stderr.write(`[host] \u51FA\u7AD9\u5E27\u8D85\u9650\u88AB\u4E22\u5F03\uFF08\u6709\u754C\u5931\u8D25\uFF09
`);
    return;
  }
  protoWrite(line + "\n");
}
function reply(reqId, result) {
  send({ v: PROTOCOL_VERSION, id: reqId, kind: "response", ts: Date.now() / 1e3, result });
}
function replyError(reqId, code, errMessage, retryable = false) {
  send({
    v: PROTOCOL_VERSION,
    id: reqId,
    kind: "response",
    ts: Date.now() / 1e3,
    error: { code, message: errMessage, retryable }
  });
}
var RpcBridge = class {
  constructor(key, sendRequest) {
    this.key = key;
    this.sendRequest = sendRequest;
  }
  key;
  sendRequest;
  pending = /* @__PURE__ */ new Map();
  bind() {
    return this;
  }
  /** host 取消/超时/reset 路径：拒绝全部在途 provider 请求。 */
  failAll(reason) {
    for (const [id, p] of this.pending) {
      this.pending.delete(id);
      p.reject(reason);
    }
  }
  async respond(request, _options) {
    const reqId = randomUUID();
    const promise = new Promise((resolve2, reject) => {
      this.pending.set(reqId, { resolve: resolve2, reject });
    });
    send({
      v: PROTOCOL_VERSION,
      id: reqId,
      kind: "request",
      method: "provider.respond",
      ts: Date.now() / 1e3,
      params: { key: this.key, request: { model: request.model, input: request.input, tools: request.tools } }
    });
    const result = await promise;
    const text2 = String(result.text ?? "");
    const response = createResponse(randomUUID(), request);
    response.output = [message("assistant", text2).item];
    const attempt = {
      id: randomUUID(),
      generationId: response.id,
      ordinal: 0,
      origin: BRIDGE_ORIGIN,
      startedAt: (/* @__PURE__ */ new Date()).toISOString(),
      elapsedMs: 0,
      requestId: null,
      responseId: response.id,
      outcome: "completed",
      status: 200,
      serviceTier: "default",
      charges: [],
      meters: { input: null, output: null, total: null, cachedInput: null, uncachedInput: null, reasoning: null, native: null }
    };
    return { response, origin: BRIDGE_ORIGIN, attempts: [attempt] };
  }
  /** host 读循环派发 provider.respond 的响应；返回是否命中本桥的在途请求。 */
  resolve(reqId, payload) {
    const p = this.pending.get(reqId);
    if (!p) return false;
    this.pending.delete(reqId);
    if (payload instanceof Error) p.reject(payload);
    else p.resolve(payload);
    return true;
  }
};
var SessionRegistry = class {
  epochs = /* @__PURE__ */ new Map();
  cores = /* @__PURE__ */ new Map();
  bridges = /* @__PURE__ */ new Map();
  inflight = /* @__PURE__ */ new Map();
  /** 出站请求（provider.respond 等）的 future 登记表，读循环派发用。 */
  outbound = /* @__PURE__ */ new Map();
  shuttingDown = false;
  /** 读循环派发：把 provider.respond 的响应路由给对应会话桥。 */
  resolveBridge(id, payload) {
    for (const bridge of this.bridges.values()) {
      if (payload instanceof Error) {
        if (bridge.resolve(id, payload)) return true;
      } else if (bridge.resolve(id, payload)) return true;
    }
    return false;
  }
  outboundSend(method, params) {
    return new Promise((resolve2, reject) => {
      const id = randomUUID();
      this.outbound.set(id, { resolve: resolve2, reject });
      send({ v: PROTOCOL_VERSION, id, kind: "request", method, ts: Date.now() / 1e3, params });
    });
  }
  loadConfig() {
    const cfg = JSON.parse(process2.env.STELLA_RUNTIME_CONFIG || "{}");
    if (!cfg.providers || !cfg.activeProvider) {
      throw new Error("\u7F3A\u5C11 STELLA_RUNTIME_CONFIG\uFF08providers/activeProvider\uFF09");
    }
    return cfg;
  }
  dataDirFor(key) {
    const dataRoot = process2.env.STELLA_RUNTIME_DATA_ROOT || "stella-runtime-data";
    const safe = key.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 64);
    return `${dataRoot}/${safe}`;
  }
  /** 取得（或懒创建）会话 Core，并递增 owner_epoch。 */
  async ensure(key) {
    const epoch = (this.epochs.get(key) ?? 0) + 1;
    this.epochs.set(key, epoch);
    if (!this.cores.has(key)) {
      const cfg = this.loadConfig();
      const dataDir = this.dataDirFor(key);
      const bridge = new RpcBridge(key, (method, p) => this.outboundSend(method, p));
      this.bridges.set(key, bridge);
      const core = new Core(
        {
          config: cfg,
          secret: () => process2.env.STELLA_RUNTIME_SECRET ?? "fake-key",
          rootDir: dataDir,
          memoryDir: `${dataDir}/persona`,
          dataDir
        },
        { persona: new StellaPersona(), worlds: [], llm: bridge }
      );
      await core.start();
      this.cores.set(key, core);
    }
    return epoch;
  }
  async submit(reqId, params) {
    const key = String(params.key ?? "");
    const turnId = String(params.turn_id ?? "");
    const ownerEpoch = Number(params.owner_epoch ?? 0);
    const deadlineMs = Number(params.deadline_ms ?? 0);
    const decision = params.decision ?? { kind: "generate" };
    const projection = params.projection ?? [];
    if (!key || !turnId) {
      replyError(reqId, "E_PROTOCOL", "key/turn_id \u7F3A\u5931");
      return;
    }
    if (this.epochs.get(key) !== ownerEpoch) {
      replyError(reqId, "E_KEY", `owner_epoch \u8FC7\u671F\uFF08\u5F53\u524D ${this.epochs.get(key) ?? 0}\uFF09`);
      return;
    }
    if (this.inflight.has(key)) {
      replyError(reqId, "E_BUSY", "\u540C\u4F1A\u8BDD\u5DF2\u6709\u5728\u9014\u8F6E\u6B21");
      return;
    }
    if (this.shuttingDown) {
      replyError(reqId, "E_HOST_GONE", "host \u6B63\u5728\u5173\u95ED");
      return;
    }
    const target = this.cores.get(key);
    if (!target) {
      replyError(reqId, "E_KEY", "\u4F1A\u8BDD\u672A ensure\uFF08\u5148\u8C03 session.ensure\uFF09");
      return;
    }
    const bridge = new RpcBridge(key, (method, p) => this.outboundSend(method, p));
    const controller = new AbortController();
    const state = { turnId, reqId, bridge, controller, deadlineTimer: null, settled: false };
    this.inflight.set(key, state);
    const settleError = (code, msg) => {
      if (state.settled) return;
      state.settled = true;
      if (state.deadlineTimer) clearTimeout(state.deadlineTimer);
      this.inflight.delete(key);
      bridge.failAll(new Error(msg));
      replyError(reqId, code, msg);
    };
    state.deadlineTimer = deadlineMs > 0 ? setTimeout(() => settleError("E_DEADLINE", `\u8F6E\u6B21\u8D85\u8FC7 ${deadlineMs}ms \u622A\u6B62`), deadlineMs) : null;
    const messages = projection.map((p) => message(p.role, p.text));
    const forkOpts = {
      id: "turn",
      messages,
      ...decision.kind !== "generate" ? { turnPolicy: () => decision } : {}
    };
    try {
      const text2 = await target.spawnFork(forkOpts);
      if (state.settled) return;
      state.settled = true;
      if (state.deadlineTimer) clearTimeout(state.deadlineTimer);
      this.inflight.delete(key);
      const kind = decision.kind;
      reply(reqId, {
        outcome: kind,
        text: kind === "generate" ? text2 : kind === "direct" ? decision.text : ""
      });
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      const code = controller.signal.aborted ? "E_CANCELLED" : "E_PROVIDER";
      settleError(code, msg);
    }
  }
  cancel(key, turnId) {
    const state = this.inflight.get(key);
    if (!state || state.turnId !== turnId) return;
    state.controller.abort(new Error("\u8F6E\u6B21\u5DF2\u88AB\u53D6\u6D88"));
    state.bridge.failAll(new Error("provider \u8C03\u7528\u5DF2\u53D6\u6D88"));
  }
  async reset(key, ownerEpoch) {
    if (this.epochs.get(key) !== ownerEpoch) {
      throw new Error(`owner_epoch \u8FC7\u671F\uFF08\u5F53\u524D ${this.epochs.get(key) ?? 0}\uFF09`);
    }
    const state = this.inflight.get(key);
    if (state) {
      state.controller.abort(new Error("reset \u53D6\u6D88\u5728\u9014\u8F6E\u6B21"));
      state.bridge.failAll(new Error("reset \u53D6\u6D88\u5728\u9014\u8F6E\u6B21"));
      this.inflight.delete(key);
      state.settled = true;
      if (state.deadlineTimer) clearTimeout(state.deadlineTimer);
      replyError(state.reqId, "E_CANCELLED", "reset \u53D6\u6D88\u5728\u9014\u8F6E\u6B21");
    }
    const core = this.cores.get(key);
    if (core) await core.loop.clearSession();
  }
  async drain() {
    const deadline = Date.now() + DRAIN_TIMEOUT_MS;
    while (this.inflight.size > 0 && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 25));
    }
    return this.inflight.size;
  }
  async shutdown() {
    this.shuttingDown = true;
    await this.drain();
    for (const core of this.cores.values()) {
      await core.stop();
    }
    this.cores.clear();
  }
  health() {
    return {
      keys: [...this.epochs.keys()],
      inflight: this.inflight.size,
      cores: this.cores.size
    };
  }
};
async function main() {
  const registry = new SessionRegistry();
  const rl = createInterface({ input: process2.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => {
    if (!line.trim()) return;
    if (Buffer.byteLength(line, "utf8") > MAX_FRAME_BYTES) {
      process2.stderr.write("[host] \u5165\u7AD9\u5E27\u8D85\u9650\uFF0C\u65AD\u94FE\uFF08\u6709\u754C\u5931\u8D25\uFF09\n");
      process2.exit(2);
    }
    let env;
    try {
      env = JSON.parse(line);
    } catch (e) {
      process2.stderr.write(`[host] \u5165\u7AD9\u5E27\u89E3\u6790\u5931\u8D25: ${e}
`);
      return;
    }
    void dispatch(env);
  });
  rl.on("close", () => {
    process2.exit(0);
  });
  async function dispatch(env) {
    const id = String(env.id ?? "");
    const kind = env.kind;
    try {
      if (kind === "response") {
        const p = registry.outbound.get(id);
        if (p) {
          registry.outbound.delete(id);
          if (env.error) p.reject(new Error(String(env.error.message)));
          else p.resolve(env.result ?? {});
          return;
        }
        if (env.error) {
          if (registry.resolveBridge(id, new Error(String(env.error.message)))) return;
        } else {
          if (registry.resolveBridge(id, env.result ?? {})) return;
        }
        return;
      }
      if (kind !== "request") return;
      const method = String(env.method ?? "");
      const params = env.params ?? {};
      switch (method) {
        case "runtime.hello":
          reply(id, {
            host_version: HOST_VERSION,
            protocol_version: PROTOCOL_VERSION,
            node: process2.version,
            ...registry.health()
          });
          return;
        case "session.ensure": {
          const epoch = await registry.ensure(String(params.key ?? ""));
          reply(id, { owner_epoch: epoch });
          return;
        }
        case "turn.submit":
          await registry.submit(id, params);
          return;
        case "turn.cancel":
          registry.cancel(String(params.key ?? ""), String(params.turn_id ?? ""));
          reply(id, { cancelled: true });
          return;
        case "session.reset":
          await registry.reset(String(params.key ?? ""), Number(params.owner_epoch ?? 0));
          reply(id, { reset: true });
          return;
        case "runtime.drain": {
          const pending = await registry.drain();
          reply(id, { pending });
          return;
        }
        case "runtime.shutdown": {
          const pending = await registry.shutdown();
          reply(id, { pending });
          setTimeout(() => process2.exit(0), 50);
          return;
        }
        default:
          replyError(id, "E_UNSUPPORTED", `\u672A\u77E5\u65B9\u6CD5: ${method}`);
      }
    } catch (error) {
      replyError(id, "E_PROVIDER", error instanceof Error ? error.message : String(error));
    }
  }
  await new Promise(() => {
  });
}
void main().catch((e) => {
  process2.stderr.write(`[host] fatal: ${e}
`);
  process2.exit(1);
});
