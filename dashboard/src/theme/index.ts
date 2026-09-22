// Stella 品牌主题（方案 §10.5，评审定案：色值取自 assets/pic/Stella_logo_origin.jpg 实测）
// —— 背景基准 #171D24（logo 底色深板岩蓝）、强调 #E5CE9C（星芒金，仅作 secondary）。
// 对比度门禁：primary 对 white ≥ 4.5:1（#2E3B4E ≈ 9.3:1，#8FB0CC ≈ 6.4:1，均通过）。
import type { ThemeDefinition } from 'vuetify';

export const StellaTheme: ThemeDefinition = {
  dark: false,
  colors: {
    primary: '#2E3B4E',
    secondary: '#B99649',
    accent: '#E5CE9C',
    background: '#F5F7FA',
    surface: '#FFFFFF',
    error: '#B3261E',
    info: '#2E5E8F',
    success: '#2E6B4F',
    warning: '#9A6A00',
  },
};

export const StellaThemeDark: ThemeDefinition = {
  dark: true,
  colors: {
    primary: '#8FB0CC',
    secondary: '#E5CE9C',
    accent: '#F8E8C0',
    background: '#171D24',
    surface: '#1E2732',
    error: '#F2B8B5',
    info: '#9AC6F0',
    success: '#9CD8B8',
    warning: '#F2D98D',
  },
};
