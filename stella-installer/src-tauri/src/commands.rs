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
        python::run_deploy_without_prepare(&["stop"])
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
    pub embedding_model: String,
    pub spaces: String,
    pub advanced_env: String,
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
        let (schema_stdout, schema_stderr, schema_code) =
            python::run_deploy(&["config-schema", "--json"])?;
        if schema_code != 0 {
            return Err(if schema_stderr.trim().is_empty() {
                schema_stdout
            } else {
                schema_stderr
            });
        }
        let schema: serde_json::Value = serde_json::from_str(
            extract_json(&schema_stdout).ok_or_else(|| "配置 schema 未输出 JSON".to_owned())?,
        )
        .map_err(|e| format!("配置 schema 无效：{e}"))?;
        let get = |key: &str, fallback: &str| {
            values
                .get(key)
                .cloned()
                .unwrap_or_else(|| fallback.to_owned())
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
        let root = python::project_root();
        let mut spaces = read_spaces(&root);
        let allowed_groups = values.get("ALLOWED_GROUPS").cloned().unwrap_or_default();
        spaces = merge_default_spaces(&root, &spaces, &allowed_groups);
        let advanced_env = std::fs::read_to_string(root.join(".env"))
            .or_else(|_| std::fs::read_to_string(root.join(".env.example")))
            .unwrap_or_default();
        serde_json::to_string(&serde_json::json!({
            "configured": configured,
            "allowed_groups": values.get("ALLOWED_GROUPS").cloned().unwrap_or_default(),
            "onebot_mode": if ws_urls.is_empty() { "reverse" } else { "forward" },
            "host": get("HOST", "0.0.0.0"),
            "port": get("PORT", "8080").parse::<u16>().unwrap_or(8080),
            "ws_urls": ws_urls,
            "access_token": get("ONEBOT_ACCESS_TOKEN", ""),
            "lm_base_url": get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234"),
            "chat_model": get("LM_STUDIO_MODEL", ""),
            "consolidation_model": get("CONSOLIDATION_LM_STUDIO_MODEL", ""),
            "embedding_model": get("MEMORY_EMBEDDING_MODEL", ""),
            "spaces": spaces,
            "advanced_env": advanced_env,
            "advanced_values": values,
            "schema": schema,
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
        let ws_urls = parse_list(&config.ws_urls);
        let spaces = parse_spaces(&config.spaces)?;
        let space_groups: Vec<i64> = spaces
            .iter()
            .flat_map(|(_, _, groups)| groups.iter().copied())
            .collect();
        let groups = if space_groups.is_empty() {
            parse_groups(&config.allowed_groups)?
        } else {
            let mut groups = space_groups;
            groups.sort_unstable();
            groups.dedup();
            groups
        };
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
        write_spaces(&root, &spaces)?;
        apply_advanced_env(&root, &config.advanced_env, &config, &groups)?;
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

#[tauri::command]
pub async fn get_version() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let path = python::project_root().join("pyproject.toml");
        let text = std::fs::read_to_string(&path).map_err(|e| format!("无法读取版本号：{e}"))?;
        text.lines()
            .find_map(|line| {
                let line = line.trim();
                line.strip_prefix("version = \"")
                    .and_then(|value| value.strip_suffix('"'))
                    .map(str::to_owned)
            })
            .ok_or_else(|| "pyproject.toml 中没有找到版本号".to_owned())
    })
    .await
    .map_err(|e| format!("读取版本任务未能完成：{e}"))?
}

#[tauri::command]
pub async fn get_personas() -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let root = python::project_root();
        let fallback_path = root.join("memory").join("SYSTEM.md");
        let fallback = std::fs::read_to_string(&fallback_path).unwrap_or_default();
        let mut personas = Vec::new();
        let env = std::fs::read_to_string(root.join(".env")).unwrap_or_default();
        let values = parse_env(&env);
        let spaces = merge_default_spaces(
            &root,
            &read_spaces(&root),
            values.get("ALLOWED_GROUPS").map(String::as_str).unwrap_or_default(),
        );
        for (name, prompt, groups) in parse_spaces(&spaces).unwrap_or_default() {
            let custom_path = if prompt.is_empty() {
                None
            } else {
                Some(root.join("system_prompts").join(&prompt))
            };
            let custom = custom_path
                .as_ref()
                .filter(|path| path.is_file())
                .and_then(|path| std::fs::read_to_string(path).ok());
            personas.push(serde_json::json!({
                "name": name,
                "prompt_file": prompt,
                "groups": groups,
                "fallback": custom.is_none(),
                "content": custom.unwrap_or_else(|| fallback.clone()),
            }));
        }
        serde_json::to_string(&personas).map_err(|e| format!("人格列表序列化失败：{e}"))
    })
    .await
    .map_err(|e| format!("读取人格任务未能完成：{e}"))?
}

