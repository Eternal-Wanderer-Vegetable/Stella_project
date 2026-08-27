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
use std::sync::OnceLock;

#[cfg(windows)]
mod runtime_bootstrap {
    use std::fs::{self, File, OpenOptions};
    use std::io::{self, Read, Write};
    use std::path::Path;
    use std::process::{Command, Stdio};
    use std::sync::Mutex;
    use std::time::{Duration, Instant};

    use sha2::{Digest, Sha256};

    /// 与 `release_assets/start.bat` 保持同步。
    /// **修改 PY_VER / PY_SHA256 时必须同步更新 start.bat，同值校验见 tests::python_runtime_constants_sync_with_start_bat**
    const PY_VER: &str = "3.12.10";
    const PY_SHA256: &str =
        "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3";
    const PY_MIRRORS: &[&str] = &[
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip",
        "https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-embed-amd64.zip",
    ];
    const GET_PIP_URL: &str = "https://bootstrap.pypa.io/get-pip.py";
    const PYPI_INDEX: &str = "https://pypi.org/simple";
    const PIP_MIRROR: &str = "https://pypi.tuna.tsinghua.edu.cn/simple";
    const DEPS_MARKER: &str = ".stella-deps-ready";
    const PROGRESS_FILE: &str = ".bootstrap-progress";
    const MIN_ZIP_SIZE: u64 = 1_048_576;
    const MIN_GET_PIP_SIZE: u64 = 500_000;

    static PREPARE_LOCK: Mutex<()> = Mutex::new(());

    fn emit_progress(root: &Path, msg: &str) {
        // 控制台可见（终端用户）+ 进度文件（GUI 可轮询）
        eprintln!("[runtime] {msg}");
        let runtime = root.join("runtime");
        // 进度文件写入失败不影响主流程
        let _ = fs::create_dir_all(&runtime);
        let _ = fs::write(runtime.join(PROGRESS_FILE), msg);
    }

    fn clear_progress(root: &Path) {
        let _ = fs::remove_file(root.join("runtime").join(PROGRESS_FILE));
    }

    fn cleanup_partial_runtime(runtime: &Path) {
        // 解压失败会残留半个 runtime/，下次启动会误判 python.exe 已存在而跳过下载
        // 导致“校验失败后永远起不来”。因此解压/校验失败时回滚整个目录。
        if runtime.is_dir() {
            let _ = fs::remove_dir_all(runtime);
        }
    }

    /// 准备嵌入式 Python 运行时与依赖，等价于 `start.bat` 的安装段。
    ///
    /// 成功后会写 `runtime/.stella-deps-ready`，状态轮询据此跳过重复安装。
    /// 若 `runtime/python.exe` 已存在（上次中断），只补装依赖并继续。
    pub fn prepare_runtime(root: &Path) -> Result<(), String> {
        let _guard = PREPARE_LOCK
            .lock()
            .map_err(|_| "运行时准备锁异常".to_owned())?;

        let runtime = root.join("runtime");
        // 依赖就绪标记里存的是 requirements.txt 的 sha256，不是一个空文件/固定字符串。
        // 为什么：升级时用户会把整个 runtime/ 复用过来（省 100MB 下载），旧的空标记
        // 跟着过来就等于「依赖已就绪」，新版本新增的依赖于是永远装不上。存哈希后
        // requirements.txt 一变就自动重装。判据必须与 release_assets/start.bat 一致。
        if deps_marker_matches(root, &runtime) {
            return Ok(());
        }

        let python = runtime.join("python.exe");
        let is_fresh_runtime = !python.is_file();

        emit_progress(root, "正在准备 Python 运行时…");
        let result: Result<(), String> = (|| {
            if !python.is_file() {
                let zip_path = root.join(format!("python-{PY_VER}-embed-amd64.zip"));
                emit_progress(root, &format!("正在下载 Python {PY_VER}（约 15MB）…"));
                download_and_verify(root, &zip_path).map_err(|e| {
                    // 下载/校验失败：删除残留的 zip，避免下次误用
                    let _ = fs::remove_file(&zip_path);
                    e
                })?;
                emit_progress(root, "正在校验并解压运行时…");
                if let Err(e) = extract_zip(&zip_path, &runtime) {
                    cleanup_partial_runtime(&runtime);
                    let _ = fs::remove_file(&zip_path);
                    return Err(e);
                }
                let _ = fs::remove_file(&zip_path);
            }
            emit_progress(root, "正在配置 site-packages…");
            patch_pth(&runtime)?;
            emit_progress(root, "正在安装 pip…");
            ensure_pip(root, &python)?;
            emit_progress(root, "正在安装构建工具…");
            ensure_build_tools(root, &python)?;
            emit_progress(root, "正在安装依赖（首次约 1-2 分钟）…");
            install_deps(root, &python)?;

            // 标记里存 requirements.txt 的哈希，而不是一句 "ready"：详见 deps_marker_matches
            let marked = requirements_hash(root).unwrap_or_else(|| "ready".to_owned());
            fs::write(runtime.join(DEPS_MARKER), marked + "\n").map_err(|e| e.to_string())?;
            Ok(())
        })();

        if let Err(ref e) = result {
            // 仅当全新安装且在解压/校验阶段失败时回滚，避免误删已可用的旧 runtime
            if is_fresh_runtime && (e.contains("校验失败") || e.contains("解压") || e.contains("压缩包")) {
                cleanup_partial_runtime(&runtime);
            }
            emit_progress(root, &format!("准备失败：{e}"));
        } else {
            clear_progress(root);
            emit_progress(root, "运行时准备完成");
            clear_progress(root);
        }
        result
    }

