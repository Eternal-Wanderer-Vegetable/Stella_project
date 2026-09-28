//! Stella 稳定启动入口（S11 Phase 2）。
//!
//! 安装器把各版本程序树放在 `<安装目录>\app\<版本>\`，本 exe 固定在
//! `<安装目录>\Stella.exe`（模板安装位）。启动流程：
//!
//! 1. 读机器级激活记录 `%LOCALAPPDATA%\Stella\active-install.json`
//!    （安装目录内 `.stella\active-install.json` 为兜底副本位置）；
//! 2. 校验记录树路径必须位于 `<安装目录>\app` 之下且含 `bot.py`——
//!    记录是机器持久状态，等同不可信输入；
//! 3. 记录缺失/损坏 → 枚举 `app\*` 取最高版本兜底；
//! 4. 以 cwd=树、透传参数启动树内 `Stella.exe`，launcher 本身随即退出；
//! 5. 全部失败 → 弹窗说明并退出 1。
//!
//! 刻意不做：不改写记录（写回属于安装事务）、不提权、不读配置文件——
//! launcher 的正确性依赖「任何单点失败都有下一层兜底」。

#![windows_subsystem = "windows"]

use std::path::{Path, PathBuf};
use std::process::Command;

const RECORD_FILENAME: &str = "active-install.json";
const APPS_DIRNAME: &str = "app";
const MAIN_BINARY: &str = "Stella.exe";
const TREE_MARKER: &str = "bot.py";

fn main() {
    std::process::exit(run());
}

fn run() -> i32 {
    let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
    else {
        show_error("无法定位启动器自身目录。");
        return 1;
    };
    let passthrough: Vec<String> = std::env::args().skip(1).collect();

    let Some(tree) = resolve_tree(&exe_dir) else {
        show_error(&format!(
            "未找到可启动的 Stella 程序树。\n请重新运行安装器修复（安装目录：{}）。",
            exe_dir.display()
        ));
        return 1;
    };

    let exe = tree.join(MAIN_BINARY);
    match Command::new(&exe)
        .current_dir(&tree)
        .args(&passthrough)
        .spawn()
    {
        Ok(_) => 0,
        Err(err) => {
            show_error(&format!(
                "启动 Stella 失败（{}）：{}\n请重新运行安装器修复。",
                exe.display(),
                err
            ));
            1
        }
    }
}

/// 激活记录优先，枚举兜底；路径一律经过 containment 校验。
fn resolve_tree(exe_dir: &Path) -> Option<PathBuf> {
    for record in record_candidate_paths(exe_dir) {
        if let Ok(text) = std::fs::read_to_string(&record) {
            if let Some(tree) = tree_from_record(&text, exe_dir) {
                return Some(tree);
            }
        }
    }
    let mut trees = enumerate_trees(exe_dir);
    trees.pop()
}

fn record_candidate_paths(exe_dir: &Path) -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(local) = std::env::var_os("LOCALAPPDATA") {
        candidates.push(
            PathBuf::from(local).join("Stella").join(RECORD_FILENAME),
        );
    }
    candidates.push(exe_dir.join(".stella").join(RECORD_FILENAME));
    candidates
}

/// 解析记录 JSON：containment（树必须位于 `<安装目录>\app` 之下）+
/// `bot.py` 存在。任何不满足返回 None——调用方走枚举兜底。
fn tree_from_record(raw: &str, exe_dir: &Path) -> Option<PathBuf> {
    let value: serde_json::Value = serde_json::from_str(raw).ok()?;
    let path = PathBuf::from(value.get("path")?.as_str()?);
    let apps_root = exe_dir.join(APPS_DIRNAME);
    if !path.starts_with(&apps_root) {
        return None;
    }
    if path.join(TREE_MARKER).is_file() {
        Some(path)
    } else {
        None
    }
}

