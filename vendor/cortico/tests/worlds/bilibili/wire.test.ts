import { describe, expect, it } from 'vitest';
import { brotliCompressSync, deflateSync } from 'node:zlib';
import { encodePacket, OP, parseFrame } from '../../../src/worlds/bilibili/wire.ts';

/** 手搓一个包(测试自己不复用被测的 encodePacket,免得两边一起错) */
function packet(op: number, ver: number, body: Buffer): Buffer {
  const buf = Buffer.alloc(16 + body.length);
  buf.writeUInt32BE(16 + body.length, 0);
  buf.writeUInt16BE(16, 4);
  buf.writeUInt16BE(ver, 6);
  buf.writeUInt32BE(op, 8);
  buf.writeUInt32BE(1, 12);
  body.copy(buf, 16);
  return buf;
}

const json = (o: unknown): Buffer => Buffer.from(JSON.stringify(o), 'utf8');

describe('帧编解码', () => {
  it('encodePacket 写出 16 字节头与不压缩标记', () => {
    const buf = encodePacket(OP.AUTH, '{"uid":0}');
    expect(buf.readUInt32BE(0)).toBe(buf.length);
    expect(buf.readUInt16BE(4)).toBe(16);
    expect(buf.readUInt16BE(6)).toBe(1);
    expect(buf.readUInt32BE(8)).toBe(OP.AUTH);
    expect(buf.subarray(16).toString('utf8')).toBe('{"uid":0}');
  });

  it('认证回执与心跳回执各自成帧', () => {
    const frames = parseFrame(
      Buffer.concat([
        packet(OP.AUTH_REPLY, 1, json({ code: 0 })),
        packet(OP.HEARTBEAT_REPLY, 1, (() => {
          const b = Buffer.alloc(4);
          b.writeUInt32BE(1234, 0);
          return b;
        })()),
      ]),
    );
    expect(frames).toEqual([
      { kind: 'auth', code: 0 },
      { kind: 'popularity', value: 1234 },
    ]);
  });

  it('brotli 包体里套着多条消息,一并摊平', () => {
    const inner = Buffer.concat([
      packet(OP.MESSAGE, 0, json({ cmd: 'DANMU_MSG', info: ['a'] })),
      packet(OP.MESSAGE, 0, json({ cmd: 'WATCHED_CHANGE', data: { num: 7 } })),
    ]);
    const frames = parseFrame(packet(OP.MESSAGE, 3, brotliCompressSync(inner)));
    expect(frames.map((f) => (f.kind === 'cmd' ? f.msg.cmd : f.kind))).toEqual([
      'DANMU_MSG',
      'WATCHED_CHANGE',
    ]);
  });

  it('zlib(protover 2)同样解得开', () => {
    const inner = packet(OP.MESSAGE, 0, json({ cmd: 'SEND_GIFT' }));
    const frames = parseFrame(packet(OP.MESSAGE, 2, deflateSync(inner)));
    expect(frames).toHaveLength(1);
    expect(frames[0]).toMatchObject({ kind: 'cmd' });
  });

  it('解不开的压缩包只丢自己,不影响同帧其他包', () => {
    const frames = parseFrame(
      Buffer.concat([
        packet(OP.MESSAGE, 3, Buffer.from([0xff, 0xff, 0xff])),
        packet(OP.MESSAGE, 0, json({ cmd: 'LIVE' })),
      ]),
    );
    expect(frames).toEqual([{ kind: 'cmd', msg: { cmd: 'LIVE' } }]);
  });

  it('半包就地停下,已完整的那条照常给出', () => {
    const whole = Buffer.concat([
      packet(OP.MESSAGE, 0, json({ cmd: 'LIVE' })),
      packet(OP.MESSAGE, 0, json({ cmd: 'PREPARING' })),
    ]);
    const frames = parseFrame(whole.subarray(0, whole.length - 5));
    expect(frames).toEqual([{ kind: 'cmd', msg: { cmd: 'LIVE' } }]);
  });

  it('包体不是 JSON 时整条跳过', () => {
    const frames = parseFrame(packet(OP.MESSAGE, 0, Buffer.from('not json', 'utf8')));
    expect(frames).toEqual([]);
  });
});