    fn download_and_verify(root: &Path, zip_path: &Path) -> Result<(), String> {
        let mut last_err = String::new();
        for url in PY_MIRRORS {
            // 断点续传：保留已有部分，由 download() 内部决定是否 Range 续传
            match download(root, url, zip_path) {
                Ok(()) => {},
                Err(e) => {
                    last_err = e;
                    continue;
                }
            }
            let size = fs::metadata(zip_path).map(|m| m.len()).unwrap_or(0);
            if size < MIN_ZIP_SIZE {
                last_err = format!("{url} 下载不完整（{size} 字节）");
                continue;
            }
            let actual = sha256_hex(zip_path)?;
            if actual != PY_SHA256 {
                fs::remove_file(zip_path).ok();
                // 校验失败需回滚：runtime 可能已有半解压内容
                let runtime = root.join("runtime");
                cleanup_partial_runtime(&runtime);
                return Err(format!(
                    "Python 运行时校验失败\n期望: {PY_SHA256}\n实际: {actual}\n已清理残留文件，请重试。"
                ));
            }
            return Ok(());
        }
        Err(format!(
            "下载 Python 运行时失败（所有镜像均不可用）：{}\n最后错误：{last_err}\n请检查网络后重试，或手动运行 start.bat。",
            zip_path.display()
        ))
    }

    fn download(root: &Path, url: &str, dest: &Path) -> Result<(), String> {
        let existing = fs::metadata(dest).map(|m| m.len()).unwrap_or(0);
        // 断点续传：已有部分且大小合理时尝试 Range
        let mut req = ureq::get(url).timeout(Duration::from_secs(120));
        let resume_from = if existing > 0 && existing < 50 * 1024 * 1024 {
            req = req.set("Range", &format!("bytes={existing}-"));
            Some(existing)
        } else {
            if existing > 0 {
                let _ = fs::remove_file(dest);
            }
            None
        };

        let resp = req.call().map_err(|e| format!("{url}: {e}"))?;
        let status = resp.status();
        let is_partial = status == 206;
        // 206 时 Content-Length 是剩余部分，需加上已有部分才是总量
        let remaining: u64 = resp
            .header("Content-Length")
            .and_then(|v| v.parse().ok())
            .unwrap_or(0);
        let total = if is_partial { existing + remaining } else { remaining };

        let mut reader = resp.into_reader();
        let mut file: File = if is_partial {
            OpenOptions::new()
                .append(true)
                .open(dest)
                .map_err(|e| format!("打开 {} 失败：{e}", dest.display()))?
        } else {
            if resume_from.is_some() {
                // 服务器不支持 Range，回退为全量重下
                let _ = fs::remove_file(dest);
            }
            File::create(dest).map_err(|e| format!("创建 {} 失败：{e}", dest.display()))?
        };

        let mut buf = [0u8; 8192];
        let mut downloaded = if is_partial { existing } else { 0 };
        let mut last_emit = Instant::now();
        let mut last_emit_bytes = downloaded;
        loop {
            let n = reader.read(&mut buf).map_err(|e| format!("读取 {url} 失败：{e}"))?;
            if n == 0 {
                break;
            }
            file.write_all(&buf[..n])
                .map_err(|e| format!("写入 {} 失败：{e}", dest.display()))?;
            downloaded += n as u64;
            // 每 500ms 或 512KB 刷新一次进度，避免刷屏
            if last_emit.elapsed() >= Duration::from_millis(500)
                || downloaded - last_emit_bytes >= 512 * 1024
            {
                if total > 0 {
                    let pct = downloaded as f64 / total as f64 * 100.0;
                    emit_progress(
                        root,
                        &format!("下载中 {pct:.1}% ({downloaded}/{total} 字节) {url}"),
                    );
                } else {
                    emit_progress(root, &format!("已下载 {downloaded} 字节 {url}"));
                }
                last_emit = Instant::now();
                last_emit_bytes = downloaded;
            }
        }
        if total > 0 {
            emit_progress(
                root,
                &format!("下载完成 {downloaded}/{total} 字节 {url}"),
            );
        }
        Ok(())
    }

