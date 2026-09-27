/**
 * `SEND_GIFT_V2` 的 protobuf 帧 → V1 的 JSON 字段形状。
 *
 * 此层将 protobuf 字段映射到 V1 的 JSON 名称，使 normalize、overlay/project 共用处理路径，并支持 V1/V2 共存及帧回放。
 *
 * 字段号依据实采帧推断，未有官方 schema；映射如下：
 *
 * ```
 * 顶层
 *    1  uid          送礼人
 *    2  uname
 *    3  face         头像 URL
 *    8  medal        粉丝牌:5=等级 6=牌名。**可能是别的房间的牌子**
 *   10  gift         礼物体,见下
 *   15  sender       送礼人完整档案(1=uid,2={1=名字,2=头像})
 * 礼物体(顶层 10)
 *    1  giftId    2 giftName   3 num   4 giftType(动画礼物=2)
 *  5/6/7 金瓜子三槽,见 coinTotal
 *    8  coin_type("gold"=付费,"silver"=免费)
 *    9  tid(这一笔的交易号,V1 同名字段同形)
 *   12  combo_id  14 连击累计金瓜子(100/200/400/600 这样递增,**不是单笔**)
 *   18  动作词("投喂")
 * ```
 *
 * 以下字段不填：
 *
 * - `guard_level`:粉丝牌里那个档位(medal.12)是**牌子所属房间**的舰长等级,
 *   不能作为本房间的舰长等级。
 * - `is_admin`:尚未确认对应的 protobuf 字段。
 */
import { pbFromBase64, pbInt, pbSub, pbText, type PbField } from './protobuf.ts';

/** 由调用方记录解析告警。 */
type GiftFrameWarn = (message: string, data?: Record<string, unknown>) => void;

/**
 * V1 data 原样返回;V2 返回补齐 V1 字段名的副本。V2 缺少礼物体或名称时返回原 data。
 */
export function giftFrameData(
  data: Record<string, unknown>,
  warn?: GiftFrameWarn,
): Record<string, unknown> {
  if (text(data.giftName) || text(data.gift_name)) return data;
  const top = pbFromBase64(data.pb);
  const gift = pbSub(top, 10);
  const giftName = pbText(gift, 2);
  if (!gift || !giftName) {
    if (data.pb !== undefined) {
      warn?.('SEND_GIFT_V2 缺少有效礼物体或礼物名', {
        decoded: top !== null,
        giftBody: gift !== null,
      });
    }
    return data;
  }
  const sender = pbSub(top, 15);
  const senderBase = pbSub(sender, 2);
  const uid = pbInt(top, 1) ?? pbInt(sender, 1);
  const uname = pbText(top, 2) || pbText(senderBase, 1);
  const face = pbText(top, 3) || pbText(senderBase, 2);
  const num = pbInt(gift, 3);
  const coinType = pbText(gift, 8);
  const totalCoin = coinTotal(gift, num, giftName, warn);
  const giftId = pbInt(gift, 1);
  const tid = pbText(gift, 9);
  return {
    ...data,
    ...(uid !== undefined ? { uid } : {}),
    ...(uname ? { uname } : {}),
    giftName,
    ...(giftId !== undefined ? { giftId } : {}),
    ...(num !== undefined ? { num } : {}),
    ...(coinType ? { coin_type: coinType } : {}),
    ...(totalCoin !== undefined ? { total_coin: totalCoin } : {}),
    ...(tid ? { tid } : {}),
    sender_uinfo: senderUinfo(top, uid, uname, face),
  };
}

function senderUinfo(
  top: readonly PbField[] | null,
  uid: number | undefined,
  uname: string,
  face: string,
): Record<string, unknown> {
  const medal = pbSub(top, 8);
  const medalLevel = pbInt(medal, 5);
  const medalName = pbText(medal, 6);
  const hasMedal = medalLevel !== undefined || medalName !== '';
  return {
    ...(uid !== undefined ? { uid } : {}),
    base: {
      ...(uname ? { name: uname } : {}),
      ...(face ? { face } : {}),
    },
    ...(hasMedal
      ? {
          medal: {
            ...(medalLevel !== undefined ? { level: medalLevel } : {}),
            ...(medalName ? { name: medalName } : {}),
          },
        }
      : {}),
  };
}

/**
 * 金瓜子字段映射尚未确认,暂取字段 5/6/7 中正数的最大值作为 fallback。
 * 有效值不相等或已知 num 不为 1 时告警。
 */
function coinTotal(
  gift: readonly PbField[],
  num: number | undefined,
  giftName: string,
  warn?: GiftFrameWarn,
): number | undefined {
  const slots = [5, 6, 7]
    .map((field) => pbInt(gift, field))
    .filter((value): value is number => value !== undefined && value > 0);
  if (slots.length === 0) return undefined;
  const total = Math.max(...slots);
  const settled = slots.every((value) => value === total) && (num ?? 1) === 1;
  if (!settled) {
    warn?.('SEND_GIFT_V2 金瓜子字段映射未确认,暂取最大值', { gift: giftName, slots, num });
  }
  return total;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
