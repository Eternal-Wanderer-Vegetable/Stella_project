import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, statSync, unlinkSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import type { OverlayAssetInfo } from './types.ts';

const MAX_ASSET_BYTES = 8 * 1024 * 1024;
const ASSET_ID_RE = /^[a-f0-9]{64}\.(?:png|jpg|webp|gif)$/;

const MIME_BY_EXT: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
};

export class OverlayAssetStore {
  constructor(readonly dir: string) {}

  list(baseUrl: string | null): OverlayAssetInfo[] {
    if (!existsSync(this.dir)) return [];
    return readdirSync(this.dir, { withFileTypes: true })
      .filter((entry) => entry.isFile() && ASSET_ID_RE.test(entry.name))
      .map((entry) => {
        const ext = entry.name.split('.').pop() ?? '';
        return {
          id: entry.name,
          mime: MIME_BY_EXT[ext] ?? 'application/octet-stream',
          size: statSync(join(this.dir, entry.name)).size,
          url: baseUrl ? `${baseUrl}/assets/${entry.name}` : '',
        };
      })
      .sort((a, b) => a.id.localeCompare(b.id));
  }

  import(base64: string): { id: string; mime: string; size: number } {
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(base64) || base64.length % 4 !== 0) {
      throw new Error('素材不是有效的 base64');
    }
    const bytes = Buffer.from(base64, 'base64');
    if (!bytes.length) throw new Error('素材为空');
    if (bytes.length > MAX_ASSET_BYTES) throw new Error('素材不能超过 8 MiB');
    const detected = detectImage(bytes);
    if (!detected) throw new Error('只支持 PNG、JPEG、WebP 和 GIF 图片');
    const id = `${createHash('sha256').update(bytes).digest('hex')}.${detected.ext}`;
    if (!existsSync(this.dir)) mkdirSync(this.dir, { recursive: true });
    const path = join(this.dir, id);
    if (!existsSync(path)) writeFileSync(path, bytes);
    return { id, mime: detected.mime, size: bytes.length };
  }

  delete(id: string): boolean {
    if (!ASSET_ID_RE.test(id)) throw new Error('素材 id 无效');
    const path = join(this.dir, id);
    if (!existsSync(path)) return false;
    unlinkSync(path);
    return true;
  }

  path(id: string): { path: string; mime: string } | null {
    if (!ASSET_ID_RE.test(id)) return null;
    const path = join(this.dir, id);
    if (!existsSync(path)) return null;
    const ext = id.split('.').pop() ?? '';
    return { path, mime: MIME_BY_EXT[ext] ?? 'application/octet-stream' };
  }
}

function detectImage(bytes: Buffer): { ext: string; mime: string } | null {
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) {
    return { ext: 'png', mime: 'image/png' };
  }
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return { ext: 'jpg', mime: 'image/jpeg' };
  }
  if (bytes.length >= 12 && bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP') {
    return { ext: 'webp', mime: 'image/webp' };
  }
  if (bytes.length >= 6 && (bytes.toString('ascii', 0, 6) === 'GIF87a' || bytes.toString('ascii', 0, 6) === 'GIF89a')) {
    return { ext: 'gif', mime: 'image/gif' };
  }
  return null;
}
