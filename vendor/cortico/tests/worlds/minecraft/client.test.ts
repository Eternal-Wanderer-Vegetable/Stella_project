import { afterEach, describe, expect, it } from 'vitest';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  GameClient, clientWindowTitle, explainExit, scanWindowReady, type GameClientOptions,
} from '../../../src/worlds/minecraft/client.ts';
import { nullLogger } from '../../../src/core/util.ts';

describe('scanWindowReady', () => {
  const LINE = '[10:10:12] [Render thread/INFO]: Backend library: LWJGL version 3.3.3-snapshot\n';

  it('一片里出现锚点就算看见', () => {
    expect(scanWindowReady('', LINE).seen).toBe(true);
  });

  it('锚点被切成两片送来也认得出:接缝由上一片的尾巴接住', () => {
    const cut = LINE.indexOf('LWJGL') - 3;
    const first = scanWindowReady('', LINE.slice(0, cut));
    expect(first.seen).toBe(false);
    expect(scanWindowReady(first.carry, LINE.slice(cut)).seen).toBe(true);
  });

  it('接缝有界:刷屏的启动日志不会把它撑大', () => {
    let carry = '';
    for (let i = 0; i < 50; i++) {
      carry = scanWindowReady(carry, `[10:10:1${i % 10}] [Render thread/INFO]: Transformed something\n`).carry;
    }
    expect(carry.length).toBeLessThanOrEqual(64);
    // 撑不大也不能因此漏判:下一片带着锚点照样认
    expect(scanWindowReady(carry, LINE).seen).toBe(true);
  });

  it('启动早期那些行不算数:Setting user 在窗口之前', () => {
    expect(scanWindowReady('', '[10:10:12] [Render thread/INFO]: Setting user: CortiCam\n').seen).toBe(false);
  });
});

describe('explainExit', () => {
  it('真崩与 Ctrl+C 关窗不是一回事:十进制长得像,措辞必须分得开', () => {
    expect(explainExit(0xc0000005)).toContain('0xC0000005');
    expect(explainExit(0xc000013a)).toContain('Ctrl+C');
    expect(explainExit(0xc0000005)).not.toContain('Ctrl+C');
  });


  it('0xC0000005 报告原生访问违例，不推断具体原因', () => {
    const text = explainExit(0xc0000005);
    expect(text).toContain('原生访问违例');
    expect(text).not.toMatch(/显卡|Java|LWJGL/i);
  });
  it('普通退出码原样报,不硬套原生崩溃表', () => {
    expect(explainExit(1)).toBe('code=1');
    expect(explainExit(null)).toContain('没有退出码');
  });
});

describe('clientWindowTitle', () => {
  it('账号名去空白就是标题;空名字不改', () => {
    expect(clientWindowTitle('CortiCam')).toBe('CortiCam');
    expect(clientWindowTitle(' Phant ')).toBe('Phant');
    expect(clientWindowTitle('')).toBeNull();
    expect(clientWindowTitle('   ')).toBeNull();
  });
});

