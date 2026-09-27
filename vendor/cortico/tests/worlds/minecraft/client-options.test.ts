/** 启动前的两份配置合并:改该改的那一项,别动别的。 */
import { describe, expect, it } from 'vitest';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { nullLogger } from '../../../src/core/util.ts';
import {
  applyChatVisible,
  mergeOptions,
  mergeSpectatorPlusConfig,
} from '../../../src/worlds/minecraft/client-options.ts';

describe('mergeOptions', () => {
  it('替换已有键,保留其余行与行序', () => {
    const prev = 'version:3465\nfullscreen:false\npauseOnLostFocus:true\nfov:0.5\n';
    const out = mergeOptions(prev, { pauseOnLostFocus: 'false' });
    expect(out).toBe('version:3465\nfullscreen:false\npauseOnLostFocus:false\nfov:0.5\n');
  });

  it('缺的键补在末尾', () => {
    const out = mergeOptions('fov:0.5\n', { pauseOnLostFocus: 'false' });
    expect(out).toBe('fov:0.5\npauseOnLostFocus:false\n');
  });

  it('值里带冒号的行(按键绑定)不被切坏', () => {
    const prev = 'key_key.fullscreen:key.keyboard.f11\npauseOnLostFocus:true\n';
    const out = mergeOptions(prev, { pauseOnLostFocus: 'false' });
    expect(out).toContain('key_key.fullscreen:key.keyboard.f11');
    expect(out).toContain('pauseOnLostFocus:false');
  });

  it('空文件也能写出一份只有这一行的 options', () => {
    const out = mergeOptions('', { pauseOnLostFocus: 'false' });
    expect(out).toBe('pauseOnLostFocus:false\n');
  });

  it('被静音的主音量被拉回来', () => {
    const out = mergeOptions('soundCategory_master:0.0\nsoundCategory_music:1.0\n', {
      soundCategory_master: '1.0',
    });
    expect(out).toBe('soundCategory_master:1.0\nsoundCategory_music:1.0\n');
  });
});

describe('mergeSpectatorPlusConfig', () => {
  it('关掉同步屏幕,别的键原样留着', () => {
    const prev = JSON.stringify({ renderHotbar: true, openScreens: true, renderArms: true });
    const out = JSON.parse(mergeSpectatorPlusConfig(prev, { openScreens: false })) as Record<string, unknown>;
    expect(out.openScreens).toBe(false);
    expect(out.renderHotbar).toBe(true);
    expect(out.renderArms).toBe(true);
  });

  it('文件不存在时只写这一个键,其余交给 World 补默认值', () => {
    expect(JSON.parse(mergeSpectatorPlusConfig('', { openScreens: false }))).toEqual({ openScreens: false });
  });
});

describe('applyChatVisible', () => {
  const withGameDir = (prev: string | null, run: (dir: string) => void): void => {
    const dir = mkdtempSync(join(tmpdir(), 'mc-options-'));
    try {
      if (prev !== null) writeFileSync(join(dir, 'options.txt'), prev, 'utf8');
      run(dir);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  };

  it('摄像机留下的 HIDDEN 掰回 FULL,其余设置一个字不动', () => {
    withGameDir('fov:0.5\nchatVisibility:2\nkey_key.chat:key.keyboard.t\n', (dir) => {
      applyChatVisible(dir, nullLogger());
      expect(readFileSync(join(dir, 'options.txt'), 'utf8'))
        .toBe('fov:0.5\nchatVisibility:0\nkey_key.chat:key.keyboard.t\n');
    });
  });

  it('全新游戏目录只写这一行,其余交给游戏补默认值', () => {
    withGameDir(null, (dir) => {
      applyChatVisible(dir, nullLogger());
      expect(readFileSync(join(dir, 'options.txt'), 'utf8')).toBe('chatVisibility:0\n');
    });
  });
});