    /// `requirements.txt` 的 sha256（大写十六进制）。读不到时返回 None。
    fn requirements_hash(root: &Path) -> Option<String> {
        sha256_hex(&root.join("requirements.txt")).ok()
    }

    /// 依赖就绪标记是否与当前 `requirements.txt` 匹配。
    ///
    /// 兼容旧标记：3.0.0 及更早写的是 `ready`，内容对不上 → 判为未就绪 → 重跑一次
    /// pip（幂等，已满足的依赖会被跳过），之后标记就自动升级成哈希了。
    fn deps_marker_matches(root: &Path, runtime: &Path) -> bool {
        let Ok(recorded) = fs::read_to_string(runtime.join(DEPS_MARKER)) else {
            return false;
        };
        match requirements_hash(root) {
            // 没有 requirements.txt 时退化为「有标记就算就绪」
            None => true,
            Some(expected) => recorded.trim().eq_ignore_ascii_case(&expected),
        }
    }

    fn sha256_hex(path: &Path) -> Result<String, String> {
        let mut file = File::open(path).map_err(|e| e.to_string())?;
        let mut hasher = Sha256::new();
        io::copy(&mut file, &mut hasher).map_err(|e| e.to_string())?;
        Ok(format!("{:X}", hasher.finalize()))
    }

    fn extract_zip(zip_path: &Path, dest: &Path) -> Result<(), String> {
        let file = File::open(zip_path).map_err(|e| e.to_string())?;
        let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("解压失败：{e}"))?;
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
        let mut fallback_reason: Option<String> = None;
        let mut installed = false;
        // get-pip.py 也走带进度与断点续传的下载
        if download(root, GET_PIP_URL, &get_pip).is_ok() {
            let size = fs::metadata(&get_pip).map(|m| m.len()).unwrap_or(0);
            if size >= MIN_GET_PIP_SIZE {
                // get-pip.py 会用本机 pip 配置的索引；显式指定官方源，
                // 避免用户全局配置指向不可用的镜像导致 bootstrap 失败。
                let args = [
                    "get-pip.py",
                    "--no-warn-script-location",
                    "--index-url",
                    PYPI_INDEX,
                ];
                match run(python, &args, root) {
                    Ok(_) => installed = true,
                    Err(e) => fallback_reason = Some(e),
                }
            } else {
                fallback_reason = Some("get-pip.py 下载不完整".to_owned());
            }
        } else {
            fallback_reason = Some(format!("get-pip.py 下载失败：{GET_PIP_URL}"));
        }
        fs::remove_file(&get_pip).ok();

