import type { ConfigGroup } from '../../core/types.ts';
import type { BraveClientConfig } from './brave-client.ts';

/** World 自有配置的默认值;启用状态由部署装配配置决定。 */
export const WEBSEARCH_DEFAULTS = {
  enabled: false,
  /** 结果地区(ISO 2位);中文场景默认CN */
  country: 'CN',
  searchLang: 'zh-hans',
  uiLang: 'zh-CN',
  safesearch: 'moderate' as BraveClientConfig['safesearch'],
  timeoutMs: 20000,
} as const;

/** 本 World 需要的密钥的环境变量名(core 不认识这个名字) */
export const WEBSEARCH_SECRET = 'BRAVE_API_KEY';

/** 本 World 声明的可调项:搜哪个地区、用什么语言、多久超时 */
export const WEBSEARCH_CONFIG_GROUP: ConfigGroup = {
  id: 'world:websearch',
  owner: 'world:websearch',
  schema: {
    type: 'object',
    title: 'WebSearch · 检索偏好',
    description: 'Brave Search 的地区与语言;改完重启生效(客户端构造时固定)。',
    properties: {
      'worlds.websearch.country': {
        type: 'string',
        title: '结果地区',
        'x-hot': false,
        description: 'ISO 两位国家码,如 CN / US。',
      },
      'worlds.websearch.searchLang': {
        type: 'string',
        title: '搜索语言',
        'x-hot': false,
        description: '如 zh-hans。',
      },
      'worlds.websearch.uiLang': {
        type: 'string',
        title: '响应语言',
        'x-hot': false,
        description: '如 zh-CN。',
      },
      'worlds.websearch.safesearch': {
        type: 'string',
        title: '安全搜索',
        enum: ['off', 'moderate', 'strict'],
        'x-hot': false,
        description: '过滤强度。',
      },
      'worlds.websearch.timeoutMs': {
        type: 'integer',
        title: '请求超时',
        minimum: 1000,
        maximum: 120_000,
        multipleOf: 1000,
        'x-scale': 1000,
        'x-suffix': 's',
        'x-hot': false,
        description: '单次搜索请求的超时。',
      },
    },
  },
};

/** config.json 的 `worlds.websearch` 节。全部在构造时读走,改完重启 World 生效。 */
export interface WebSearchConfigSection {
  enabled: boolean;
  country: string;
  searchLang: string;
  uiLang: string;
  safesearch: BraveClientConfig['safesearch'];
  timeoutMs: number;
}
