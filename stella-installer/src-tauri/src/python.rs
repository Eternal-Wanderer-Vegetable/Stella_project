//! 定位并调用 Python 侧的 `deploy` 模块。
//!
//! 所有业务逻辑都在 Python 里（检查、配置渲染、进程管理），Rust 只负责起子进程、
//! 拿输出、转成前端要的 JSON。这个分工是刻意的：检查逻辑能被 pytest 覆盖、
//! 在终端可直接跑、将来 Web 前端复用同一接口。
//!
//! Release 形态首次使用时需要准备嵌入式 Python 运行时与依赖。该步骤用纯 Rust
//! 实现（下载、SHA-256 校验、解压、启用 site-packages、安装 pip 与依赖），
//! 不依赖 `start.bat`——该脚本保留为手动备用安装方式。
//!
//! 三个平台相关的坑：
//! 1. **Python 位置**：开发时是 PATH 里的（conda 环境），Release 时是 `<项目根>/runtime/python.exe`；
//! 2. **工作目录**：必须是项目根 —— `python -m deploy` 要能 import 到 `deploy` 包；
//! 3. **Windows 下必须抑制控制台窗口** —— 否则每次调用都会闪一个黑框。

use std::path::{Path, PathBuf};
use std::process::Command;

#[cfg(windows)]
mod runtime_bootstrap {
    use std::fs::{self, File};
    use std::io;
    use std::path::Path;
    use std::process::{Command, Stdio};
    use std::sync::Mutex;

    use sha2::{Digest, Sha256};

    /// 与 `release_assets/start.bat` 保持同步。
    const PY_VER: &str = "3.12.10";
    const PY_SHA256: &str =
        "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3";
    const PY_MIRRORS: &[&str] = &[
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
        "https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-embed-amd64.zip",
    ];
    const GET_PIP_URL: &str = "https://bootstrap.pypa.io/get-pip.py";
    const PIP_MIRROR: &str = "https://pypi.tuna.tsinghua.edu.cn/simple";
    const DEPS_MARKER: &str = ".stella-deps-ready";
    const MIN_ZIP_SIZE: u64 = 1_048_576;
    const MIN_GET_PIP_SIZE: u64 = 500_000;

    static PREPARE_LOCK: Mutex<()> = Mutex::new(());

    /// 准备嵌入式 Python 运行时与依赖，等价于 `start.bat` 的安装段。
    ///
    /// 成功后会写 `runtime/.stella-deps-ready`，状态轮询据此跳过重复安装。
    /// 若 `runtime/python.exe` 已存在（上次中断），只补装依赖并继续。
    pub fn prepare_runtime(root: &Path) -> Result<(), String> {
        let _guard = PREPARE_LOCK
            .lock()
            .map_err(|_| "运行时准备锁异常".to_owned())?;

        let runtime = root.join("runtime");
        if runtime.join(DEPS_MARKER).is_file() {
            return Ok(());
        }

        let python = runtime.join("python.exe");
        if !python.is_file() {
            let zip_path = root.join(format!("python-{PY_VER}-embed-amd64.zip"));
            download_and_verify(&zip_path)?;
            extract_zip(&zip_path, &runtime)?;
            fs::remove_file(&zip_path).ok();
        }
        patch_pth(&runtime)?;
        ensure_pip(root, &python)?;
        install_deps(root, &python)?;

        fs::write(runtime.join(DEPS_MARKER), "ready\n").map_err(|e| e.to_string())?;
        Ok(())
    }

    fn download_and_verify(zip_path: &Path) -> Result<(), String> {
        for url in PY_MIRRORS {
            fs::remove_file(zip_path).ok();
            if download(url, zip_path).is_err() {
                continue;
            }
            let size = fs::metadata(zip_path).map(|m| m.len()).unwrap_or(0);
            if size < MIN_ZIP_SIZE {
                continue;
            }
            let actual = sha256_hex(zip_path)?;
            if actual != PY_SHA256 {
                fs::remove_file(zip_path).ok();
                return Err(format!(
                    "Python 运行时校验失败\n期望: {PY_SHA256}\n实际: {actual}"
                ));
            }
            return Ok(());
        }
        Err(format!(
            "下载 Python 运行时失败（所有镜像均不可用）：{}",
            zip_path.display()
        ))
    }

    fn download(url: &str, dest: &Path) -> Result<(), String> {
        let response = ureq::get(url)
            .timeout(std::time::Duration::from_secs(120))
            .call()
            .map_err(|e| format!("{url}: {e}"))?;
        let mut reader = response.into_reader();
        let mut file =
            File::create(dest).map_err(|e| format!("创建 {} 失败：{e}", dest.display()))?;
        io::copy(&mut reader, &mut file).map_err(|e| format!("写入 {} 失败：{e}", dest.display()))?;
        Ok(())
    }

    fn sha256_hex(path: &Path) -> Result<String, String> {
        let mut file = File::open(path).map_err(|e| e.to_string())?;
        let mut hasher = Sha256::new();
        io::copy(&mut file, &mut hasher).map_err(|e| e.to_string())?;
        Ok(format!("{:X}", hasher.finalize()))
    }

