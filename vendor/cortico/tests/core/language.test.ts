/**
 * 控制台默认语言依次读取 config.language、进程环境和系统 locale。
 * 非中文 locale 使用英文，locale 缺失时用中文；请求可另行选择语言。
 */
import { describe, it, expect } from 'vitest';
import {
  detectLanguage, languageOfLocale, pick, resolveLanguage, systemLanguage,
} from '../../src/core/language.ts';
import { coreConfigGroup, CORE_CONFIG_GROUP } from '../../src/core/config.ts';
import { coerceGroupValues } from '../../src/core/config-schema.ts';

describe('languageOfLocale', () => {
  it('中文的各种写法都归 zh,其余归 en,空值算未知', () => {
    for (const tag of ['zh', 'zh-CN', 'zh-Hant-TW', 'ZH_cn', ' zh-SG ']) expect(languageOfLocale(tag)).toBe('zh');
    for (const tag of ['en-US', 'ja', 'de-DE', 'fr']) expect(languageOfLocale(tag)).toBe('en');
    expect(languageOfLocale('')).toBeUndefined();
    expect(languageOfLocale(undefined)).toBeUndefined();
  });
});

describe('detectLanguage / resolveLanguage', () => {
  it('环境变量压过系统区域;不认识的值当没设', () => {
    expect(detectLanguage({ CORTICO_LANGUAGE: 'en' }, 'zh-CN')).toBe('en');
    expect(detectLanguage({ CORTICO_LANGUAGE: 'zh' }, 'en-US')).toBe('zh');
    expect(detectLanguage({ CORTICO_LANGUAGE: 'fr' }, 'en-US')).toBe('en');
    expect(detectLanguage({}, 'zh-CN')).toBe('zh');
    expect(detectLanguage({}, 'en-US')).toBe('en');
  });

  it('区域读不到时保持中文', () => {
    expect(detectLanguage({}, undefined)).toBe('zh');
    expect(detectLanguage({}, '')).toBe('zh');
  });

  it('配置值赢过系统读数;非法配置值忽略', () => {
    expect(resolveLanguage('zh')).toBe('zh');
    expect(resolveLanguage('en')).toBe('en');
    expect(resolveLanguage('auto')).toBe(systemLanguage());
    expect(resolveLanguage(undefined)).toBe(systemLanguage());
  });

  it('系统读数进程内只读一次', () => {
    expect(systemLanguage()).toBe(systemLanguage());
  });
});

describe('pick 与串表', () => {
  it('按语言取表', () => {
    const table = { zh: { a: '甲' }, en: { a: 'A' } };
    expect(pick('zh', table).a).toBe('甲');
    expect(pick('en', table).a).toBe('A');
  });

  it('core 配置组两种语言结构一致,只有文案不同', () => {
    const zh = coreConfigGroup('zh');
    const en = coreConfigGroup('en');
    expect(zh).toEqual(CORE_CONFIG_GROUP);
    expect(Object.keys(en.schema.properties)).toEqual(Object.keys(zh.schema.properties));
    for (const key of Object.keys(zh.schema.properties)) {
      const { title: _t1, description: _d1, 'x-suffix': _s1, ...zhRest } = zh.schema.properties[key];
      const { title: _t2, description: _d2, 'x-suffix': _s2, ...enRest } = en.schema.properties[key];
      expect(enRest).toEqual(zhRest);
      expect(en.schema.properties[key].title).not.toBe(zh.schema.properties[key].title);
    }
  });

  it('校验回执按语言措辞,缺省中文', () => {
    const group = coreConfigGroup('en');
    expect(coerceGroupValues(group, { 'batching.maxBatchSize': 0 }, 'en'))
      .toEqual({ error: 'Batch size limit cannot be less than 1' });
    expect(coerceGroupValues(coreConfigGroup('zh'), { 'batching.maxBatchSize': 0 }))
      .toEqual({ error: '单批上限 不能小于 1' });
  });
});
