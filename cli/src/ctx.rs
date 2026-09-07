// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! 运行上下文：部署形态检测、项目根定位、Python 解释器发现。
//!
//! 形态判定优先级（方案 §4）：``--mode`` 参数 > ``STELLA_MODE`` 环境变量 > 自动检测。
//! 自动检测按序：runtime/python.exe 存在（Windows 发布包布局）→ 本地；
//! docker-compose.yml 且 docker 可用 → docker；bot.py 且能找到 Python → 本地。
//! runtime/ 优先于 compose 文件是刻意的：装了嵌入式运行时的目录一定是本地发布包，
//! 而「仓库克隆 + 装了 docker 的开发机」两种形态都该有明确的覆盖手段。

use std::env;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{bail, Context, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Local,
    Docker,
}

impl Mode {
    pub fn label(self) -> &'static str {
        match self {
            Mode::Local => "本地（Python 直接运行）",
            Mode::Docker => "docker compose",
        }
    }
}

/// 一次命令执行所需的全部环境信息。
pub struct Ctx {
    pub mode: Mode,
    /// Stella 项目根（含 bot.py 或 docker-compose.yml 的目录）
    pub root: PathBuf,
    /// 本地形态的 Python 调用前缀；docker 形态为空
    pub python: Vec<String>,
}

/// 解析形态与项目根。``explicit`` 来自 ``--mode``，环境变量次之，最后自动检测。
pub fn resolve(explicit: Option<Mode>) -> Result<Ctx> {
    let root = find_root().context(
        "未找到 Stella 项目根（当前目录及上级都没有 bot.py / docker-compose.yml）。\n\
         请在项目目录内运行 stellacli，或参考部署文档：docs/deployment-docker.md",
    )?;

    let mode = match explicit.or_else(mode_from_env) {
        Some(m) => m,
        None => auto_detect(&root)?,
    };

    match mode {
        Mode::Local => {
            let python = find_python(&root).ok_or_else(|| no_python_error(&root))?;
            Ok(Ctx { mode, root, python })
        }
        Mode::Docker => {
            if !docker_available() {
                bail!(
                    "检测到 docker 形态，但宿主机上找不到可用的 docker。\n\
                     安装 Docker 后重试，或用 --mode local 切换本地形态。"
                );
            }
            if docker_form_precondition_missing(&root) {
                bail!(
                    "docker 形态需要项目根下的 docker-compose.yml（当前根：{}）",
                    root.display()
                );
            }
            Ok(Ctx {
                mode,
                root,
                python: Vec::new(),
            })
        }
    }
}

fn mode_from_env() -> Option<Mode> {
    match env::var("STELLA_MODE")
        .ok()?
        .trim()
        .to_ascii_lowercase()
        .as_str()
    {
        "local" => Some(Mode::Local),
        "docker" => Some(Mode::Docker),
        _ => None,
    }
}

/// 从当前目录向上找项目根：含 bot.py 或 docker-compose.yml 的最近目录。
fn find_root() -> Option<PathBuf> {
    let mut dir = env::current_dir().ok()?;
    loop {
        if dir.join("bot.py").is_file() || dir.join("docker-compose.yml").is_file() {
            return Some(dir);
        }
        if !dir.pop() {
            return None;
        }
    }
}

fn auto_detect(root: &Path) -> Result<Mode> {
    // Windows 发布包布局：runtime/ 里带 python.exe，一定是本地形态
    if embedded_python(root).is_some() {
        return Ok(Mode::Local);
    }
    if root.join("docker-compose.yml").is_file() && docker_available() {
        return Ok(Mode::Docker);
    }
    if root.join("bot.py").is_file() && find_python(root).is_some() {
        return Ok(Mode::Local);
    }
    bail!(
        "无法自动判断部署形态（项目根：{}）。\n\
         - 想用本地运行：需要可用的 Python（runtime/python.exe 或 PATH 里的 python3），或加 --mode local 查看具体缺什么\n\
         - 想用 docker：需要安装 Docker 并保留 docker-compose.yml，或加 --mode docker 查看具体缺什么",
        root.display()
    )
}

