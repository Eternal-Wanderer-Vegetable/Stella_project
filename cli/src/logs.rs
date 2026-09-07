// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! logs 命令：原生 tail（不 spawn Python——docker 形态的日志文件挂载在宿主机，
//! 读文件比 compose logs 快且能按级别着色）。轮询式跟随，不引 inotify 依赖。

use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use anstyle::Reset;
use anyhow::{bail, Context, Result};
use serde_json::Value;

use crate::style;

/// 先展示的尾部行数。stella.jsonl 轮转 10MB×5，全量重放没有意义。
const TAIL_LINES: usize = 200;
const POLL_INTERVAL: Duration = Duration::from_millis(300);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Target {
    Jsonl,
    Boot,
    Thought,
}

impl Target {
    fn file_name(self) -> &'static str {
        match self {
            Target::Jsonl => "stella.jsonl",
            Target::Boot => "boot_debug.log",
            Target::Thought => "stella_thought_logs.md",
        }
    }
}

/// 日志目录解析。docker 形态优先问 compose 要**已解析**的挂载配置（宿主机侧
/// 的 /data 挂载源叫什么名字由用户的 compose 决定，不能假设是 ./StellaData）；
/// 失败或本地形态回落到启发式：StellaData/logs（分离布局）→ logs/（旧布局），
/// 与 config/home.py 的布局判定保持同序。
pub fn resolve_logs_dir(root: &Path, docker: bool) -> Option<PathBuf> {
    if docker {
        if let Some(data_dir) = resolve_docker_data_dir(root) {
            let dir = data_dir.join("logs");
            if dir.is_dir() {
                return Some(dir);
            }
        }
    }
    let separated = root.join("StellaData").join("logs");
    let legacy = root.join("logs");
    separated
        .is_dir()
        .then_some(separated)
        .or_else(|| legacy.is_dir().then_some(legacy))
}

/// 从 `docker compose config --format json` 的输出里找 stella 服务挂到 /data 的
/// bind 源路径（compose 已把它解析成绝对路径）。
fn resolve_docker_data_dir(root: &Path) -> Option<PathBuf> {
    let out = std::process::Command::new("docker")
        .args(["compose", "config", "--format", "json"])
        .current_dir(root)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let v: Value = serde_json::from_slice(&out.stdout).ok()?;
    extract_data_mount(&v)
}

/// 纯解析部分单独成函数以便单测（不依赖真实 docker）。
fn extract_data_mount(config: &Value) -> Option<PathBuf> {
    let volumes = config
        .get("services")?
        .get("stella")?
        .get("volumes")?
        .as_array()?;
    for vol in volumes {
        if vol.get("target").and_then(Value::as_str) == Some("/data") {
            if let Some(src) = vol.get("source").and_then(Value::as_str) {
                if !src.is_empty() {
                    return Some(PathBuf::from(src));
                }
            }
        }
    }
    None
}

pub fn run(
    root: &Path,
    docker: bool,
    target: Target,
    file: Option<&Path>,
    follow: bool,
    out: &mut dyn Write,
) -> Result<i32> {
    let path = match file {
        Some(f) => f.to_path_buf(),
        None => {
            let dir = resolve_logs_dir(root, docker).with_context(|| {
                format!(
                    "未找到日志目录（找过 docker 挂载源/logs、{} 与 {}）。\
                     首次运行或未配置时会没有日志；也可用 --file 指定任意日志文件。",
                    root.join("StellaData").join("logs").display(),
                    root.join("logs").display()
                )
            })?;
            dir.join(target.file_name())
        }
    };
    if !path.is_file() {
        bail!("日志文件不存在：{}", path.display());
    }
    tail(&path, follow, target, out)
}

