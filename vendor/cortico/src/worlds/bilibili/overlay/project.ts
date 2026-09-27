import { giftFrameData } from '../gift-frame.ts';
import type { Normalized } from '../normalize.ts';
import type { OverlayAudienceEvent, OverlayAudienceFacts } from './types.ts';

export function projectOverlayEvent(
  msg: Record<string, unknown>,
  normalized: Normalized | null,
): OverlayAudienceEvent | null {
  const cmd = String(msg.cmd ?? '').split(':')[0];
  if (cmd === 'DANMU_MSG' || cmd === 'DANMU_MSG_MIRROR') return projectDanmaku(msg);
  if (!isGiftCommand(cmd)) return null;
  return projectGift(msg, cmd, normalized);
}

function projectDanmaku(msg: Record<string, unknown>): OverlayAudienceEvent | null {
  const info = Array.isArray(msg.info) ? msg.info as unknown[] : [];
  const body = string(info[1]).trim();
  if (!body) return null;
  const sender = array(info[2]);
  const medal = array(info[3]);
  const userLevel = array(info[4]);
  const rich = firstObject(
    object(array(info[0])[15]).user,
    object(array(info[0])[15]).user_info,
    object(array(info[0])[15]).sender_uinfo,
    msg.user_info,
    msg.sender_uinfo,
  );
  const base = firstObject(rich.base, rich);
  const uid = positiveNumber(sender[0]) || positiveNumber(object(rich).uid);
  const username = string(sender[1]) || string(object(base).name) || string(object(base).uname) || '某位观众';
  const guardLevel = optionalNumber(info[7]);
  const medalLevel = optionalNumber(medal[0]);
  const userLevelValue = optionalNumber(userLevel[0]);
  const rank = optionalNumber(sender[5]);
  const nameColor = typeof sender[7] === 'string' ? string(sender[7]) : undefined;
  const isAdmin = optionalBoolean(sender[2]);
  const vip = optionalBoolean(sender[3]);
  const svip = optionalBoolean(sender[4]);
  const facts: OverlayAudienceFacts = {
    ...(uid ? { uid: String(uid) } : {}),
    ...(guardLevel !== undefined ? { guardLevel } : {}),
    ...(medalLevel !== undefined ? { medalLevel } : {}),
    ...(typeof medal[1] === 'string' ? { medalName: string(medal[1]) } : {}),
    ...(typeof medal[2] === 'string' ? { medalAnchorName: string(medal[2]) } : {}),
    ...(optionalNumber(medal[3]) !== undefined ? { medalRoomId: optionalNumber(medal[3]) } : {}),
    ...(optionalNumber(medal[4]) !== undefined ? { medalColor: optionalNumber(medal[4]) } : {}),
    ...(isAdmin !== undefined ? { isAdmin } : {}),
    ...(vip !== undefined ? { vip } : {}),
    ...(svip !== undefined ? { svip } : {}),
    ...(rank !== undefined ? { rank } : {}),
    ...(nameColor !== undefined ? { nameColor } : {}),
    ...(userLevelValue !== undefined ? { userLevel: userLevelValue } : {}),
    eventKind: 'danmaku',
  };
  return {
    eventKind: 'danmaku',
    username,
    body,
    avatarUrl: faceUrl(rich, base),
    facts,
  };
}

