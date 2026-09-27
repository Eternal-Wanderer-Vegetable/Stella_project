import type {
  EventEnvelope,
  EventGrepQuery,
  EventRangeQuery,
  WorldHost,
  ToolDef,
} from '../../core/types.ts';
import { renderEventLines } from '../../core/util.ts';
import {
  eventInConversation,
  parseConversationAddress,
  type Conv,
} from './conversation.ts';

interface HistoryToolDeps {
  source: string;
  host: () => WorldHost | undefined;
}

const NOT_STARTED = '[tool failed] QQ module not started';
const TARGET_FORMAT = '"group:<id>" or "private:<id>"';

function parseConversationFilter(raw: unknown): Conv | { error: string } | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const conversation = parseConversationAddress(raw);
  return conversation ?? {
    error: `"${raw.trim()}" is not a valid conversation; use ${TARGET_FORMAT} (numeric QQ group/user id, not a name)`,
  };
}

function matchesReadFilters(
  event: EventEnvelope,
  source: string,
  args: Record<string, unknown>,
  conversation: Conv | null,
): boolean {
  if (event.source !== source) return false;
  if (event.origin !== 'external') return false;
  if (typeof args.sender === 'string' && event.senderKey !== args.sender) return false;
  if (typeof args.from_time === 'string' && event.ts < args.from_time) return false;
  if (typeof args.to_time === 'string' && event.ts > args.to_time) return false;
  return !conversation || eventInConversation(event, conversation);
}

/**
 * 邻域读取的两个入口:
 *  - around      = 平台 message_id(消息行首的 `#<id>`),World 自己定位
 *  - around_time = ISO 时间,取该时刻之后的第一条为中心(没有号可用时的入口)
 * 两者都不涉及 core 事件游标——游标是存储位置,不进 agent 的词表。
 */