fn tail(path: &Path, follow: bool, target: Target, out: &mut dyn Write) -> Result<i32> {
    let content =
        std::fs::read_to_string(path).with_context(|| format!("读取 {} 失败", path.display()))?;
    let lines: Vec<&str> = content.lines().collect();
    let start = lines.len().saturating_sub(TAIL_LINES);
    for line in &lines[start..] {
        emit_line(line, target, out);
    }
    if start > 0 {
        writeln!(out, "（已省略前面 {start} 行）")?;
    }
    if !follow {
        return Ok(0);
    }
    // 跟随：从当前文件长度起增量读；文件被轮转截短则从头再来
    let mut pos = std::fs::metadata(path)?.len();
    loop {
        thread::sleep(POLL_INTERVAL);
        let Ok(len) = std::fs::metadata(path).map(|m| m.len()) else {
            continue;
        };
        if len < pos {
            pos = 0; // 轮转/截断
        }
        if len > pos {
            if let Ok(content) = std::fs::read_to_string(path) {
                // 按“丢弃不完整尾部”的粗粒度处理：多字节字符被读半截的概率极低
                //（轮询间隔远大于写行间隔），出现时丢一行不影响可用性
                let mut consumed = 0usize;
                for line in content.split_inclusive('\n') {
                    let next = consumed + line.len();
                    if next > pos as usize && line.ends_with('\n') {
                        emit_line(line.trim_end_matches('\n'), target, out);
                    }
                    consumed = next;
                }
                pos = len;
            } else {
                pos = len;
            }
        }
    }
}

fn emit_line(line: &str, target: Target, out: &mut dyn Write) {
    match target {
        Target::Jsonl => {
            let _ = writeln!(out, "{}", render_jsonl(line));
        }
        _ => {
            let _ = writeln!(out, "{line}");
        }
    }
}

/// 单行结构化日志 → 人读行。解析失败原样输出（混入的警告行不丢）。
/// 字段契约见 core/logging_sink.py：ts / level / module / message / [truncated]。
fn render_jsonl(line: &str) -> String {
    let Some(v) = serde_json::from_str::<Value>(line).ok() else {
        return line.to_string();
    };
    let ts = v.get("ts").and_then(Value::as_str).unwrap_or("");
    let level = v.get("level").and_then(Value::as_str).unwrap_or("");
    let message = v.get("message").and_then(Value::as_str).unwrap_or("");
    let module = v.get("module").and_then(Value::as_str).unwrap_or("");
    let truncated = if v.get("truncated").and_then(Value::as_bool).unwrap_or(false) {
        "…（截断）"
    } else {
        ""
    };
    let (st, reset) = match level {
        "ERROR" | "CRITICAL" => (
            style::ERROR.render().to_string(),
            Reset.render().to_string(),
        ),
        "WARNING" => (style::WARN.render().to_string(), Reset.render().to_string()),
        "INFO" => (String::new(), String::new()),
        _ => (style::DIM.render().to_string(), Reset.render().to_string()),
    };
    let module_part = if module.is_empty() {
        String::new()
    } else {
        format!("[{module}] ")
    };
    format!("{ts} {st}{level}{reset} {module_part}{message}{truncated}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn jsonl_line_rendering() {
        let line = r#"{"ts":"2026-09-07T12:00:00+08:00","level":"WARNING","module":"core.x","message":"小心"}"#;
        let text = render_jsonl(line);
        assert!(text.contains("2026-09-07T12:00:00"));
        assert!(text.contains("WARNING"));
        assert!(text.contains("[core.x]"));
        assert!(text.contains("小心"));
    }

    #[test]
    fn jsonl_truncated_marker() {
        let line = r#"{"ts":"t","level":"INFO","module":"m","message":"长文本","truncated":true}"#;
        assert!(render_jsonl(line).contains("…（截断）"));
    }

    #[test]
    fn non_json_line_passes_through() {
        assert_eq!(render_jsonl("普通警告行"), "普通警告行");
    }

    #[test]
    fn docker_compose_config_mount_extraction() {
        let cfg: Value = serde_json::json!({
            "services": {"stella": {"volumes": [
                {"type": "bind", "source": "E:/some/dir/data", "target": "/data"},
                {"type": "bind", "source": "E:/x", "target": "/other"}
            ]}}
        });
        assert_eq!(
            extract_data_mount(&cfg),
            Some(PathBuf::from("E:/some/dir/data"))
        );
    }

    #[test]
    fn docker_compose_config_without_data_mount() {
        let cfg: Value = serde_json::json!({"services": {"stella": {"volumes": []}}});
        assert_eq!(extract_data_mount(&cfg), None);
    }

    #[test]
    fn logs_dir_prefers_stella_data() {
        let tmp = std::env::temp_dir().join(format!("stellacli-logs-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(tmp.join("StellaData/logs")).unwrap();
        std::fs::create_dir_all(tmp.join("logs")).unwrap();
        assert_eq!(
            resolve_logs_dir(&tmp, false).unwrap(),
            tmp.join("StellaData/logs")
        );
        std::fs::remove_dir_all(&tmp).ok();
    }
}
