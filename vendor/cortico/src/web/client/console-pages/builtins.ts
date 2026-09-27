/** 内置面板注册表，键对应 ConsolePanelDecl.builtin。 */

import type { ConsolePanel } from '../../shared/client-panel.ts';
import { llmSettingsPanel } from './builtins/llm-settings/panel.ts';

export type BuiltinPanels = Readonly<Record<string, ConsolePanel>>;

export const BUILTIN_PANELS: BuiltinPanels = {
  'llm-settings': llmSettingsPanel,
};