function readAround(
  host: WorldHost,
  source: string,
  args: Record<string, unknown>,
  conversation: Conv | null,
): EventEnvelope[] {
  const candidates = host.store
    .range({ source, origin: 'external' })
    .filter((event) => matchesReadFilters(event, source, args, conversation));
  let center = -1;
  if (args.around !== undefined && args.around !== null && String(args.around) !== '') {
    const mid = String(args.around).trim().replace(/^#/, '');
    center = candidates.findIndex((event) => String(event.meta?.message_id ?? '') === mid);
  } else if (typeof args.around_time === 'string' && args.around_time) {
    center = candidates.findIndex((event) => event.ts >= (args.around_time as string));
    // 给的时刻晚于全部记录时,以最后一条为中心
    if (center < 0 && candidates.length > 0) center = candidates.length - 1;
  }
  if (center < 0) return [];
  const before = args.before !== undefined ? Math.max(0, Number(args.before)) : 20;
  const after = args.after !== undefined ? Math.max(0, Number(args.after)) : 20;
  return candidates.slice(Math.max(0, center - before), center + after + 1);
}

function createReadHistoryTool(deps: HistoryToolDeps): ToolDef {
  return {
    name: 'qq_read_history',
    description:
      'Read QQ history: the neighborhood of one message (around / around_time), or a time range. Optional conversation and sender filters.',
    tags: ['read'],
    parameters: {
      type: 'object',
      properties: {
        around: {
          type: 'string',
          description: 'A QQ message id — the `#<id>` at the start of a message line. Reads the messages around it.',
        },
        around_time: {
          type: 'string',
          description: 'ISO 8601 time: reads around the first message at or after it. Use when you have no message id.',
        },
        before: { type: 'number', description: 'With around/around_time: how many earlier messages (default 20).' },
        after: { type: 'number', description: 'With around/around_time: how many later messages (default 20).' },
        from_time: { type: 'string', description: 'Start time, ISO 8601.' },
        to_time: { type: 'string', description: 'End time, ISO 8601.' },
        sender: { type: 'string', description: 'Filter by QQ number.' },
        conversation: {
          type: 'string',
          description: `Filter by conversation: ${TARGET_FORMAT} (numeric QQ group/user id, not a name).`,
        },
        limit: { type: 'number', description: 'Max results, default 50.' },
      },
      required: [],
    },
    handler: async (args) => {
      const host = deps.host();
      if (!host) return NOT_STARTED;
      const filter = parseConversationFilter(args.conversation);
      if (filter && 'error' in filter) return `[bad input] ${filter.error}`;
      const conversation = filter || null;
      const limit = args.limit !== undefined ? Number(args.limit) : 50;

      const hasAround =
        (args.around !== undefined && args.around !== null && String(args.around) !== '') ||
        (typeof args.around_time === 'string' && args.around_time !== '');
      let events: EventEnvelope[];
      if (hasAround) {
        events = readAround(host, deps.source, args, conversation);
      } else {
        const query: EventRangeQuery = {
          source: deps.source,
          origin: 'external',
          limit: conversation ? undefined : limit,
        };
        if (typeof args.from_time === 'string') query.fromTs = args.from_time;
        if (typeof args.to_time === 'string') query.toTs = args.to_time;
        if (typeof args.sender === 'string') query.senderKey = args.sender;
        events = host.store.range(query);
        if (conversation) {
          events = events.filter((event) => eventInConversation(event, conversation));
          if (events.length > limit) events = events.slice(events.length - limit);
        }
      }

      return events.length ? renderEventLines(events) : '(no matching messages)';
    },
  };
}

function createGrepHistoryTool(deps: HistoryToolDeps): ToolDef {
  return {
    name: 'qq_grep_history',
    description:
      'Keyword search over QQ history; each hit includes 3 messages of context on each side. Optional conversation and sender filters.',
    tags: ['read'],
    parameters: {
      type: 'object',
      properties: {
        keyword: { type: 'string', description: 'Keyword (plain substring match).' },
        sender: { type: 'string', description: 'Filter by QQ number.' },
        conversation: {
          type: 'string',
          description: `Filter by conversation: ${TARGET_FORMAT} (numeric QQ group/user id, not a name).`,
        },
        from_time: { type: 'string', description: 'Start time, ISO 8601.' },
        to_time: { type: 'string', description: 'End time, ISO 8601.' },
        limit: { type: 'number', description: 'Max hit groups, default 5.' },
      },
      required: ['keyword'],
    },
    handler: async (args) => {
      const host = deps.host();
      if (!host) return NOT_STARTED;
      const keyword = typeof args.keyword === 'string' ? args.keyword : '';
      if (!keyword) return '[bad input] keyword must not be empty';
      const filter = parseConversationFilter(args.conversation);
      if (filter && 'error' in filter) return `[bad input] ${filter.error}`;
      const conversation = filter || null;
      const limit = args.limit !== undefined ? Number(args.limit) : 5;

      const query: EventGrepQuery = {
        keyword,
        context: 3,
        source: deps.source,
        origin: 'external',
        limit: conversation ? undefined : limit,
      };
      if (typeof args.sender === 'string') query.senderKey = args.sender;
      if (typeof args.from_time === 'string') query.fromTs = args.from_time;
      if (typeof args.to_time === 'string') query.toTs = args.to_time;

      let hits = host.store.grep(query);
      if (conversation) {
        hits = hits.filter((hit) => {
          const event = hit.events.find((item) => item.cursor === hit.hitCursor);
          return !!event && eventInConversation(event, conversation);
        });
        if (hits.length > limit) hits = hits.slice(0, limit);
      }
      hits = hits.map((hit) => ({
        ...hit,
        events: hit.events.filter(
          (event) =>
            event.source === deps.source &&
            event.origin === 'external' &&
            (!conversation || eventInConversation(event, conversation)),
        ),
      }));

      return hits.length
        ? hits.map((hit) => renderEventLines(hit.events)).join('\n---\n')
        : `(no messages containing "${keyword}")`;
    },
  };
}

export function createHistoryTools(deps: HistoryToolDeps): ToolDef[] {
  return [createReadHistoryTool(deps), createGrepHistoryTool(deps)];
}