fn embedded_python(root: &Path) -> Option<PathBuf> {
    let exe = root.join("runtime").join("python.exe");
    exe.is_file().then_some(exe)
}

/// 解释器发现（与 GUI 侧 python.rs 的约定一致）：
/// runtime/python.exe → python3 → python →（Windows）py -3。
/// 返回调用前缀，如 ``["py", "-3"]``。
pub fn find_python(root: &Path) -> Option<Vec<String>> {
    if let Some(exe) = embedded_python(root) {
        return Some(vec![exe.to_string_lossy().into_owned()]);
    }
    for name in ["python3", "python"] {
        if probe_python(name, &[]) {
            return Some(vec![name.to_string()]);
        }
    }
    if probe_python("py", &["-3"]) {
        return Some(vec!["py".into(), "-3".into()]);
    }
    None
}

/// 探测候选解释器。输出里必须含 "Python"——Windows 的 python3 有时是商店别名
/// 存根，跑 --version 只会打开商店或输出广告语，不能当可用解释器。
fn probe_python(program: &str, pre_args: &[&str]) -> bool {
    let out = Command::new(program)
        .args(pre_args)
        .arg("--version")
        .output();
    match out {
        Ok(o) => {
            let text = format!(
                "{}{}",
                String::from_utf8_lossy(&o.stdout),
                String::from_utf8_lossy(&o.stderr)
            );
            text.contains("Python")
        }
        Err(_) => false,
    }
}

fn no_python_error(root: &Path) -> anyhow::Error {
    anyhow::anyhow!(
        "本地形态需要 Python 3.10+，当前都没找到：\n\
         - Windows 发布包应带 runtime/python.exe（项目根：{}）\n\
         - 或在 PATH 里安装 python3 / python（Windows 也可用 py 启动器）\n\
         - 不想装 Python 可改用 docker 形态（--mode docker），见 docs/deployment-docker.md",
        root.display()
    )
}

/// docker 形态的先决条件是否缺失（缺 compose 文件；docker 本体可用性单独探测）。
/// 单独成函数只为可测：resolve 依赖 cwd 定位根，不适合单测。
fn docker_form_precondition_missing(root: &Path) -> bool {
    !root.join("docker-compose.yml").is_file()
}

pub fn docker_available() -> bool {
    Command::new("docker")
        .arg("--version")
        .output()
        .is_ok_and(|o| o.status.success())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn touch(dir: &Path, name: &str) {
        std::fs::write(dir.join(name), "").unwrap();
    }

    #[test]
    fn auto_detect_prefers_runtime_layout() {
        let tmp = tempdir();
        touch(&tmp, "docker-compose.yml");
        touch(&tmp, "bot.py");
        let rt = tmp.join("runtime");
        std::fs::create_dir_all(&rt).unwrap();
        touch(&rt, "python.exe");
        assert_eq!(auto_detect(&tmp).unwrap(), Mode::Local);
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn auto_detect_bot_only_is_local() {
        let tmp = tempdir();
        touch(&tmp, "bot.py");
        // 无 runtime、无 compose 文件时能否 local 取决于机器上有没有 python；
        // 这里只断言「不会判成 docker」
        assert!(auto_detect(&tmp).map(|m| m != Mode::Docker).unwrap_or(true));
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn explicit_docker_without_compose_file_rejected() {
        // 直接验证判据本身（resolve 依赖 cwd 定位根，不适合在这里测）
        let tmp = tempdir();
        touch(&tmp, "bot.py");
        assert!(!tmp.join("docker-compose.yml").is_file());
        assert!(docker_form_precondition_missing(&tmp));
        std::fs::remove_dir_all(&tmp).ok();
    }

    fn tempdir() -> PathBuf {
        // 用纳秒时间戳拼目录名：SystemTime 的 Debug 带花括号，Windows 路径不接受
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir =
            std::env::temp_dir().join(format!("stellacli-test-{}-{nanos}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }
}
