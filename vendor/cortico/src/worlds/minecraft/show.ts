/**
 * 容器操作的演出节拍(GUI 同步给观众看时,把 ms 级的协议操作放慢到人手速度)。
 *
 * 节拍只在「摄像机客户端开着 + GUI 同步开着」时非 null;关着时所有 beat 都是
 * 零等待,协议层照旧瞬时。预算封顶:单次操作(一单 stow/take/craft/装炉)加起来
 * 最多多花 budgetMs,超了剩余步骤恢复瞬时——整箱掏空不会变成慢动作长镜头。
 *
 * 两次开窗之间还有一道 `openGap`:关窗到下一次开窗至少空 reopenGapMs。协议层里
 * 这个间隔是几十到几百毫秒,同步到摄像机画面上就是一次快速闪屏;而同 tick 的
 * 开关窗正是历史上「同步屏关不掉」那个竞态的源头。
 * 所以这道间隔既是观感也是防竞态,不受 budgetMs 约束。
 */

export interface ShowTempo {
  /** 逐格摆放/逐栈存取的间隔 */
  clickMs: number;
  /** 开窗后停一拍再动手 */
  dwellOpenMs: number;
  /** 材料摆齐后停一拍,让产出槽亮相 */
  dwellResultMs: number;
  /** 收完手停一拍再关窗 */
  dwellCloseMs: number;
  /** 单次操作的节拍总预算 */
  budgetMs: number;
  /** 上一次关窗到这一次开窗之间至少空多久(不吃 budgetMs) */
  reopenGapMs: number;
}

type ShowBeat = 'open' | 'click' | 'result' | 'close';

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/**
 * 关窗时刻是跨技能的:stow 关的窗,下一步 craft 开窗时要知道它多久之前关的。
 * 引擎子进程里只有一个 bot,所以这里是模块级的一份;由 world.ts 的 `windowClose`
 * 监听统一打点,覆盖所有关窗路径(技能收尾、合成前清遗留窗、队列空了的窗口卫生)。
 */
let lastWindowCloseAt = 0;

/** 关窗打点。任何路径关掉的容器窗口都算数,所以挂在 bot 的 windowClose 事件上。 */
export function markShowWindowClosed(now = Date.now()): void {
  lastWindowCloseAt = now;
}

/** 测试用:清掉模块级的关窗时刻 */
export function resetShowScene(): void {
  lastWindowCloseAt = 0;
}

/**
 * 一次容器操作一个 pacer:构造时把节拍快照下来(操作中途热改配置不半途变速),
 * tempo 为 null 时整个对象是无操作的。
 */
export class ShowPacer {
  private spent = 0;

  constructor(private readonly tempo: ShowTempo | null) {}

  /**
   * 开窗之前调:上一次关窗离现在不够 reopenGapMs 就把差额等掉。
   * 不吃预算——预算封顶是为了「别演成慢动作」,而这道间隔是为了「别闪屏」,
   * 预算耗尽恰恰是连着做了很多下的时候,正是最需要它的时候。
   */
  async openGap(now = Date.now()): Promise<void> {
    const t = this.tempo;
    if (!t || t.reopenGapMs <= 0) return;
    const wait = t.reopenGapMs - (now - lastWindowCloseAt);
    if (wait > 0) await sleep(Math.min(wait, t.reopenGapMs));
  }

  async beat(kind: ShowBeat): Promise<void> {
    const t = this.tempo;
    if (!t) return;
    const ms =
      kind === 'open' ? t.dwellOpenMs :
      kind === 'click' ? t.clickMs :
      kind === 'result' ? t.dwellResultMs : t.dwellCloseMs;
    const left = t.budgetMs - this.spent;
    if (ms <= 0 || left <= 0) return;
    const wait = Math.min(ms, left);
    this.spent += wait;
    await sleep(wait);
  }
}
