import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { BilibiliWorld } from '../../../src/worlds/bilibili/world.ts';
import { AgentAnnouncementStore } from '../../../src/worlds/bilibili/overlay/announcement.ts';

const roots: string[] = [];

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe('Agent 公告持久化', () => {
  it('字数按 Unicode code point 计算，emoji 与前端口径一致', () => {
    const file = tempFile();
    const store = new AgentAnnouncementStore(file);
    expect(store.set('A😀B', 3).text).toBe('A😀B');
    expect(() => store.set('A😀BC', 3)).toThrow('当前 4 字');
    expect(JSON.parse(readFileSync(file, 'utf8')).text).toBe('A😀B');
  });

  it('写入后可跨实例恢复，失败的超长写入不覆盖旧公告', () => {
    const file = tempFile();
    const first = new AgentAnnouncementStore(file);
    first.set('今晚十点开播', 20);
    expect(() => first.set('这条公告太长', 3)).toThrow();
    const second = new AgentAnnouncementStore(file);
    expect(second.current.text).toBe('今晚十点开播');
    expect(second.current.revision).toBe(1);
  });

  it('工具 schema 暴露动态 maxLength，写入值由 ENV_PROMPT 占位符读取', async () => {
    const file = tempFile();
    const module = new BilibiliWorld({
      roomId: 0,
      agentNoticeFile: file,
      agentNoticeMaxChars: () => 4,
    });
    const tool = module.tools()[0];
    expect((tool.parameters.properties as Record<string, { maxLength: number }>).text.maxLength).toBe(4);
    expect(await tool.handler({ text: 'A😀BC' }, { role: 'main', log: null as never })).toContain('4/4');
    expect(module.envPromptVars()).toMatchObject({
      'bilibili.agentAnnouncement': 'A😀BC',
      'bilibili.agentAnnouncementLimit': '4',
    });
    expect(await tool.handler({ text: 'A😀BCD' }, { role: 'main', log: null as never })).toContain('[bad input]');
  });

  /*
   * 空串拒绝执行并保留公告板内容；回执使用否定形并点名入参。
   */
  it('空串被拒绝执行:公告板不动,回执是否定形并点名入参', async () => {
    const file = tempFile();
    const module = new BilibiliWorld({
      roomId: 0,
      agentNoticeFile: file,
      agentNoticeMaxChars: () => 15,
    });
    const tool = module.tools()[0];
    await tool.handler({ text: '今晚十点开播' }, { role: 'main', log: null as never });
    const reply = await tool.handler({ text: '' }, { role: 'main', log: null as never });
    expect(reply).toContain('text 是空串');
    expect(reply).toContain('[not executed]');
    // 旧的成功形字数口径不该再出现(它正是「空参数=成功」的示范样本)
    expect(reply).not.toContain('0/15 chars');
    // 公告板保持原样,没有被抹掉
    expect(module.envPromptVars()['bilibili.agentAnnouncement']).toBe('今晚十点开播');
  });
});

function tempFile(): string {
  const root = mkdtempSync(join(tmpdir(), 'bilibili-announcement-'));
  roots.push(root);
  return join(root, 'state', 'agent-notice.json');
}
