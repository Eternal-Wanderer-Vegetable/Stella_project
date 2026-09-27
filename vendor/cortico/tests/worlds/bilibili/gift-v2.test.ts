/**
 * SEND_GIFT_V2 使用 gift-v2-frames.ts 中保留真实字段布局、身份项已替换为假值的 protobuf 帧。
 */
import { describe, expect, it } from 'vitest';
import { giftFrameData } from '../../../src/worlds/bilibili/gift-frame.ts';
import { normalize } from '../../../src/worlds/bilibili/normalize.ts';
import { projectOverlayEvent } from '../../../src/worlds/bilibili/overlay/project.ts';
import { pbDecode, pbInt, pbSub, pbText } from '../../../src/worlds/bilibili/protobuf.ts';
import { PB_BIG, PB_SMALL } from './gift-v2-frames.ts';

const OPTS = { giftFlushYuan: 1 };

function v2(pb: string): Record<string, unknown> {
  return { cmd: 'SEND_GIFT_V2', danmu: { area: 1 }, data: { dmscore: 462, pb } };
}

function warnSink(): {
  warn: (message: string, data?: Record<string, unknown>) => void;
  messages: string[];
} {
  const messages: string[] = [];
  return { warn: (message) => void messages.push(message), messages };
}

describe('protobuf 线格式读取器', () => {
  it('拆出字段、嵌套与字符串,同字段号后来者覆盖', () => {
    // 08 96 01 = field1 varint 150;12 02 68 69 = field2 "hi";1a 02 08 07 = field3 {1:7}
    const buf = Uint8Array.from([0x08, 0x96, 0x01, 0x12, 0x02, 0x68, 0x69, 0x1a, 0x02, 0x08, 0x07, 0x08, 0x01]);
    const fields = pbDecode(buf);
    expect(fields).not.toBeNull();
    expect(pbInt(fields, 1)).toBe(1); // 后来者覆盖:150 之后又来了一个 1
    expect(pbText(fields, 2)).toBe('hi');
    expect(pbInt(pbSub(fields, 3), 1)).toBe(7);
  });

  it('截断、越界与废弃的 group wire type 一律给 null,不抛', () => {
    expect(pbDecode(Uint8Array.from([0x08]))).toBeNull(); // varint 没读完
    expect(pbDecode(Uint8Array.from([0x12, 0x05, 0x61]))).toBeNull(); // 声称 5 字节只有 1
    expect(pbDecode(Uint8Array.from([0x0b, 0x00]))).toBeNull(); // wire type 3(group)
    expect(pbText(pbDecode(Uint8Array.from([0x0a, 0x02, 0xff, 0xfe])), 1)).toBe(''); // 不是 UTF-8
  });
});

describe('SEND_GIFT_V2 真帧', () => {
  it('付费礼物成事件,金额、名字、身份、头像都从 pb 里读出来', () => {
    expect(normalize(v2(PB_SMALL), OPTS)).toMatchObject({
      kind: 'event',
      type: 'bilibili.gift',
      trigger: 'debounce', // ¥0.10 不到插队门槛
      text: '[礼物 ¥0.10|测试观众甲] 粉丝团灯牌×1',
      senderKey: '10001',
      meta: {
        uid: 10001,
        uname: '测试观众甲',
        gift: '粉丝团灯牌',
        num: 1,
        yuan: 0.1,
        avatarUrl: 'https://i0.hdslb.com/bfs/face/0000000000000000000000000000000000000000.jpg',
        tid: '4800000000000000001',
      },
      coalesce: { kind: 'gift', gift: '粉丝团灯牌', num: 1, yuan: 0.1 },
    });
  });

  it('大额礼物照样插队', () => {
    expect(normalize(v2(PB_BIG), OPTS)).toMatchObject({
      trigger: 'flush',
      text: '[礼物 ¥50|测试观众乙] 亲密之旅×1',
      senderKey: '10002',
      meta: { yuan: 50, gift: '亲密之旅' },
    });
  });

  it('coin_type 从 pb 里读出 gold,不再被当成免费礼物记进读数', () => {
    const frame = giftFrameData((v2(PB_SMALL).data) as Record<string, unknown>);
    expect(frame).toMatchObject({ coin_type: 'gold', total_coin: 100, giftName: '粉丝团灯牌', num: 1 });
    expect(normalize(v2(PB_SMALL), OPTS)).not.toMatchObject({ kind: 'count' });
  });

  it('粉丝牌只带等级与牌名;不拿牌子里的档位冒充本房间的舰长', () => {
    const frame = giftFrameData((v2(PB_SMALL).data) as Record<string, unknown>);
    expect(frame.sender_uinfo).toMatchObject({ medal: { level: 30, name: '测试牌子' } });
    expect(frame.guard_level).toBeUndefined();
    expect(normalize(v2(PB_SMALL), OPTS)).toMatchObject({ meta: { guardLevel: 0 } });
  });

  it('Overlay 投影拿到名字、礼物与头像,不再是「某位观众 · 礼物 ×1」', () => {
    const raw = v2(PB_SMALL);
    expect(projectOverlayEvent(raw, normalize(raw, OPTS))).toMatchObject({
      eventKind: 'gift',
      username: '测试观众甲',
      body: '粉丝团灯牌 ×1',
      avatarUrl: 'https://i0.hdslb.com/bfs/face/0000000000000000000000000000000000000000.jpg',
      facts: { uid: '10001', medalLevel: 30, medalName: '测试牌子' },
    });
  });
});

describe('读不出来的帧', () => {
  it('pb 解不动:成事件 + 告警,绝不悄悄记成免费礼物', () => {
    const sink = warnSink();
    const got = normalize({ cmd: 'SEND_GIFT_V2', data: { pb: '这不是base64!!' } }, { ...OPTS, warn: sink.warn });
    expect(got).toMatchObject({
      kind: 'event',
      type: 'bilibili.gift',
      trigger: 'debounce',
      text: '[礼物|某位观众] 礼物×1',
      coalesce: { yuan: null },
    });
    expect((got as { meta?: Record<string, unknown> }).meta?.yuan).toBeUndefined();
    expect(sink.messages).toContain('礼物帧读不出金额,按未知金额成事件');
  });

  it('coin_type 读得出且不是 gold 时才算免费礼物', () => {
    expect(normalize({ cmd: 'SEND_GIFT', data: { giftName: '小心心', num: 3, coin_type: 'silver' } }, OPTS))
      .toEqual({ kind: 'count', field: 'freeGift', by: 3 });
  });

  it('V1 字段还在就原样走 V1,一个字节都不碰 pb', () => {
    const data = { uname: '阿明', giftName: '小花花', num: 2, coin_type: 'gold', total_coin: 2000, uid: 42, pb: '坏的' };
    expect(giftFrameData(data)).toBe(data);
    expect(normalize({ cmd: 'SEND_GIFT_V2', data }, OPTS)).toMatchObject({
      text: '[礼物 ¥2|阿明] 小花花×2',
      senderKey: '42',
    });
  });
});