        if installed {
            return Ok(());
        }
        // ensurepip 使用随附的本地 wheel，不依赖网络索引。
        let hint = fallback_reason
            .map(|r| format!("\n（get-pip 未成功：{r}）"))
            .unwrap_or_default();
        run(python, &["-m", "ensurepip", "--upgrade"], root)
            .map(|_| ())
            .map_err(|e| format!("pip 安装失败：{e}{hint}"))
    }

    /// 安装 setuptools + wheel。
    ///
    /// **必需，不是可选优化。** 嵌入式 Python 只带标准库，而现在的 `get-pip.py`
    /// 只装 pip（setuptools/wheel 早就从它的默认项里去掉了）。于是任何**只发 sdist、
    /// 不发 wheel** 的依赖都装不上——pip 要构建它，就得 import `setuptools.build_meta`，
    /// 报 `BackendUnavailable: Cannot import 'setuptools.build_meta'` 直接退出码 2。
    ///
    /// 2026-08-26 的 v3.0.0 预发布就是这样炸的：`qrcode_terminal` 在 PyPI 上只有
    /// 源码包，全新解压的发布包装依赖必然失败。开发机不复现，因为那里的 runtime 早年
    /// 被老版 get-pip 带上过 setuptools。
    ///
    /// 失败**不阻断**：多数依赖有 wheel，缺构建工具只影响 sdist 那几个，
    /// 真需要时会在 install_deps 里报出来，那条错误信息比这里更具体。
    fn ensure_build_tools(root: &Path, python: &Path) -> Result<(), String> {
        let args = [
            "-m", "pip", "install", "--no-warn-script-location",
            "-i", PYPI_INDEX, "setuptools", "wheel",
        ];
        if run(python, &args, root).is_ok() {
            return Ok(());
        }
        let mirror = [
            "-m", "pip", "install", "--no-warn-script-location",
            "-i", PIP_MIRROR, "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
            "setuptools", "wheel",
        ];
        let _ = run(python, &mirror, root);
        Ok(())
    }

    fn install_deps(root: &Path, python: &Path) -> Result<(), String> {
        let requirements = root.join("requirements.txt");
        if !requirements.is_file() {
            return Err(format!("缺少 {}", requirements.display()));
        }
        let primary = [
            "-m", "pip", "install", "-r", "requirements.txt",
            "--no-warn-script-location", "-i", PYPI_INDEX,
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

        #[test]
        fn python_runtime_constants_sync_with_start_bat() {
            let bat_path = Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
                .join("release_assets")
                .join("start.bat");
            // 开发环境可能没有 release_assets/start.bat（如 CI 精简检出），此时跳过
            if !bat_path.is_file() {
                return;
            }
            let bat = fs::read_to_string(&bat_path).expect("无法读取 start.bat");
            assert!(
                bat.contains(PY_VER),
                "PY_VER {PY_VER} 未在 start.bat 中找到，请同步修改"
            );
            assert!(
                bat.contains(PY_SHA256),
                "PY_SHA256 未在 start.bat 中找到，请同步修改 start.bat 与 python.rs"
            );
            // 进一步校验 bat 中的 SHA256 行格式正确
            let sha_line = bat
                .lines()
                .find(|l| l.contains("PY_SHA256"))
                .unwrap_or("");
            assert!(
                sha_line.contains(PY_SHA256),
                "start.bat 的 PY_SHA256 与 python.rs 不一致"
            );
        }

        /// 两条 bootstrap 路径（GUI 的 python.rs 与命令行的 start.bat）都必须装构建工具。
        ///
        /// 少了它，任何只发 sdist 的依赖都会以
        /// `BackendUnavailable: Cannot import 'setuptools.build_meta'` 装不上
        /// ——v3.0.0 预发布被 qrcode_terminal 卡住就是这个。开发机不复现（那里的
        /// runtime 早年被老版 get-pip 带上过 setuptools），所以只能靠这条断言防回归。
        #[test]
        fn both_bootstrap_paths_install_build_tools() {
            let src = fs::read_to_string(Path::new(file!())).expect("无法读取 python.rs");
            assert!(
                src.contains("fn ensure_build_tools"),
                "python.rs 必须装 setuptools/wheel，否则 sdist 依赖装不上"
            );
            assert!(
                src.contains("ensure_build_tools(root, &python)?"),
                "ensure_build_tools 必须在 bootstrap 序列里被真的调用"
            );

            let bat_path = Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
                .join("release_assets")
                .join("start.bat");
            if !bat_path.is_file() {
                return;
            }
            let bat = fs::read_to_string(&bat_path).expect("无法读取 start.bat");
            assert!(
                bat.contains("pip install setuptools wheel"),
                "start.bat 必须在装依赖之前装 setuptools/wheel"
            );
            let tools_at = bat
                .find("pip install setuptools wheel")
                .expect("上一步已断言存在");
            let reqs_at = bat
                .find("pip install -r requirements.txt")
                .expect("start.bat 应当安装 requirements.txt");
            assert!(
                tools_at < reqs_at,
                "构建工具必须先装：装依赖时才需要它来构建 sdist"
            );
        }

        /// 依赖就绪标记必须两边都按 requirements.txt 的哈希判定。
        ///
        /// 升级时用户会把整个 runtime/ 复用过来省下 100MB 下载。旧实现的标记是个
        /// 空文件，跟着复用过去就等于「依赖已就绪」，新版本新增的依赖永远装不上，
        /// 而且报错发生在 import 阶段，看起来完全不像升级引起的。
        #[test]
        fn deps_marker_is_content_based_on_both_paths() {
            let src = fs::read_to_string(Path::new(file!())).expect("无法读取 python.rs");
            assert!(
                src.contains("fn deps_marker_matches"),
                "python.rs 必须按内容判定依赖就绪，而不是「标记文件存在」"
            );
            assert!(
                src.contains("fn requirements_hash"),
                "判据必须是 requirements.txt 的哈希"
            );

            let bat_path = Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("..")
                .join("..")
                .join("release_assets")
                .join("start.bat");
            if !bat_path.is_file() {
                return;
            }
            let bat = fs::read_to_string(&bat_path).expect("无法读取 start.bat");
            assert!(
                bat.contains(":req_hash"),
                "start.bat 必须计算 requirements.txt 的哈希"
            );
            assert!(
                bat.contains("hashfile \"requirements.txt\" SHA256"),
                "start.bat 必须用 certutil 算 requirements.txt 的 SHA256"
            );
            assert!(
                !bat.contains("echo ready"),
                "start.bat 不能再写固定内容的就绪标记（复用 runtime 时会漏装依赖）"
            );
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

/// 用户数据目录（``STELLA_HOME``）：``.env``、空间配置、人格、记忆库都在这里。
///
/// **判据只有 ``config/home.py`` 一份**，所以这里问 Python 要（`deploy paths`），
/// 不在 Rust 里重写一遍定位逻辑。两处各写一套的后果是「一边读旧目录、一边写新目录」，
/// 用户会看到「保存成功但没生效」这种最难查的症状。
///
/// 取不到就退回程序目录 = 退回旧布局，界面照常可用。结果缓存：进程运行期间数据目录
/// 不会变，而每次文件操作都起一个 Python 子进程太慢。
pub fn data_root() -> PathBuf {
    static CACHE: OnceLock<PathBuf> = OnceLock::new();
    CACHE
        .get_or_init(|| {
            run_deploy_without_prepare(&["paths"])
                .ok()
                .filter(|(_, _, code)| *code == 0)
                .and_then(|(stdout, _, _)| {
                    serde_json::from_str::<serde_json::Value>(extract_json_str(&stdout)?)
                        .ok()?
                        .get("stella_home")?
                        .as_str()
                        .map(PathBuf::from)
                })
                .unwrap_or_else(project_root)
        })
        .clone()
}

/// 从可能夹带日志的 stdout 里截出 JSON 对象（与 commands.rs 的 extract_json 同源）。
fn extract_json_str(text: &str) -> Option<&str> {
    let start = text.find('{')?;
    let end = text.rfind('}')?;
    if end > start {
        Some(&text[start..=end])
    } else {
        None
    }
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
    run_deploy_inner(args, true)
}

/// 执行无需准备 Python 的命令。关闭窗口时使用它，避免用户只打开界面后
/// 关闭窗口却触发首次运行时下载。
pub fn run_deploy_without_prepare(args: &[&str]) -> Result<(String, String, i32), String> {
    run_deploy_inner(args, false)
}

fn run_deploy_inner(
    args: &[&str],
    prepare: bool,
) -> Result<(String, String, i32), String> {
    let root = project_root();
    if prepare {
        prepare_runtime(&root)?;
    }
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
