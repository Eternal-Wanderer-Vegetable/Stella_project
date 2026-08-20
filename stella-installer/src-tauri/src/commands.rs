//! Tauri command 层。函数体只做「调 python + 转 JSON」，不含业务逻辑。

use crate::python;
use serde::Deserialize;
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
pub async fn run_doctor() -> Result<String, String> {
    let (stdout, stderr, code) = tauri::async_runtime::spawn_blocking(|| {
        python::run_deploy(&["doctor", "--json"])
    })
    .await
    .map_err(|e| format!("自检任务未能完成：{e}"))??;
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
pub async fn get_status() -> Result<String, String> {
    let (stdout, stderr, code) = tauri::async_runtime::spawn_blocking(|| {
        python::run_deploy(&["status", "--json"])
    })
    .await
    .map_err(|e| format!("状态任务未能完成：{e}"))??;
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
pub async fn start_bot(force: bool) -> Result<String, String> {
    let (stdout, stderr, code) = tauri::async_runtime::spawn_blocking(move || {
        let mut args = vec!["start", "--detach"];
        if force {
            args.push("--force");
        }
        python::run_deploy(&args)
    })
    .await
    .map_err(|e| format!("启动任务未能完成：{e}"))??;
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
pub async fn stop_bot() -> Result<String, String> {
    let (stdout, stderr, code) = tauri::async_runtime::spawn_blocking(|| {
        python::run_deploy(&["stop"])
    })
    .await
    .map_err(|e| format!("停止任务未能完成：{e}"))??;
    if code != 0 {
        return Err(format!(
            "停止失败（code {code}）：\n{}",
            if stderr.trim().is_empty() { stdout } else { stderr }
        ));
    }
    Ok(stdout)
}

#[derive(Debug, Deserialize)]
pub struct ConfigInput {
    pub allowed_groups: String,
    pub onebot_mode: String,
    pub host: String,
    pub port: u16,
    pub ws_urls: String,
    pub access_token: String,
    pub lm_base_url: String,
    pub chat_model: String,
    pub consolidation_model: String,
}

/// 读取当前 GUI 配置向导需要的 .env 值。
#[tauri::command]
pub async fn get_config() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let path = python::project_root().join(".env");
        let values = if path.is_file() {
            parse_env(&std::fs::read_to_string(&path).map_err(|e| e.to_string())?)
        } else {
            std::collections::HashMap::new()
        };
        let configured = path.is_file()
            && !values.get("LM_STUDIO_MODEL").unwrap_or(&String::new()).is_empty();
        let ws_urls = values
            .get("ONEBOT_WS_URLS")
            .map(|raw| {
                serde_json::from_str::<Vec<String>>(raw)
                    .map(|urls| urls.join(","))
                    .unwrap_or_else(|_| raw.clone())
            })
            .unwrap_or_default();
        serde_json::to_string(&serde_json::json!({
            "configured": configured,
            "allowed_groups": values.get("ALLOWED_GROUPS").cloned().unwrap_or_default(),
            "onebot_mode": if values.contains_key("ONEBOT_WS_URLS") { "forward" } else { "reverse" },
            "host": values.get("HOST").cloned().unwrap_or_else(|| "127.0.0.1".into()),
            "port": values.get("PORT").and_then(|v| v.parse::<u16>().ok()).unwrap_or(8080),
            "ws_urls": ws_urls,
            "access_token": values.get("ONEBOT_ACCESS_TOKEN").cloned().unwrap_or_default(),
            "lm_base_url": values.get("LM_STUDIO_BASE_URL").cloned().unwrap_or_else(|| "http://127.0.0.1:1234".into()),
            "chat_model": values.get("LM_STUDIO_MODEL").cloned().unwrap_or_default(),
            "consolidation_model": values.get("CONSOLIDATION_LM_STUDIO_MODEL").cloned().unwrap_or_default(),
        }))
        .map_err(|e| format!("无法读取配置：{e}"))
    })
    .await
    .map_err(|e| format!("读取配置任务未能完成：{e}"))?
}

