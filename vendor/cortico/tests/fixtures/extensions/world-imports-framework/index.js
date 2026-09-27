import { nowIso } from 'cortico/core/util.ts';

export default {
  id: 'imports-framework',
  label: '借框架的 World',
  defaults: () => ({ enabled: false }),
  create: () => ({}),
  // 测试拿它与框架自己 import 的那一个比对象身份。
  nowIso,
};
