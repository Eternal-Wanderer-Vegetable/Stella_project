// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! 终端样式常量。级别配色刻意与 deploy/report.py 的 _LEVEL_STYLES 一致——
//! 用户在 GUI/CLI/`python -m deploy` 三处看到的颜色语义必须相同。

use anstyle::{AnsiColor, Color, Style};

const fn fg(color: AnsiColor) -> Option<Color> {
    Some(Color::Ansi(color))
}

pub const OK: Style = Style::new().fg_color(fg(AnsiColor::Green));
pub const WARN: Style = Style::new().fg_color(fg(AnsiColor::Yellow)).bold();
pub const ERROR: Style = Style::new().fg_color(fg(AnsiColor::Red)).bold();
pub const INFO: Style = Style::new().fg_color(fg(AnsiColor::Cyan));
pub const TITLE: Style = Style::new().bold();
pub const DIM: Style = Style::new().fg_color(fg(AnsiColor::BrightBlack));
