/** 由 CORTICO_FAKE_MODE 选择正常退出、非零退出或重启请求;每次启动记录到 CORTICO_FAKE_LOG。 */
import { appendFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const mode = process.env.CORTICO_FAKE_MODE ?? 'clean';
const dataDir = process.env.CORTICO_FAKE_DATA_DIR ?? '';
const logFile = process.env.CORTICO_FAKE_LOG ?? '';

if (logFile) appendFileSync(logFile, `${mode}\n`);
if (dataDir) process.send?.({ type: 'cortico:ready', dataDir });

// 第二次启动正常退出,限制重启次数。
const runs = process.env.CORTICO_FAKE_LOG
  ? (await import('node:fs')).readFileSync(logFile, 'utf8').trim().split('\n').length
  : 1;
const effective = runs > 1 ? 'clean' : mode;

if (effective === 'ready-restart') {
  writeFileSync(join(dataDir, '.restart-request'), 'test\n');
  process.send?.({ type: 'cortico:restart' });
} else if (effective === 'flag-only') {
  writeFileSync(join(dataDir, '.restart-request'), 'test\n');
}

process.exit(effective === 'crash' ? 3 : 0);
