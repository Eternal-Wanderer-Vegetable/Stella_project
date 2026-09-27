/**
 * B 站直播长连的帧编解码。
 *
 * 帧头固定 16 字节:总长 u32 | 头长 u16 | protover u16 | op u32 | seq u32。
 * 一个 WebSocket 消息可包含多个包;op=5 且 protover 为 2/3 时,包体是 zlib/brotli 压缩的嵌套包序列。
 */
import { brotliDecompressSync, inflateSync } from 'node:zlib';

export const OP = {
  HEARTBEAT: 2,
  HEARTBEAT_REPLY: 3,
  MESSAGE: 5,
  AUTH: 7,
  AUTH_REPLY: 8,
} as const;

const HEADER_LEN = 16;

/** 编码为未压缩包（protover 1）。 */
export function encodePacket(op: number, body: string): Buffer {
  const payload = Buffer.from(body, 'utf8');
  const buf = Buffer.alloc(HEADER_LEN + payload.length);
  buf.writeUInt32BE(HEADER_LEN + payload.length, 0);
  buf.writeUInt16BE(HEADER_LEN, 4);
  buf.writeUInt16BE(1, 6);
  buf.writeUInt32BE(op, 8);
  buf.writeUInt32BE(1, 12);
  payload.copy(buf, HEADER_LEN);
  return buf;
}

export type Frame =
  | { kind: 'auth'; code: number }
  | { kind: 'popularity'; value: number }
  | { kind: 'cmd'; msg: Record<string, unknown> };

interface RawPacket {
  ver: number;
  op: number;
  body: Buffer;
}

/** 长度字段越界时停止解析,丢弃剩余字节。 */
function* iterPackets(buf: Buffer): Generator<RawPacket> {
  let off = 0;
  while (off + HEADER_LEN <= buf.length) {
    const total = buf.readUInt32BE(off);
    const headLen = buf.readUInt16BE(off + 4);
    const ver = buf.readUInt16BE(off + 6);
    const op = buf.readUInt32BE(off + 8);
    if (total < headLen || headLen < HEADER_LEN || off + total > buf.length) return;
    yield { ver, op, body: buf.subarray(off + headLen, off + total) };
    off += total;
  }
}

/** 解码消息中的包;解压或 JSON 解析失败的包跳过。 */
export function parseFrame(buf: Buffer): Frame[] {
  const out: Frame[] = [];
  collect(buf, out);
  return out;
}

function collect(buf: Buffer, out: Frame[]): void {
  for (const pkt of iterPackets(buf)) {
    if (pkt.op === OP.AUTH_REPLY) {
      out.push({ kind: 'auth', code: readJson(pkt.body)?.code as number ?? 0 });
    } else if (pkt.op === OP.HEARTBEAT_REPLY) {
      out.push({ kind: 'popularity', value: pkt.body.length >= 4 ? pkt.body.readUInt32BE(0) : 0 });
    } else if (pkt.op === OP.MESSAGE) {
      if (pkt.ver === 2 || pkt.ver === 3) {
        let inner: Buffer;
        try {
          inner = pkt.ver === 2 ? inflateSync(pkt.body) : brotliDecompressSync(pkt.body);
        } catch {
          continue;
        }
        collect(inner, out);
      } else {
        const msg = readJson(pkt.body);
        if (msg) out.push({ kind: 'cmd', msg });
      }
    }
  }
}

function readJson(body: Buffer): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(body.toString('utf8'));
    return parsed !== null && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
