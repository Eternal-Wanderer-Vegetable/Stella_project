//! 定位并调用 Python 侧的 `deploy` 模块。
//!
//! 所有业务逻辑都在 Python 里（检查、配置渲染、进程管理），Rust 只负责起子进程、
//! 拿输出、转成前端要的 JSON。这个分工是刻意的：检查逻辑能被 pytest 覆盖、
//! 在终端可直接跑、将来 Web 前端复用同一接口。
//!
//! 三个平台相关的坑：
//! 1. **Python 位置**：开发时是 PATH 里的（conda 环境），Release 时是 `<项目根>/runtime/python.exe`；
//! 2. **工作目录**：必须是项目根 —— `python -m deploy` 要能 import 到 `deploy` 包；
//! 3. **Windows 下必须抑制控制台窗口** —— 否则每次调用都会闪一个黑框。

use std::path::{Path, PathBuf};
use std::process::Command;

/// 定位 Stella 项目根目录（含 bot.py 与 deploy/ 的那一层）。
///
/// 两种运行形态：
/// - `cargo tauri dev`：exe 在 stella-installer/src-tauri/target/debug/，
///   项目根在其上几层。但更可靠的是用 CARGO_MANIFEST_DIR 编译期常量向上两层；
/// - Release：exe 与 bot.py 同目录（安装器会被放进 Stella 解压目录）。
///
/// 判据统一为「向上找到含 bot.py 的目录」，而不是硬编码层数——
/// 这样两种形态用同一套逻辑，且目录结构调整时不会静默失效。
pub fn project_root() -> PathBuf {
    // 形态一：从当前 exe 位置向上找含 bot.py 的目录（Release：exe 与 bot.py 同层）
    if let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
    {
        let mut dir: Option<&Path> = Some(exe_dir.as_path());
        for _ in 0..6 {
            if let Some(d) = dir {
                if d.join("bot.py").is_file() {
                    return d.to_path_buf();
                }
                dir = d.parent();
            }
        }
    }
    // 形态二（开发兜底）：CARGO_MANIFEST_DIR 是 src-tauri/，向上两级即项目根
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

/// 优先用 Release 包自带的运行时，回退到 PATH 里的 python。
///
/// 与 release_assets/serve.bat 的三级查找同源：runtime\python.exe →
/// PATH 的 python → py 启动器。这里只做前两级，py 启动器留给安装流程处理。
pub fn find_python(root: &Path) -> PathBuf {
    let embedded = [
        root.join("runtime").join("python.exe"),       // Windows
        root.join("runtime").join("bin").join("python"), // POSIX
    ];
    for c in embedded {
        if c.is_file() {
            return c;
        }
    }
    // 交给 PATH 解析；找不到时 Command::spawn 会报错，由 run_deploy 带回给前端
    PathBuf::from("python")
}

/// 执行 `python -m deploy <args>`，返回 `(stdout, stderr, 退出码)`。
///
/// 退出码语义交给调用方判断：`doctor` 的 1 是「发现阻塞问题」的正常结果，
/// 其他命令的非零才是异常——run_deploy 自己不做成败判断，只如实带回。
///
/// 用 from_utf8_lossy 而非 from_utf8：deploy/__main__.py 已经强制 stdout 为
/// UTF-8，但 stderr 可能混入其他编码（如 Windows 的系统错误消息），非法字节
/// 不该让整个调用失败。
pub fn run_deploy(args: &[&str]) -> Result<(String, String, i32), String> {
    let root = project_root();
    let python = find_python(&root);

    let mut cmd = Command::new(&python);
    cmd.arg("-m").arg("deploy").args(args).current_dir(&root);

    // Windows 抑制黑窗：不加则每次调用都闪一个黑色控制台窗口。
    // 几乎所有 Tauri + 子进程的项目都会踩这个坑。0x0800_0000 = CREATE_NO_WINDOW。
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000);
    }

    let output = cmd.output().map_err(|e| {
        format!(
            "无法启动 Python（{}）：{e}\n检查 Python 是否安装并在 PATH 中，或运行 start.bat 拉取运行时。",
            python.display()
        )
    })?;

    let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
    let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
    let code = output.status.code().unwrap_or(-1);
    Ok((stdout, stderr, code))
}