describe('GameClient 窗口标题', () => {
  const clients: GameClient[] = [];

  afterEach(async () => {
    await Promise.all(clients.splice(0).map((c) => c.stop()));
  });

  function wait(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function rig(over: {
    username?: string;
    autoJoin?: boolean;
    titleSettleMs?: number;
    titles?: Array<{ pid: number; title: string }>;
    gameDir?: () => string;
    windowTimeoutMs?: number;
    findWindow?: GameClientOptions['findWindow'];
    /** 不注入 findWindow,让就绪判定走本平台真实那条路 */
    realWindowProbe?: boolean;
    /** 假进程起来先打这一行再挂住,用来喂日志锚点 */
    announce?: string;
    /** 给了就换成"起来立刻退出"的假进程,用来打崩溃那条路 */
    exitCode?: number;
    restartMax?: number;
    restartBackoffMs?: number;
    restartWindowMs?: number;
    onCrash?: GameClientOptions['onCrash'];
  }): GameClient {
    const titles = over.titles ?? [];
    const opts: GameClientOptions = {
      label: '测试客户端',
      enabled: () => true,
      gameDir: over.gameDir ?? (() => ''),
      versionId: () => '',
      javaPath: () => '',
      jvmArgs: () => '',
      username: () => over.username ?? 'CortiCam',
      width: () => 1280,
      height: () => 720,
      autoJoin: () => over.autoJoin ?? false,
      server: () => ({ host: '127.0.0.1', port: 25565 }),
      noPauseOnLostFocus: () => false,
      chatUsable: () => false,
      log: nullLogger(),
      commandOverride: {
        command: process.execPath,
        args: ['-e', over.exitCode === undefined
          ? `${over.announce ? `console.log(${JSON.stringify(over.announce)});` : ''}setInterval(() => {}, 60000)`
          : `process.exit(${over.exitCode})`],
      },
      restartMax: over.restartMax === undefined ? undefined : () => over.restartMax as number,
      restartBackoffMs: over.restartBackoffMs,
      restartWindowMs: over.restartWindowMs,
      onCrash: over.onCrash,
      windowPollMs: 20,
      windowTimeoutMs: over.windowTimeoutMs ?? 2_000,
      titleSettleMs: over.titleSettleMs ?? 40,
      ...(over.realWindowProbe ? {} : { findWindow: over.findWindow ?? (async () => true) }),
      setWindowTitle: async ({ ownerPid, title }) => {
        titles.push({ pid: ownerPid, title });
        return true;
      },
    };
    const client = new GameClient(opts);
    clients.push(client);
    return client;
  }

  it('窗口就绪后立刻把标题写成账号名', async () => {
    const titles: Array<{ pid: number; title: string }> = [];
    const client = rig({ username: 'CortiCam', autoJoin: false, titles });
    await client.start();
    for (let i = 0; i < 20 && titles.length === 0; i++) await wait(20);
    expect(titles.map((t) => t.title)).toEqual(['CortiCam']);
    const st = await client.state();
    expect(st.phase).toBe('running');
    expect(titles[0]?.pid).toBe(st.pid);
  });

  it('直连进服会再写一次:挡住游戏自己的那次 updateTitle', async () => {
    const titles: Array<{ pid: number; title: string }> = [];
    const client = rig({ username: 'Phant', autoJoin: true, titleSettleMs: 50, titles });
    await client.start();
    for (let i = 0; i < 20 && titles.length === 0; i++) await wait(20);
    expect(titles.map((t) => t.title)).toEqual(['Phant']);
    await wait(80);
    expect(titles.map((t) => t.title)).toEqual(['Phant', 'Phant']);
  });

  it('空账号名不改标题', async () => {
    const titles: Array<{ pid: number; title: string }> = [];
    const client = rig({ username: '  ', autoJoin: true, titles });
    await client.start();
    await wait(80);
    expect(titles).toEqual([]);
  });

  // 这一对只在非 Windows 上跑:Windows 那条路问 user32 要 ownerPid 名下的窗口,
  // 根本不看日志。见 client.ts 的 windowSeen。
  it.skipIf(process.platform === 'win32')('没有 user32 的平台:stdout 打出建窗那行才算就绪', async () => {
    const client = rig({
      realWindowProbe: true,
      announce: '[10:10:12] [Render thread/INFO]: Backend library: LWJGL version 3.3.3-snapshot',
    });
    await client.start();
    for (let i = 0; i < 40 && (await client.state()).phase !== 'running'; i++) await wait(20);
    expect((await client.state()).phase).toBe('running');
  });

  it.skipIf(process.platform === 'win32')('没有 user32 的平台:进程活着但没打那行,等到超时报失败', async () => {
    const client = rig({ realWindowProbe: true, windowTimeoutMs: 60 });
    await client.start();
    for (let i = 0; i < 40 && (await client.state()).phase !== 'error'; i++) await wait(20);
    const st = await client.state();
    expect(st.phase).toBe('error');
    expect(st.detail).toContain('Backend library');
  });

  it('运行态锁存启动目录,停止后才采用新配置目录', async () => {
    const launchDir = mkdtempSync(join(tmpdir(), 'mc-client-launch-'));
    const nextDir = mkdtempSync(join(tmpdir(), 'mc-client-next-'));
    let configuredDir = launchDir;
    const client = rig({ gameDir: () => configuredDir });

    try {
      await client.start();
      for (let i = 0; i < 50 && (await client.state()).phase !== 'running'; i += 1) await wait(10);
      expect((await client.state()).phase).toBe('running');
      configuredDir = nextDir;

      const running = await client.state();
      expect(running.gameDir).toBe(launchDir);

      const stopped = await client.stop();
      expect(stopped.gameDir).toBe(nextDir);
    } finally {
      await client.stop();
      rmSync(launchDir, { recursive: true, force: true });
      rmSync(nextDir, { recursive: true, force: true });
    }
  });

  it('人为 stop() 不触发自动重启:那不是崩溃', async () => {
    const crashes: number[] = [];
    const client = rig({ restartMax: 3, onCrash: (i) => crashes.push(i.attempt) });
    await client.start();
    await client.stop();
    await wait(80);
    expect(crashes).toEqual([]);
  });

  it('运行进程的失败日志仍指向该次启动目录', async () => {
    const launchDir = mkdtempSync(join(tmpdir(), 'mc-client-log-launch-'));
    const nextDir = mkdtempSync(join(tmpdir(), 'mc-client-log-next-'));
    let configuredDir = launchDir;
    const client = rig({
      gameDir: () => configuredDir,
      windowTimeoutMs: 40,
      findWindow: async () => false,
    });

    try {
      await client.start();
      configuredDir = nextDir;

      for (let i = 0; i < 50 && (await client.state()).phase !== 'error'; i += 1) await wait(10);
      const failed = await client.state();
      expect(failed.phase).toBe('error');
      expect(failed.gameDir).toBe(launchDir);
      expect(failed.detail).toContain(join(launchDir, 'logs', 'latest.log'));
      expect(failed.detail).not.toContain(join(nextDir, 'logs', 'latest.log'));

      const stopped = await client.stop();
      expect(stopped.gameDir).toBe(nextDir);
    } finally {
      await client.stop();
      rmSync(launchDir, { recursive: true, force: true });
      rmSync(nextDir, { recursive: true, force: true });
    }
  });


  describe('崩溃自动重启', () => {
    async function crashUntil(over: { max: number; count: number }) {
      const crashes: Array<{ attempt: number; max: number; delayMs: number }> = [];
      let client: GameClient | null = null;
      client = rig({
        exitCode: 3,
        restartMax: over.max,
        restartBackoffMs: 10,
        restartWindowMs: 60_000,
        onCrash: (i) => {
          crashes.push({ attempt: i.attempt, max: i.max, delayMs: i.delayMs });
          if (crashes.length >= over.count) void client?.stop();
        },
      });
      await client.start();
      for (let i = 0; i < 200 && crashes.length < over.count; i += 1) await wait(20);
      return crashes;
    }

    it('非人为退出就退避重启,退避逐次加倍', async () => {
      const crashes = await crashUntil({ max: 3, count: 3 });
      expect(crashes.map((c) => c.attempt)).toEqual([1, 2, 3]);
      expect(crashes.map((c) => c.delayMs)).toEqual([10, 20, 40]);
    });

    it('窗口内超上限就停手并报出来,不闷着重启到天荒地老', async () => {
      const crashes = await crashUntil({ max: 2, count: 3 });
      expect(crashes.map((c) => c.attempt)).toEqual([1, 2, 0]);
      expect(crashes[2]).toMatchObject({ max: 2, delayMs: 0 });
    });

    it('不给上限就退回老行为:只报一次,不重启', async () => {
      const crashes = await crashUntil({ max: 0, count: 1 });
      expect(crashes).toEqual([{ attempt: 0, max: 0, delayMs: 0 }]);
    });

    /**
     * 正常退出按退出码识别，不报告崩溃或安排自动重启。
     */
    it('code=0 是正常退出:不报崩、不排重启、相位归 stopped', async () => {
      const crashes: unknown[] = [];
      const client = rig({
        exitCode: 0, restartMax: 3, restartBackoffMs: 10, restartWindowMs: 60_000,
        onCrash: (i) => crashes.push(i),
      });
      await client.start();
      for (let i = 0; i < 40 && (await client.state()).phase !== 'stopped'; i += 1) await wait(20);
      expect(crashes).toEqual([]);
      expect((await client.state()).phase).toBe('stopped');
      expect((await client.state()).detail).toBeNull();
      // 再等一整个退避:真排了定时器的话这里会重新起进程
      await wait(60);
      expect(crashes).toEqual([]);
      expect((await client.state()).phase).toBe('stopped');
    });

    it('非零退出码照旧当崩:分诊只放行正常退出那一条', async () => {
      const crashes = await crashUntil({ max: 1, count: 1 });
      expect(crashes.map((c) => c.attempt)).toEqual([1]);
    });

    it('两次崩溃隔得比窗口还远就从头计数:活过一整个窗口才算真活过来', async () => {
      const crashes: Array<{ attempt: number }> = [];
      let client: GameClient | null = null;
      client = rig({
        exitCode: 3,
        restartMax: 1,
        restartBackoffMs: 10,
        restartWindowMs: 1, // 窗口 1ms:每一次崩溃都落在上一次的窗口之外
        onCrash: (i) => {
          crashes.push({ attempt: i.attempt });
          if (crashes.length >= 3) void client?.stop();
        },
      });
      await client.start();
      for (let i = 0; i < 200 && crashes.length < 3; i += 1) await wait(20);
      expect(crashes.map((c) => c.attempt)).toEqual([1, 1, 1]);
    });
  });
});