#[tauri::command]
pub async fn save_persona(
    space: String,
    prompt_file: String,
    content: String,
) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        if space.is_empty()
            || !space
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
        {
            return Err("空间名无效".to_owned());
        }
        let file = if prompt_file.trim().is_empty() {
            format!("{space}.md")
        } else {
            prompt_file.trim().to_owned()
        };
        if !file.ends_with(".md")
            || file.contains('/')
            || file.contains('\\')
            || file.contains("..")
        {
            return Err("人格文件名必须是 system_prompts 根目录下的 .md 文件".to_owned());
        }
        let root = python::project_root();
        let dir = root.join("system_prompts");
        std::fs::create_dir_all(&dir).map_err(|e| format!("无法创建人格目录：{e}"))?;
        std::fs::write(dir.join(&file), content).map_err(|e| format!("无法保存人格：{e}"))?;
        let spaces_dir = root.join("config").join("spaces");
        std::fs::create_dir_all(&spaces_dir).map_err(|e| format!("无法创建空间目录：{e}"))?;
        let space_path = spaces_dir.join(format!("{space}.toml"));
        let old = std::fs::read_to_string(&space_path).unwrap_or_else(|_| "qq_groups = []\n".to_owned());
        let mut output = Vec::new();
        let mut replaced = false;
        for line in old.lines() {
            if line.trim_start().starts_with("system_prompt") {
                if !replaced {
                    output.push(format!("system_prompt = {}", toml_string(&file)));
                    replaced = true;
                }
            } else {
                output.push(line.to_owned());
            }
        }
        if !replaced {
            output.push(format!("system_prompt = {}", toml_string(&file)));
        }
        std::fs::write(space_path, format!("{}\n", output.join("\n")))
            .map_err(|e| format!("无法保存空间人格映射：{e}"))?;
        Ok(format!("已保存 {file}"))
    })
    .await
    .map_err(|e| format!("保存人格任务未能完成：{e}"))?
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

fn parse_spaces(text: &str) -> Result<Vec<(String, String, Vec<i64>)>, String> {
    let mut result = Vec::new();
    for (line_no, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let (name, prompt, groups) = if line.contains('|') {
            let parts: Vec<_> = line.splitn(3, '|').map(str::trim).collect();
            if parts.len() != 3 {
                return Err(format!("空间配置第 {} 行应为“空间名 | prompt.md | 群号”", line_no + 1));
            }
            (parts[0], parts[1], parts[2])
        } else {
            let (name, groups) = line
                .split_once(':')
                .ok_or_else(|| format!("空间配置第 {} 行格式无效", line_no + 1))?;
            (name.trim(), "", groups)
        };
        let name = name.trim();
        if name.is_empty()
            || !name
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
        {
            return Err(format!("空间名无效：{name}（只允许字母、数字、_、-）"));
        }
        let prompt = prompt.trim();
        if !prompt.is_empty()
            && (prompt.contains('/')
                || prompt.contains('\\')
                || prompt.contains("..")
                || !prompt.ends_with(".md"))
        {
            return Err(format!("人格文件名无效：{prompt}（只允许 system_prompts 根目录下的 .md 文件）"));
        }
        result.push((name.to_owned(), prompt.to_owned(), parse_groups(groups)?));
    }
    Ok(result)
}

