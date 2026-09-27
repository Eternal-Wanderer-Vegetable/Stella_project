import { describe, expect, it } from 'vitest';
import { normalize } from '../../../src/worlds/bilibili/normalize.ts';
import { projectOverlayEvent } from '../../../src/worlds/bilibili/overlay/project.ts';

describe('Bilibili Overlay 事件投影', () => {
  it('弹幕投影头像与可用于用户组的实测字段', () => {
    const info: unknown[] = [];
    info[0] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, { user: { base: { face: '//i.example/avatar.png' } } }];
    info[1] = '晚上好';
    info[2] = [42, '阿明', 1, 0, 1, 8, 1, '#66ccff'];
    info[3] = [21, '蓝天', '主播', 7734200, 16744576];
    info[4] = [35];
    info[7] = 2;
    const raw = { cmd: 'DANMU_MSG', info };
    const event = projectOverlayEvent(raw, normalize(raw, { giftFlushYuan: 1 }));
    expect(event).toMatchObject({
      eventKind: 'danmaku',
      username: '阿明',
      body: '晚上好',
      avatarUrl: 'https://i.example/avatar.png',
      facts: {
        uid: '42',
        guardLevel: 2,
        medalLevel: 21,
        medalName: '蓝天',
        medalAnchorName: '主播',
        medalRoomId: 7734200,
        medalColor: 16744576,
        isAdmin: true,
        vip: false,
        svip: true,
        rank: 8,
        nameColor: '#66ccff',
        userLevel: 35,
      },
    });
  });

  it('礼物缺失的身份字段保持缺失，exists 规则不会误判', () => {
    const raw = { cmd: 'SEND_GIFT', data: { uid: 7, uname: '小七', giftName: '花', num: 2, coin_type: 'gold', total_coin: 100 } };
    const event = projectOverlayEvent(raw, normalize(raw, { giftFlushYuan: 1 }));
    expect(event?.facts).toEqual({ uid: '7', eventKind: 'gift' });
    expect(event?.body).toBe('花 ×2');
  });

  it('醒目留言的 user_info.user_level 是数字，直接进 facts.userLevel', () => {
    const raw = { cmd: 'SUPER_CHAT_MESSAGE', data: { uid: 9, price: 30, message: '点首歌', user_info: { uname: '阿明', user_level: 14 } } };
    const event = projectOverlayEvent(raw, normalize(raw, { giftFlushYuan: 1 }));
    expect(event?.facts).toMatchObject({ uid: '9', userLevel: 14 });
  });

  it('免费礼物虽不唤醒 Agent，仍可进入准入为礼物的 Overlay 弹幕机', () => {
    const raw = { cmd: 'SEND_GIFT', data: { uname: '小七', giftName: '免费心心', num: 3, coin_type: 'silver' } };
    const normalized = normalize(raw, { giftFlushYuan: 1 });
    expect(normalized?.kind).toBe('count');
    expect(projectOverlayEvent(raw, normalized)).toMatchObject({ eventKind: 'gift', body: '免费心心 ×3' });
  });
});
