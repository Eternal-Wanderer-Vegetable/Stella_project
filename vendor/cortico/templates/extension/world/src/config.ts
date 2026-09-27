import type { ConfigGroup } from 'cortico/core/types.ts';

/** config.json 的 worlds.example 段，默认禁用；bot 或部署可启用。 */
export interface ExampleConfigSection {
  enabled: boolean;
  /** `example_echo` 回执的开头一句;热改。 */
  greeting: string;
}

export const EXAMPLE_DEFAULTS: ExampleConfigSection = {
  enabled: false,
  greeting: 'Example says:',
};

/** World 配置的 JSON Schema 声明。 */
export const EXAMPLE_CONFIG_GROUP: ConfigGroup = {
  id: 'world:example',
  owner: 'world:example',
  schema: {
    type: 'object',
    title: 'Example',
    properties: {
      'worlds.example.greeting': {
        type: 'string',
        title: '回执开头',
        description: 'example_echo 回执的第一句。',
        'x-hot': true,
      },
    },
  },
};