fn read_spaces(root: &std::path::Path) -> String {
    let dir = root.join("config").join("spaces");
    let Ok(entries) = std::fs::read_dir(dir) else {
        return String::new();
    };
    let mut lines = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|v| v.to_str()) != Some("toml") {
            continue;
        }
        let Some(name) = path.file_stem().and_then(|v| v.to_str()).map(str::to_owned) else {
            continue;
        };
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let Some(groups) = text.lines().find_map(|line| {
            let (key, value) = line.split_once('=')?;
            (key.trim() == "qq_groups").then(|| value.trim().trim_matches(['[', ']']))
        }) else {
            continue;
        };
        let prompt = text
            .lines()
            .find_map(|line| {
                let (key, value) = line.split_once('=')?;
                (key.trim() == "system_prompt")
                    .then(|| value.trim().trim_matches('"').to_owned())
            })
            .unwrap_or_default();
        lines.push(format!("{name} | {prompt} | {groups}"));
    }
    lines.sort();
    lines.join("\n")
}

fn merge_default_spaces(root: &std::path::Path, explicit: &str, allowed: &str) -> String {
    let mut known = std::collections::HashSet::new();
    for (_, _, groups) in parse_spaces(explicit).unwrap_or_default() {
        known.extend(groups);
    }
    let ledger_path = root.join("memory").join(".space_assignments.json");
    let ledger = std::fs::read_to_string(ledger_path)
        .ok()
        .and_then(|text| serde_json::from_str::<std::collections::HashMap<String, String>>(&text).ok())
        .unwrap_or_default();
    let mut output = explicit.lines().map(str::to_owned).collect::<Vec<_>>();
    for group in parse_groups(allowed).unwrap_or_default() {
        if known.contains(&group) {
            continue;
        }
        let name = ledger
            .get(&group.to_string())
            .cloned()
            .unwrap_or_else(|| format!("space_{group}"));
        output.push(format!("{name} | | {group}"));
        known.insert(group);
    }
    output.join("\n")
}

fn write_spaces(
    root: &std::path::Path,
    spaces: &[(String, String, Vec<i64>)],
) -> Result<(), String> {
    let dir = root.join("config").join("spaces");
    std::fs::create_dir_all(&dir).map_err(|e| format!("无法创建空间配置目录：{e}"))?;
    let names: std::collections::HashSet<&str> = spaces.iter().map(|(name, _, _)| name.as_str()).collect();
    for entry in std::fs::read_dir(&dir).map_err(|e| format!("无法读取空间配置目录：{e}"))? {
        let path = entry.map_err(|e| e.to_string())?.path();
        if path.extension().and_then(|v| v.to_str()) != Some("toml") {
            continue;
        }
        let managed = std::fs::read_to_string(&path)
            .map(|text| text.starts_with("# Managed by Stella installer"))
            .unwrap_or(false);
        let name = path.file_stem().and_then(|v| v.to_str()).unwrap_or_default();
        if managed && !names.contains(name) {
            std::fs::remove_file(path).map_err(|e| format!("无法删除旧空间配置：{e}"))?;
        }
    }
    for (name, prompt, groups) in spaces {
        let path = dir.join(format!("{name}.toml"));
        let prompt = if prompt.is_empty() {
            format!("{name}.md")
        } else {
            prompt.clone()
        };
        let prompt_dir = root.join("system_prompts");
        std::fs::create_dir_all(&prompt_dir).map_err(|e| format!("无法创建人格目录：{e}"))?;
        let prompt_path = prompt_dir.join(&prompt);
        if !prompt_path.is_file() {
            let default = prompt_dir.join("default.md");
            let fallback = root.join("memory").join("SYSTEM.md");
            let source = if default.is_file() { default } else { fallback };
            if source.is_file() {
                std::fs::copy(source, &prompt_path)
                    .map_err(|e| format!("无法复制默认人格：{e}"))?;
            }
        }
        let prompt_line = format!("system_prompt = {}\n", toml_string(&prompt));
        let text = format!("# Managed by Stella installer\n{prompt_line}qq_groups = {:?}\n", groups);
        std::fs::write(path, text).map_err(|e| format!("无法写入空间配置：{e}"))?;
    }
    Ok(())
}

