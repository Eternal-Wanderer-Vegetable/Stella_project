import type { ConfigGroup } from '../../core/types.ts';
import { cloneOverlayConfig } from './overlay/model.ts';

export const BILIBILI_DEFAULTS = {
  // enabled 由Persona的装配层显式开启。
  enabled: false,
  /** 直播间号;短号与真实房间号都行,World 自己换算 */
  roomId: 0,
  /** 登录 cookie 的 SESSDATA;空值使用匿名接入。 */
  sessdata: '',
  /** 礼物使用 flush 投递的金额门槛,单位元。 */
  giftFlushYuan: 1,
  /** 相同弹幕与常规礼物进入总线前的固定归并窗 */
  coalesceWindowMs: 300,
  /** 固定窗内累计到此数量时立即冲刷 */
  coalesceMaxItems: 64,
  /** 高能榜拥挤代理的开启/退出水位 */
  audienceOnlineRankOn: 200,
  audienceOnlineRankOff: 170,
  /** 人数持续不高于退出线达到此时长后解除拥挤态,单位秒。 */
  audienceReleaseHoldSec: 120,
  /** 人数信号新鲜度与已拥挤时的最长陈旧保持 */
  audienceSignalFreshSec: 90,
  audienceActiveStaleHoldSec: 300,
  audienceEventLineBudget: 114,
  audienceEventTokenBudget: 1061,
  /** 重要观众常规互动占总批预算的上限比例,同时受剩余额度限制。 */
  audienceImportantShare: 0.5,
  overlay: cloneOverlayConfig(),
};

export const BILIBILI_CONFIG_GROUP: ConfigGroup = {
  id: 'world:bilibili',
  owner: 'world:bilibili',
  schema: {
    type: 'object',
    title: 'B 站直播间 · 接入',
    description: '只读接入:弹幕、礼物、醒目留言、上舰、进场与人流读数。',
    properties: {
      'worlds.bilibili.roomId': {
        type: 'integer',
        title: '直播间号',
        minimum: 0,
        maximum: 4294967295,
        'x-hot': false,
        description: '短号或真实房间号皆可。改动需重启后生效。',
      },
      'worlds.bilibili.sessdata': {
        type: 'string',
        title: '登录凭证 SESSDATA',
        'x-hot': false,
        description:
          '浏览器登录 bilibili 后的 SESSDATA cookie。留空使用匿名接入,观众身份可能被脱敏。修改后需重启。',
      },
      'worlds.bilibili.giftFlushYuan': {
        type: 'number',
        title: '礼物即时投递门槛',
        minimum: 0,
        maximum: 1000,
        'x-suffix': '元',
        'x-hot': true,
        description: '达到此金额的礼物立即投递;其余礼物参与常规合批。',
      },
      'worlds.bilibili.coalesceWindowMs': {
        type: 'integer',
        title: '相同消息归并窗',
        minimum: 0,
        maximum: 2000,
        multipleOf: 50,
        'x-scale': 1000,
        'x-suffix': 's',
        'x-hot': true,
        description: '相同弹幕与常规礼物在进入事件总线前合并;0 关闭。窗口固定且不续期,flush 事件不等待。',
      },
      'worlds.bilibili.coalesceMaxItems': {
        type: 'integer',
        title: '归并池硬上限',
        minimum: 1,
        maximum: 1000,
        'x-suffix': '条',
        'x-hot': true,
        description: '固定窗内累计到此数量时立即输出归并结果,交给事件总线调度。',
      },
      'worlds.bilibili.audienceOnlineRankOn': {
        type: 'integer',
        title: '高能榜拥挤开启线',
        minimum: 1,
        maximum: 100000,
        'x-suffix': '人',
        'x-hot': true,
        description: '高能榜人数达到此值时进入拥挤态；只有同批上下文也超预算才会开始筛选。',
      },
      'worlds.bilibili.audienceOnlineRankOff': {
        type: 'integer',
        title: '高能榜拥挤退出线',
        minimum: 0,
        maximum: 100000,
        'x-suffix': '人',
        'x-hot': true,
        description: '人数持续不高于此值,达到退出等待时间后解除拥挤态。',
      },
      'worlds.bilibili.audienceReleaseHoldSec': {
        type: 'integer',
        title: '拥挤退出等待',
        minimum: 1,
        maximum: 1800,
        'x-suffix': 's',
        'x-hot': true,
        description: '高能榜人数需持续不高于退出线的时长。',
      },
      'worlds.bilibili.audienceSignalFreshSec': {
        type: 'integer',
        title: '高能榜新鲜时间',
        minimum: 1,
        maximum: 3600,
        'x-suffix': 's',
        'x-hot': true,
        description: '超过此时间未更新时标记为陈旧，但已拥挤状态可在最长保持期内继续生效。',
      },
      'worlds.bilibili.audienceActiveStaleHoldSec': {
        type: 'integer',
        title: '拥挤陈旧保持上限',
        minimum: 1,
        maximum: 3600,
        'x-suffix': 's',
        'x-hot': true,
        description: '最后一次高能榜读数过去这么久后，旧的拥挤判定不再启用限流。',
      },
      'worlds.bilibili.audienceEventLineBudget': {
        type: 'integer',
        title: '观众事件行预算',
        minimum: 1,
        maximum: 5000,
        'x-suffix': '行/批',
        'x-hot': true,
        description: '拥挤态下同批归并候选超过此行数才启用筛选。',
      },
      'worlds.bilibili.audienceEventTokenBudget': {
        type: 'integer',
        title: '观众事件 token 预算',
        minimum: 1,
        maximum: 100000,
        'x-suffix': 'token/批',
        'x-hot': true,
        description: '拥挤态下同批归并候选超过此估算量才启用筛选。',
      },
      'worlds.bilibili.audienceImportantShare': {
        type: 'number',
        title: '重要观众常规互动预算比例',
        minimum: 0.01,
        maximum: 1,
        'x-scale': 100,
        'x-suffix': '%',
        'x-hot': true,
        description: '重要观众常规互动占总批预算的上限比例,同时受批次剩余额度限制。',
      },
      'worlds.bilibili.overlay.enabled': {
        type: 'boolean',
        title: '启用 Overlay',
        'x-hot': false,
        description: '在本机启动透明 Overlay 页面。改动需重启后生效。',
      },
      'worlds.bilibili.overlay.port': {
        type: 'integer',
        title: 'Overlay 端口',
        minimum: 0,
        maximum: 65535,
        'x-hot': false,
        description: '默认 7795；被占用时会自动顺延。0 表示随机空闲端口。',
      },
      'worlds.bilibili.overlay.agentNoticeMaxChars': {
        type: 'integer',
        title: 'Agent 公告字数上限',
        minimum: 1,
        maximum: 5000,
        'x-suffix': '字',
        'x-hot': true,
        description: 'Agent 公告工具写入纯文本时的 Unicode 字符上限。',
      },
    },
  },
};

/** config.json 的 `worlds.bilibili` 节。 */
export type BilibiliConfigSection = typeof BILIBILI_DEFAULTS;
