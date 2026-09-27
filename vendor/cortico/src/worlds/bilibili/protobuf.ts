/**
 * protobuf 线格式读取器，仅解字段号、wire type 与原始值，不使用 .proto 或执行类型映射；调用方解释字段布局。
 * 读取失败返回 null、undefined 或空串,由调用方处理。
 * 单值字段按 protobuf 语义取同字段号最后一次出现的值。
 */

/** 一个字段的原始读数。`varint` / `bytes` 按 wire type 二选一。 */
export interface PbField {
  readonly field: number;
  readonly wire: number;
  readonly varint?: bigint;
  readonly bytes?: Uint8Array;
}

const TEXT = new TextDecoder('utf-8', { fatal: true });

/**
 * 解析一层字段;内容截断、长度越界或 wire type 不受支持时返回 null。
 */
export function pbDecode(buf: Uint8Array): PbField[] | null {
  const out: PbField[] = [];
  let i = 0;
  while (i < buf.length) {
    const key = readVarint(buf, i);
    if (!key) return null;
    i = key.next;
    const field = Number(key.value >> 3n);
    const wire = Number(key.value & 7n);
    if (field <= 0) return null;
    if (wire === 0) {
      const value = readVarint(buf, i);
      if (!value) return null;
      i = value.next;
      out.push({ field, wire, varint: value.value });
    } else if (wire === 2) {
      const len = readVarint(buf, i);
      if (!len) return null;
      const start = len.next;
      const end = start + Number(len.value);
      if (!Number.isSafeInteger(end) || end > buf.length) return null;
      out.push({ field, wire, bytes: buf.subarray(start, end) });
      i = end;
    } else if (wire === 5 || wire === 1) {
      const width = wire === 5 ? 4 : 8;
      if (i + width > buf.length) return null;
      out.push({ field, wire, bytes: buf.subarray(i, i + width) });
      i += width;
    } else {
      return null;
    }
  }
  return out;
}

/** 按 Node Buffer 的 base64 规则解码;空输入、空结果或 protobuf 解析失败时返回 null。 */
export function pbFromBase64(value: unknown): PbField[] | null {
  if (typeof value !== 'string' || !value) return null;
  let bytes: Buffer;
  try {
    bytes = Buffer.from(value, 'base64');
  } catch {
    return null;
  }
  if (bytes.length === 0) return null;
  return pbDecode(bytes);
}

/** 将字段字节解析为嵌套消息；缺少字节或解析失败时返回 null。 */
export function pbSub(fields: readonly PbField[] | null, field: number): PbField[] | null {
  const bytes = pick(fields, field)?.bytes;
  return bytes ? pbDecode(bytes) : null;
}

/** 将字段字节解码为 UTF-8；缺少字节、解码失败或包含控制字符时返回空串。 */
export function pbText(fields: readonly PbField[] | null, field: number): string {
  const bytes = pick(fields, field)?.bytes;
  if (!bytes) return '';
  let text: string;
  try {
    text = TEXT.decode(bytes);
  } catch {
    return '';
  }
  return hasControlChars(text) ? '' : text;
}

/**
 * 读取 varint;缺失或超出 JavaScript 安全整数范围时返回 undefined。
 */
export function pbInt(fields: readonly PbField[] | null, field: number): number | undefined {
  const value = pick(fields, field)?.varint;
  if (value === undefined) return undefined;
  const num = Number(value);
  return Number.isSafeInteger(num) ? num : undefined;
}

function hasControlChars(text: string): boolean {
  for (let i = 0; i < text.length; i += 1) {
    if (text.charCodeAt(i) < 0x20) return true;
  }
  return false;
}

function pick(fields: readonly PbField[] | null, field: number): PbField | undefined {
  if (!fields) return undefined;
  for (let i = fields.length - 1; i >= 0; i -= 1) {
    if (fields[i].field === field) return fields[i];
  }
  return undefined;
}

/** varint 最多读取 10 字节;没有终止位时返回 null。 */
function readVarint(buf: Uint8Array, from: number): { value: bigint; next: number } | null {
  let value = 0n;
  let shift = 0n;
  for (let i = from; i < buf.length && i - from < 10; i += 1) {
    const byte = buf[i];
    value |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return { value, next: i + 1 };
    shift += 7n;
  }
  return null;
}