fn apply_advanced_env(
    root: &std::path::Path,
    raw: &str,
    config: &ConfigInput,
    groups: &[i64],
) -> Result<(), String> {
    if raw.trim().is_empty() {
        return Ok(());
    }
    let managed = [
        ("ALLOWED_GROUPS", groups.iter().map(i64::to_string).collect::<Vec<_>>().join(",")),
        ("ONEBOT_ACCESS_TOKEN", config.access_token.clone()),
        ("LM_STUDIO_BASE_URL", config.lm_base_url.clone()),
        ("LM_STUDIO_MODEL", config.chat_model.clone()),
        (
            "CONSOLIDATION_LM_STUDIO_MODEL",
            config.consolidation_model.clone(),
        ),
        ("MEMORY_EMBEDDING_MODEL", config.embedding_model.clone()),
    ];
    let mut replaced = std::collections::HashSet::new();
    let mut onebot_replaced = std::collections::HashSet::new();
    let ws_urls = serde_json::to_string(&parse_list(&config.ws_urls)).unwrap();
    let mut output = Vec::new();
    for line in raw.lines() {
        let trimmed = line.trim_start().trim_start_matches('#').trim_start();
        if let Some((key, value)) = trimmed.split_once('=') {
            if matches!(key.trim(), "HOST" | "PORT" | "ONEBOT_WS_URLS") {
                let key = key.trim();
                if !onebot_replaced.insert(key.to_owned()) {
                    continue;
                }
                match (config.onebot_mode.as_str(), key) {
                    ("reverse", "HOST") => output.push(format!("HOST={}", config.host)),
                    ("reverse", "PORT") => output.push(format!("PORT={}", config.port)),
                    ("reverse", "ONEBOT_WS_URLS") => output.push(format!("# ONEBOT_WS_URLS={value}")),
                    ("forward", "ONEBOT_WS_URLS") => output.push(format!("ONEBOT_WS_URLS={ws_urls}")),
                    ("forward", "HOST") | ("forward", "PORT") => output.push(format!("# {key}={value}")),
                    _ => {}
                }
                continue;
            }
        }
        let mut handled = false;
        for (key, value) in &managed {
            if replaced.contains(key) {
                continue;
            }
            let trimmed = line.trim_start().trim_start_matches('#').trim_start();
            if trimmed.starts_with(&format!("{key}=")) {
                output.push(format!("{key}={value}"));
                replaced.insert(*key);
                handled = true;
                break;
            }
        }
        if !handled {
            output.push(line.to_owned());
        }
    }
    if config.onebot_mode == "reverse" {
        if !onebot_replaced.contains("HOST") {
            output.push(format!("HOST={}", config.host));
        }
        if !onebot_replaced.contains("PORT") {
            output.push(format!("PORT={}", config.port));
        }
    } else if !onebot_replaced.contains("ONEBOT_WS_URLS") {
        output.push(format!("ONEBOT_WS_URLS={ws_urls}"));
    }
    for (key, value) in &managed {
        if !replaced.contains(key) {
            output.push(format!("{key}={value}"));
        }
    }
    std::fs::write(root.join(".env"), format!("{}\n", output.join("\n")))
        .map_err(|e| format!("无法写入高级配置：{e}"))
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