/// 枚举 `app\*` 内含 bot.py 的树，按版本号从新到旧排序（无版本名的排最后）。
fn enumerate_trees(exe_dir: &Path) -> Vec<PathBuf> {
    let apps = exe_dir.join(APPS_DIRNAME);
    let mut trees: Vec<(Vec<u64>, String, PathBuf)> = Vec::new();
    let Ok(entries) = std::fs::read_dir(&apps) else {
        return Vec::new();
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() && path.join(TREE_MARKER).is_file() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let key = parse_version(&name);
            trees.push((key, name, path));
        }
    }
    trees.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| b.1.cmp(&a.1)));
    trees.into_iter().map(|(_, _, path)| path).collect()
}

/// "5.1.2" → [5,1,2]；非数字段按 0 处理（版本排序的宽容实现）。
fn parse_version(name: &str) -> Vec<u64> {
    name.split('.')
        .map(|part| part.parse::<u64>().unwrap_or(0))
        .collect()
}

#[cfg(windows)]
fn show_error(message: &str) {
    use std::os::windows::ffi::OsStrExt;

    let wide: Vec<u16> = std::ffi::OsStr::new(message)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let caption: Vec<u16> = std::ffi::OsStr::new("Stella")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    #[link(name = "user32")]
    extern "system" {
        fn MessageBoxW(
            hwnd: *const core::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            kind: u32,
        ) -> i32;
    }
    unsafe {
        MessageBoxW(
            std::ptr::null(),
            wide.as_ptr(),
            caption.as_ptr(),
            0x0000_0010, // MB_ICONERROR
        );
    }
}

#[cfg(not(windows))]
fn show_error(message: &str) {
    eprintln!("{message}");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root(tag: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("stella-launcher-{tag}"));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join(APPS_DIRNAME)).unwrap();
        dir
    }

    fn seed_tree(root: &Path, version: &str) -> PathBuf {
        let tree = root.join(APPS_DIRNAME).join(version);
        std::fs::create_dir_all(&tree).unwrap();
        std::fs::write(tree.join(TREE_MARKER), b"").unwrap();
        tree
    }

    #[test]
    fn record_tree_validates_containment_and_marker() {
        let root = temp_root("record");
        let tree = seed_tree(&root, "5.1.0");
        let json_path = tree.display().to_string().replace('\\', "\\\\");
        let good = format!(
            r#"{{"schema_version": 1, "version": "5.1.0", "path": "{json_path}"}}"#
        );
        assert_eq!(
            tree_from_record(&good, &root).as_deref(),
            Some(tree.as_path())
        );

        // 树外路径拒绝
        let evil_path = root.join("elsewhere").display().to_string().replace('\\', "\\\\");
        let evil = format!(r#"{{"path": "{evil_path}"}}"#);
        assert!(tree_from_record(&evil, &root).is_none());
        // 损坏 JSON 拒绝
        assert!(tree_from_record("{broken", &root).is_none());
        // 缺 bot.py 拒绝
        std::fs::remove_file(tree.join(TREE_MARKER)).unwrap();
        assert!(tree_from_record(&good, &root).is_none());
        std::fs::write(tree.join(TREE_MARKER), b"").unwrap();

        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn enumeration_sorts_newest_first_and_drops_incomplete() {
        let root = temp_root("enum");
        seed_tree(&root, "5.0.0");
        seed_tree(&root, "5.10.0");
        seed_tree(&root, "5.9.0");
        let incomplete = root.join(APPS_DIRNAME).join("6.0.0");
        std::fs::create_dir_all(&incomplete).unwrap(); // 无 bot.py

        let trees = enumerate_trees(&root);
        let names: Vec<String> = trees
            .iter()
            .map(|t| t.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        assert_eq!(names, vec!["5.10.0", "5.9.0", "5.0.0"]);
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn version_parse_is_componentwise() {
        assert_eq!(parse_version("5.1.2"), vec![5, 1, 2]);
        assert_eq!(parse_version("junk"), vec![0]);
    }
}
