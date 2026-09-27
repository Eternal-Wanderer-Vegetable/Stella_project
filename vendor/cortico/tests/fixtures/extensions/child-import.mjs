// 子进程里 `cortico/*` 能不能解析,解析出来的是不是框架自己那一份。
import { nowIso } from 'cortico/core/util.ts';
import { nowIso as direct } from '../../../src/core/util.ts';

console.log(typeof nowIso);
if (nowIso !== direct) {
  console.error('cortico/core/util.ts 与直接 import 的不是同一个实例');
  process.exit(2);
}
