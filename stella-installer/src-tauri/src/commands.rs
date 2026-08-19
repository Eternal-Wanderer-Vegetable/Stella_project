//! Tauri command 层。函数体只做「调 python + 转 JSON」，不含业务逻辑。

use crate::python;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};

/// 环境自检。返回 `deploy doctor --json` 的原始 JSON 字符串。
///
/// 返回 String 而非 serde_json::Value：前端拿到就 JSON.parse，中间再解析一遍
/// 是多余的开销，且会丢掉 Python 侧的字段顺序（对调试友好）。
///
/// doctor 的退出码 1 表示「发现阻塞性问题」，不是调用失败——这里必须放行，
/// 否则有 error 时前端会收到错误而不是检查结果。
#[tauri::command]
pub fn run_doctor() -> Result<String, String> {
    let (stdout, stderr, code) = python::run_deploy(&["doctor", "--json"])?;
    // doctor 的退出码 1 表示「发现阻塞性问题」，是正常结果而非调用失败。
    // 其他非零码才是异常（Python 崩了、模块 import 失败等）。
    if code != 0 && code != 1 {
        return Err(format!(
            "deploy doctor 异常退出（code {code}）：\n{}",
            if stderr.trim().is_empty() { stdout.clone() } else { stderr }
        ));
    }
    extract_json(&stdout)
        .map(str::to_owned)
        .ok_or_else(|| format!(
            "deploy doctor 未输出 JSON。\nstdout: {stdout}\nstderr: {stderr}"
        ))
}

/// 进程与链路状态。返回 `deploy status --json` 的原始 JSON 字符串。
///
/// status 只报告状态，不判断成败，因此非零退出码才是异常。
#[tauri::command]
pub fn get_status() -> Result<String, String> {
    let (stdout, stderr, code) = python::run_deploy(&["status", "--json"])?;
    if code != 0 {
        return Err(format!(
            "deploy status 异常退出（code {code}）：\n{}",
            if stderr.trim().is_empty() { stdout.clone() } else { stderr }
        ));
    }
    extract_json(&stdout)
        .map(str::to_owned)
        .ok_or_else(|| format!("deploy status 未输出 JSON。\nstdout: {stdout}\nstderr: {stderr}"))
}

/// 后台启动 Bot。对应 `deploy start --detach`。
#[tauri::command]
pub fn start_bot(force: bool) -> Result<String, String> {
    let mut args = vec!["start", "--detach"];
    if force {
        args.push("--force");
    }
    let (stdout, stderr, code) = python::run_deploy(&args)?;
    if code != 0 {
        return Err(format!(
            "启动失败（code {code}）：\n{}",
            if stderr.trim().is_empty() { stdout } else { stderr }
        ));
    }
    Ok(stdout)
}

/// 优雅停止。对应 `deploy stop`，可能等待在途任务收尾。
#[tauri::command]
pub fn stop_bot() -> Result<String, String> {
    let (stdout, stderr, code) = python::run_deploy(&["stop"])?;
    if code != 0 {
        return Err(format!(
            "停止失败（code {code}）：\n{}",
            if stderr.trim().is_empty() { stdout } else { stderr }
        ));
    }
    Ok(stdout)
}

/// 读结构化日志尾部最多 `max_bytes` 字节，返回原始文本。
///
/// 直接读文件而不是调用 Python，且只读取尾部有限字节，避免高频轮询把整个日志
/// 文件载入内存。开头不完整的半行会被丢弃，前端负责逐行 JSON 容错。
#[tauri::command]
pub fn read_log_tail(path: Option<String>, max_bytes: usize) -> Result<String, String> {
    let path = path
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| python::project_root().join("logs").join("stella.jsonl"));
    let mut file = match File::open(&path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(String::new()),
        Err(error) => return Err(format!("无法读取日志 {}：{error}", path.display())),
    };
    if max_bytes == 0 {
        return Ok(String::new());
    }
    let size = file
        .metadata()
        .map_err(|error| format!("无法读取日志 {} 的大小：{error}", path.display()))?
        .len();
    let start = size.saturating_sub(max_bytes as u64);
    file.seek(SeekFrom::Start(start))
        .map_err(|error| format!("无法定位日志 {}：{error}", path.display()))?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| format!("无法读取日志 {}：{error}", path.display()))?;
    if start > 0 {
        if let Some(newline) = bytes.iter().position(|byte| *byte == b'\n') {
            bytes.drain(..=newline);
        } else {
            bytes.clear();
        }
    }
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

/// 从混杂输出里提取第一个完整的 JSON 对象。
///
/// Python 的 warning（如 PendingDeprecationWarning）通常走 stderr，但某些
/// 情况会落到 stdout，混在 JSON 前后会让前端 JSON.parse 直接失败。
/// 与 memory/consolidator.py 的 _parse_json 同样的容错思路。
fn extract_json(s: &str) -> Option<&str> {
    let start = s.find('{')?;
    let end = s.rfind('}')?;
    if end > start {
        Some(&s[start..=end])
    } else {
        None
    }
}