    fn extract_zip(zip_path: &Path, dest: &Path) -> Result<(), String> {
        let file = File::open(zip_path).map_err(|e| e.to_string())?;
        let mut archive = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
        for index in 0..archive.len() {
            let mut entry = archive.by_index(index).map_err(|e| e.to_string())?;
            let name = entry.name().replace('\\', "/");
            if name.starts_with('/') || name.split('/').any(|part| part == "..") {
                return Err(format!("压缩包包含不安全路径：{name}"));
            }
            let out = dest.join(&name);
            if entry.is_dir() {
                fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            } else {
                if let Some(parent) = out.parent() {
                    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                }
                let mut writer = File::create(&out).map_err(|e| e.to_string())?;
                io::copy(&mut entry, &mut writer).map_err(|e| e.to_string())?;
            }
        }
        Ok(())
    }

    fn patch_pth(runtime: &Path) -> Result<(), String> {
        for entry in fs::read_dir(runtime).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            let file_name = entry.file_name().to_string_lossy().into_owned();
            if !(file_name.starts_with("python") && file_name.ends_with("._pth")) {
                continue;
            }
            let path = entry.path();
            let mut text = fs::read_to_string(&path).map_err(|e| e.to_string())?;
            text = text.replace("#import site", "import site");
            if !text.lines().any(|line| line.trim() == "..") {
                if !text.ends_with('\n') {
                    text.push('\n');
                }
                text.push_str("..\n");
            }
            fs::write(&path, text).map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    fn ensure_pip(root: &Path, python: &Path) -> Result<(), String> {
        let get_pip = root.join("get-pip.py");
        let mut used = false;
        if download(GET_PIP_URL, &get_pip).is_ok() {
            let size = fs::metadata(&get_pip).map(|m| m.len()).unwrap_or(0);
            if size >= MIN_GET_PIP_SIZE {
                used = true;
                run(python, &["get-pip.py", "--no-warn-script-location"], root)
                    .map_err(|e| format!("pip 安装失败：{e}"))?;
            }
        }
        fs::remove_file(&get_pip).ok();
        if !used {
            run(python, &["-m", "ensurepip", "--upgrade"], root)
                .map_err(|e| format!("pip 安装失败：{e}"))?;
        }
        Ok(())
    }

    fn install_deps(root: &Path, python: &Path) -> Result<(), String> {
        let requirements = root.join("requirements.txt");
        if !requirements.is_file() {
            return Err(format!("缺少 {}", requirements.display()));
        }
        let primary = [
            "-m", "pip", "install", "-r", "requirements.txt", "--no-warn-script-location",
        ];
        match run(python, &primary, root) {
            Ok(_) => Ok(()),
            Err(first) => {
                let mirror = [
                    "-m", "pip", "install", "-r", "requirements.txt", "--no-warn-script-location",
                    "-i", PIP_MIRROR, "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
                ];
                run(python, &mirror, root)
                    .map(|_| ())
                    .map_err(|second| {
                        format!("依赖安装失败：\n{first}\n\n镜像重试也失败：\n{second}")
                    })
            }
        }
    }

    fn run(python: &Path, args: &[&str], cwd: &Path) -> Result<String, String> {
        use std::os::windows::process::CommandExt;

        let output = Command::new(python)
            .args(args)
            .current_dir(cwd)
            .stdin(Stdio::null())
            .creation_flags(0x0800_0000)
            .output()
            .map_err(|e| format!("无法运行 {}：{e}", python.display()))?;
        let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
        let stderr = String::from_utf8_lossy(&output.stderr).into_owned();
        if output.status.success() {
            Ok(format!("{stdout}\n{stderr}").trim().to_owned())
        } else {
            let code = output.status.code().unwrap_or(-1);
            Err(format!(
                "{} {} 退出码 {code}\nstdout: {stdout}\nstderr: {stderr}",
                python.display(),
                args.join(" ")
            ))
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn patch_pth_enables_site_and_project_root() {
            let dir = std::env::temp_dir().join("stella-pth-test");
            fs::create_dir_all(&dir).unwrap();
            fs::write(dir.join("python312._pth"), "#import site\n.\n").unwrap();
            patch_pth(&dir).unwrap();
            let text = fs::read_to_string(dir.join("python312._pth")).unwrap();
            assert!(text.contains("import site"));
            assert!(text.lines().any(|line| line.trim() == ".."));
            fs::remove_dir_all(&dir).ok();
        }

        #[test]
        fn sha256_hex_matches_known_vector() {
            let dir = std::env::temp_dir().join("stella-hash-test");
            fs::create_dir_all(&dir).unwrap();
            let file = dir.join("payload");
            fs::write(&file, b"abc").unwrap();
            assert_eq!(
                sha256_hex(&file).unwrap(),
                "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"
            );
            fs::remove_dir_all(&dir).ok();
        }
    }
}

#[cfg(windows)]
fn prepare_runtime(root: &Path) -> Result<(), String> {
    runtime_bootstrap::prepare_runtime(root)
}

#[cfg(not(windows))]
fn prepare_runtime(_root: &Path) -> Result<(), String> {
    Ok(())
}

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
    prepare_runtime(&root)?;
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