function projectGift(
  msg: Record<string, unknown>,
  cmd: string,
  normalized: Normalized | null,
): OverlayAudienceEvent | null {
  // 解析告警由 normalize 负责。
  const data = giftFrameData(object(msg.data));
  const sender = firstObject(data.sender_uinfo, data.user_info);
  const base = firstObject(sender.base, sender);
  const uid = positiveNumber(data.uid) || positiveNumber(object(data.user_info).uid) || positiveNumber(object(sender).uid);
  const username = string(data.uname)
    || string(data.username)
    || string(object(data.user_info).uname)
    || string(object(base).name)
    || string(object(base).uname)
    || '某位观众';
  const guardLevel = firstNumber(data.guard_level, sender.guard_level);
  const medalLevel = optionalNumber(object(sender.medal).level);
  const medalName = typeof object(sender.medal).name === 'string' ? string(object(sender.medal).name) : undefined;
  const isAdmin = firstBoolean(sender.is_admin, object(data.user_info).manager);
  const vip = optionalBoolean(sender.vip);
  const svip = optionalBoolean(sender.svip);
  const userLevel = optionalNumber(sender.user_level);
  const facts: OverlayAudienceFacts = {
    ...(uid ? { uid: String(uid) } : {}),
    ...(guardLevel !== undefined ? { guardLevel } : {}),
    ...(medalLevel !== undefined ? { medalLevel } : {}),
    ...(medalName !== undefined ? { medalName } : {}),
    ...(isAdmin !== undefined ? { isAdmin } : {}),
    ...(vip !== undefined ? { vip } : {}),
    ...(svip !== undefined ? { svip } : {}),
    ...(userLevel !== undefined ? { userLevel } : {}),
    eventKind: 'gift',
  };
  const body = giftBody(cmd, data, normalized);
  if (!body) return null;
  return {
    eventKind: 'gift',
    username,
    body,
    avatarUrl: faceUrl(sender, base, data.user_info),
    facts,
  };
}

function giftBody(cmd: string, data: Record<string, unknown>, normalized: Normalized | null): string {
  if (cmd === 'SUPER_CHAT_MESSAGE') return `醒目留言 ¥${nonNegativeNumber(data.price)}：${string(data.message)}`;
  if (cmd === 'GUARD_BUY') return `开通 ${string(data.gift_name) || '大航海'} ×${positiveNumber(data.num) || 1}`;
  if (cmd === 'USER_TOAST_MSG' || cmd === 'USER_TOAST_MSG_V2') {
    // toast_msg 明确写明续费时才显示“续费”，否则使用中性措辞。V2 把角色名挪进了 guard_info。
    const rawRole = cmd === 'USER_TOAST_MSG_V2' ? object(data.guard_info).role_name : data.role_name;
    const role = string(rawRole) || '大航海';
    return `${string(data.toast_msg).includes('续费') ? '续费' : '上舰'} ${role}`;
  }
  if (cmd === 'SEND_GIFT' || cmd === 'SEND_GIFT_V2') {
    const gift = string(data.giftName) || string(data.gift_name) || '礼物';
    return `${gift} ×${positiveNumber(data.num) || 1}`;
  }
  return normalized?.kind === 'event' ? normalized.text : '';
}

function isGiftCommand(cmd: string): boolean {
  return cmd === 'SUPER_CHAT_MESSAGE'
    || cmd === 'GUARD_BUY'
    || cmd === 'USER_TOAST_MSG'
    || cmd === 'USER_TOAST_MSG_V2'
    || cmd === 'SEND_GIFT'
    || cmd === 'SEND_GIFT_V2';
}

function faceUrl(...values: unknown[]): string {
  for (const value of values) {
    const objValue = object(value);
    for (const candidate of [objValue.face, object(objValue.base).face]) {
      const raw = string(candidate);
      if (raw.startsWith('//')) return `https:${raw}`;
      if (/^https?:\/\//i.test(raw)) return raw;
    }
  }
  return '';
}

function firstObject(...values: unknown[]): Record<string, unknown> {
  for (const value of values) {
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  }
  return {};
}

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function string(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function positiveNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0;
}

function nonNegativeNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const number = optionalNumber(value);
    if (number !== undefined) return number;
  }
  return undefined;
}

function optionalBoolean(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value;
  if (value === 0 || value === 1) return value === 1;
  return undefined;
}

function firstBoolean(...values: unknown[]): boolean | undefined {
  for (const value of values) {
    const boolean = optionalBoolean(value);
    if (boolean !== undefined) return boolean;
  }
  return undefined;
}
