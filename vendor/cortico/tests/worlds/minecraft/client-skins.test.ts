/** 皮肤:库的收发、loader 配置合并、按账号名铺进游戏目录。 */
import { afterEach, describe, expect, it } from 'vitest';
import { deflateSync } from 'node:zlib';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { nullLogger } from '../../../src/core/util.ts';
import {
  applySkins,
  checkSkinBytes,
  clearStoredSkin,
  hasSkinMod,
  installedMatches,
  installedSkinPath,
  mergeSkinLoaderConfig,
  pngSize,
  readStoredSkin,
  removeInstalledSkin,
  setStoredSkin,
  storedSkinInfo,
} from '../../../src/worlds/minecraft/client-skins.ts';

const dirs: string[] = [];

function tmp(): string {
  const dir = mkdtempSync(join(tmpdir(), 'mc-skins-'));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  while (dirs.length > 0) rmSync(dirs.pop()!, { recursive: true, force: true });
});

/** 真 PNG(单色填充),尺寸可指定:解析器与"是不是图片"的判据都吃真字节 */
function png(width: number, height: number, fill = 0x55): Buffer {
  const raw = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y++) {
    const row = y * (1 + width * 4);
    raw[row] = 0; // filter: none
    for (let x = 0; x < width; x++) {
      raw.writeUInt32BE(((fill + x + y) % 256) * 0x01010100 + 0xff, row + 1 + x * 4);
    }
  }
  const chunk = (type: string, body: Buffer): Buffer => {
    const head = Buffer.alloc(8);
    head.writeUInt32BE(body.length, 0);
    head.write(type, 4, 'ascii');
    const crcTable: number[] = [];
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
    let crc = 0xffffffff;
    for (const byte of Buffer.concat([Buffer.from(type, 'ascii'), body])) {
      crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    }
    const tail = Buffer.alloc(4);
    tail.writeUInt32BE((crc ^ 0xffffffff) >>> 0, 0);
    return Buffer.concat([head, body, tail]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

describe('皮肤文件的判据', () => {
  it('PNG 头里读得出宽高', () => {
    expect(pngSize(png(64, 32))).toEqual({ width: 64, height: 32 });
  });

  it('不是 PNG 的字节给 null', () => {
    expect(pngSize(Buffer.from('这是一段文本,不是图片'))).toBeNull();
  });

  it('64x64 与老格式 64x32 都收', () => {
    expect(checkSkinBytes(png(64, 64))).toEqual({ width: 64, height: 64 });
    expect(checkSkinBytes(png(64, 32))).toEqual({ width: 64, height: 32 });
  });

  it('尺寸不对的图连同它的尺寸一起被驳回', () => {
    const out = checkSkinBytes(png(128, 128));
    expect(out).toHaveProperty('error');
    expect((out as { error: string }).error).toContain('128x128');
  });
});

describe('选中的那张留底', () => {
  it('收下之后读得回来,带尺寸与字节数', () => {
    const store = tmp();
    const bytes = png(64, 64);
    const info = setStoredSkin(store, 'bot', bytes);
    expect(info).toMatchObject({ width: 64, height: 64, bytes: bytes.length });
    expect(readStoredSkin(store, 'bot')!.equals(bytes)).toBe(true);
    expect(storedSkinInfo(store, 'bot')).toMatchObject({ width: 64, height: 64 });
  });

  it('两个角色各留各的', () => {
    const store = tmp();
    setStoredSkin(store, 'bot', png(64, 64, 0x10));
    setStoredSkin(store, 'player', png(64, 64, 0x90));
    expect(readStoredSkin(store, 'bot')!.equals(readStoredSkin(store, 'player')!)).toBe(false);
  });

  it('换一张就是覆盖,不留旧的', () => {
    const store = tmp();
    setStoredSkin(store, 'bot', png(64, 64, 0x10));
    const next = png(64, 64, 0x90);
    setStoredSkin(store, 'bot', next);
    expect(readStoredSkin(store, 'bot')!.equals(next)).toBe(true);
  });

  it('尺寸不合格的图不落盘', () => {
    const store = tmp();
    expect(setStoredSkin(store, 'bot', png(128, 128))).toHaveProperty('error');
    expect(readStoredSkin(store, 'bot')).toBeNull();
  });

  it('不是图片的字节连同原因一起被驳回', () => {
    const store = tmp();
    const out = setStoredSkin(store, 'bot', Buffer.from('这是一段文本'));
    expect((out as { error: string }).error).toContain('不是 PNG');
  });

  it('撤下时把刚撤的字节交回去(调用方拿它认已铺的那份)', () => {
    const store = tmp();
    const bytes = png(64, 64);
    setStoredSkin(store, 'bot', bytes);
    expect(clearStoredSkin(store, 'bot')!.equals(bytes)).toBe(true);
    expect(readStoredSkin(store, 'bot')).toBeNull();
    expect(clearStoredSkin(store, 'bot')).toBeNull();
  });
});

describe('mergeSkinLoaderConfig', () => {
  it('空文件写出一份只有本地那条 loader 的配置', () => {
    const out = JSON.parse(mergeSkinLoaderConfig('')) as { loadlist: Array<Record<string, unknown>> };
    expect(out.loadlist).toHaveLength(1);
    expect(out.loadlist[0]).toMatchObject({
      name: 'LocalSkin',
      type: 'Legacy',
      skin: 'LocalSkin/skins/{USERNAME}.png',
      model: 'auto',
    });
  });

  it('本地那条排到最前,其余条目与别的字段原样留着', () => {
    const prev = JSON.stringify({
      version: '15.0.1',
      enableCape: false,
      loadlist: [
        { name: 'Mojang', type: 'MojangAPI' },
        { name: 'LittleSkin', type: 'CustomSkinAPI', root: 'https://littleskin.cn/csl/' },
      ],
    });
    const out = JSON.parse(mergeSkinLoaderConfig(prev)) as {
      enableCape: boolean;
      loadlist: Array<{ name: string }>;
    };
    expect(out.enableCape).toBe(false);
    expect(out.loadlist.map((e) => e.name)).toEqual(['LocalSkin', 'Mojang', 'LittleSkin']);
  });

  it('已经有的本地那条不被重写,只是挪到前面', () => {
    const prev = JSON.stringify({
      loadlist: [
        { name: 'Mojang', type: 'MojangAPI' },
        { name: '我自己配的', type: 'Legacy', skin: 'LocalSkin/skins/{USERNAME}.png', model: 'slim' },
      ],
    });
    const out = JSON.parse(mergeSkinLoaderConfig(prev)) as { loadlist: Array<Record<string, unknown>> };
    expect(out.loadlist[0]).toMatchObject({ name: '我自己配的', model: 'slim' });
    expect(out.loadlist).toHaveLength(2);
  });
});

describe('applySkins', () => {
  it('按账号名铺进游戏目录,并写好 loader 配置', () => {
    const game = tmp();
    const bytes = png(64, 64);
    applySkins(game, [{ username: 'CortiV', bytes }], nullLogger());

    expect(readFileSync(installedSkinPath(game, 'CortiV')).equals(bytes)).toBe(true);
    const config = JSON.parse(
      readFileSync(join(game, 'CustomSkinLoader', 'CustomSkinLoader.json'), 'utf8'),
    ) as { loadlist: Array<{ name: string }> };
    expect(config.loadlist[0].name).toBe('LocalSkin');
    expect(installedMatches(game, 'CortiV', bytes)).toBe(true);
  });

  it('两个账号各铺各的', () => {
    const game = tmp();
    const her = png(64, 64, 0x10);
    const his = png(64, 64, 0x90);
    applySkins(game, [{ username: 'CortiV', bytes: her }, { username: 'Phant', bytes: his }], nullLogger());
    expect(installedMatches(game, 'CortiV', her)).toBe(true);
    expect(installedMatches(game, 'Phant', his)).toBe(true);
  });

  it('换一张就覆盖掉上一张', () => {
    const game = tmp();
    const first = png(64, 64, 0x10);
    const second = png(64, 64, 0x90);
    applySkins(game, [{ username: 'CortiV', bytes: first }], nullLogger());
    applySkins(game, [{ username: 'CortiV', bytes: second }], nullLogger());
    expect(installedMatches(game, 'CortiV', second)).toBe(true);
  });

  it('谁都没选皮肤的游戏目录里不留下 loader 配置', () => {
    const game = tmp();
    applySkins(game, [], nullLogger());
    expect(existsSync(join(game, 'CustomSkinLoader'))).toBe(false);
  });
});

describe('removeInstalledSkin', () => {
  it('撤走的是本 World 铺的那份', () => {
    const game = tmp();
    const bytes = png(64, 64);
    applySkins(game, [{ username: 'CortiV', bytes }], nullLogger());
    expect(removeInstalledSkin(game, 'CortiV', bytes)).toBe(true);
    expect(existsSync(installedSkinPath(game, 'CortiV'))).toBe(false);
  });

  it('人自己放进去的皮肤不动', () => {
    const game = tmp();
    const mine = png(64, 64, 0x77);
    const dst = installedSkinPath(game, 'Phant');
    mkdirSync(join(game, 'CustomSkinLoader', 'LocalSkin', 'skins'), { recursive: true });
    writeFileSync(dst, mine);
    expect(removeInstalledSkin(game, 'Phant', png(64, 64, 0x11))).toBe(false);
    expect(readFileSync(dst).equals(mine)).toBe(true);
  });
});

describe('hasSkinMod', () => {
  it('mods 目录里有 CustomSkinLoader 的 jar 才算装了', () => {
    const game = tmp();
    expect(hasSkinMod(game)).toBe(false);
    mkdirSync(join(game, 'mods'), { recursive: true });
    writeFileSync(join(game, 'mods', 'fabric-api-0.100.8+1.20.6.jar'), '');
    expect(hasSkinMod(game)).toBe(false);
    writeFileSync(join(game, 'mods', 'CustomSkinLoader_Universal-15.0.1.jar'), '');
    expect(hasSkinMod(game)).toBe(true);
  });
});