/// 通过 deploy init 的统一校验与模板渲染保存 GUI 配置。
#[tauri::command]
pub async fn save_config(config: ConfigInput) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let root = python::project_root();
        let answers_path = root.join(".stella-installer.answers.toml");
        let groups = parse_groups(&config.allowed_groups)?;
        let ws_urls = parse_list(&config.ws_urls);
        if config.onebot_mode != "reverse" && config.onebot_mode != "forward" {
            return Err("连接方式必须是 reverse 或 forward".to_owned());
        }
        if config.onebot_mode == "reverse" && !(1..=65535).contains(&config.port) {
            return Err("端口必须在 1 到 65535 之间".to_owned());
        }
        if config.onebot_mode == "forward" && ws_urls.is_empty() {
            return Err("正向 WS 模式至少需要一个地址".to_owned());
        }
        let answers = format!(
            "allowed_groups = {}\nonebot_mode = {}\nhost = {}\nport = {}\nws_urls = {}\naccess_token = {}\nlm_base_url = {}\nchat_model = {}\nconsolidation_model = {}\n",
            serde_json::to_string(&groups).unwrap(),
            toml_string(&config.onebot_mode),
            toml_string(&config.host),
            config.port,
            serde_json::to_string(&ws_urls).unwrap(),
            toml_string(&config.access_token),
            toml_string(&config.lm_base_url),
            toml_string(&config.chat_model),
            toml_string(&config.consolidation_model),
        );
        std::fs::write(&answers_path, answers).map_err(|e| format!("无法写入临时配置：{e}"))?;
        let answer_arg = answers_path.to_string_lossy().into_owned();
        let result = python::run_deploy(&["init", "--answers", &answer_arg, "--force"]);
        let _ = std::fs::remove_file(&answers_path);
        let (stdout, stderr, code) = result?;
        if code != 0 {
            return Err(if stderr.trim().is_empty() { stdout } else { stderr });
        }
        Ok(stdout)
    })
    .await
    .map_err(|e| format!("保存配置任务未能完成：{e}"))?
}

/// 从 LM Studio 的 OpenAI 兼容接口读取已加载模型。
#[tauri::command]
pub async fn list_models(base_url: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let url = format!("{}/v1/models", base_url.trim_end_matches('/'));
        let response = ureq::get(&url)
            .timeout(std::time::Duration::from_secs(5))
            .call()
            .map_err(|e| format!("无法连接 LM Studio：{e}"))?;
        let mut body = String::new();
        response
            .into_reader()
            .read_to_string(&mut body)
            .map_err(|e| format!("读取 LM Studio 响应失败：{e}"))?;
        let data: serde_json::Value = serde_json::from_str(&body)
            .map_err(|e| format!("LM Studio 返回数据无效：{e}"))?;
        let models: Vec<String> = data["data"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|item| item["id"].as_str().map(str::to_owned))
            .collect();
        serde_json::to_string(&models).map_err(|e| format!("模型列表序列化失败：{e}"))
    })
    .await
    .map_err(|e| format!("读取模型任务未能完成：{e}"))?
}

/// 读结构化日志尾部最多 `max_bytes` 字节，返回原始文本。
///
/// 直接读文件而不是调用 Python，且只读取尾部有限字节，避免高频轮询把整个日志
/// 文件载入内存。开头不完整的半行会被丢弃，前端负责逐行 JSON 容错。
#[tauri::command]
pub async fn read_log_tail(path: Option<String>, max_bytes: usize) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
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
    })
    .await
    .map_err(|e| format!("日志读取任务未能完成：{e}"))?
}

fn parse_env(text: &str) -> std::collections::HashMap<String, String> {
    text.lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                return None;
            }
            let (key, value) = line.split_once('=')?;
            let value = value.trim().trim_matches('"').trim_matches('\'');
            Some((key.trim().to_owned(), value.to_owned()))
        })
        .collect()
}

fn parse_groups(text: &str) -> Result<Vec<i64>, String> {
    let groups: Result<Vec<_>, _> = text
        .split([',', '，', ' ', '\n'])
        .filter(|value| !value.trim().is_empty())
        .map(|value| {
            value
                .trim()
                .parse::<i64>()
                .map_err(|_| format!("群号不是有效整数：{value}"))
        })
        .collect();
    let groups = groups?;
    if groups.is_empty() || groups.iter().any(|group| *group <= 0) {
        return Err("至少填写一个正整数群号".to_owned());
    }
    Ok(groups)
}

fn parse_list(text: &str) -> Vec<String> {
    text.split([',', '，', '\n'])
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .collect()
}

fn toml_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_owned())
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
