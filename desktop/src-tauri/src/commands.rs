//! Tauri command 层。函数体只做「调 python + 转 JSON」，不含业务逻辑。

use crate::python;
use serde::Deserialize;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

/// 环境自检。返回 `deploy doctor --json` 的原始 JSON 字符串。
///
/// 返回 String 而非 serde_json::Value：前端拿到就 JSON.parse，中间再解析一遍
/// 是多余的开销，且会丢掉 Python 侧的字段顺序（对调试友好）。
///
/// doctor 的退出码 1 表示「发现阻塞性问题」，不是调用失败——这里必须放行，
/// 否则有 error 时前端会收到错误而不是检查结果。
/// 在线面板的基地址：HOST/PORT 读自 STELLA_HOME/.env（0.0.0.0 → 127.0.0.1）。
fn live_base_url() -> String {
    let path = python::data_root().join(".env");
    let values = std::fs::read_to_string(&path)
        .map(|text| parse_env(&text))
        .unwrap_or_default();
    let host = values.get("HOST").cloned().unwrap_or_else(|| "127.0.0.1".into());
    let port = values.get("PORT").cloned().unwrap_or_else(|| "8080".into());
    let host = if host == "0.0.0.0" || host == "::" {
        "127.0.0.1".to_string()
    } else {
        host
    };
    format!("http://{host}:{port}")
}

/// 轮询状态接口直到 Bot 就绪（或超时），返回在线面板基地址。
///
/// 离线页的「启动 Bot」按钮走完 start_bot 后调用它：就绪即把 WebView 导航到
/// 在线面板（由 Bot 同端口托管，登录态存在该源下可跨壳重启保留）。
#[tauri::command]
pub async fn wait_bot_ready(timeout_secs: Option<u64>) -> Result<String, String> {
    let timeout = timeout_secs.unwrap_or(120).max(1);
    tauri::async_runtime::spawn_blocking(move || {
        let base = live_base_url();
        let status_url = format!("{base}/stella/status");
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout);
        loop {
            // 状态接口 200 = Bot 进程活着且 WebUI 已挂载
            if ureq::get(&status_url)
                .timeout(std::time::Duration::from_secs(1))
                .call()
                .is_ok()
            {
                return Ok(base);
            }
            if std::time::Instant::now() >= deadline {
                return Err(format!("等待 Bot 就绪超时（{timeout}s）。请查看日志排查。"));
            }
            std::thread::sleep(std::time::Duration::from_millis(800));
        }
    })
    .await
    .map_err(|e| format!("等待任务失败：{e}"))?
}

#[tauri::command]
pub fn desktop_session_secret() -> String {
    // 供打包进壳的 dashboard 在 tauri:// 源下换取正式 JWT（方案 §4 D5）；
    // 秘钥本身只在壳与 Bot 子进程环境之间传递，不落盘。
    crate::desktop_session_secret().to_string()
}

#[tauri::command]
pub async fn run_doctor() -> Result<String, String> {
    let runtime =
        tauri::async_runtime::spawn_blocking(|| try_runtime_operation("doctor", false, true))
            .await
            .map_err(|e| format!("Runtime 自检任务未能完成：{e}"))?;
    if let Some((envelope, _stdout, stderr, code)) = runtime {
        if let Some(data) = envelope.get("data") {
            return serde_json::to_string(data)
                .map_err(|e| format!("Runtime doctor 结果无效：{e}"));
        }
        return Err(runtime_failure(
            &envelope,
            &format!("Runtime doctor 异常退出（code {code}）：{stderr}"),
        ));
    }
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
    let runtime =
        tauri::async_runtime::spawn_blocking(|| try_runtime_operation("status", false, true))
            .await
            .map_err(|e| format!("Runtime 状态任务未能完成：{e}"))?;
    if let Some((envelope, _stdout, stderr, code)) = runtime {
        if let Some(data) = envelope.get("data") {
            return serde_json::to_string(data)
                .map_err(|e| format!("Runtime status 结果无效：{e}"));
        }
        return Err(runtime_failure(
            &envelope,
            &format!("Runtime status 异常退出（code {code}）：{stderr}"),
        ));
    }
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
    let runtime = tauri::async_runtime::spawn_blocking(move || {
        try_runtime_operation("start", force, true)
    })
    .await
    .map_err(|e| format!("Runtime 启动任务未能完成：{e}"))?;
    if let Some((envelope, _stdout, stderr, code)) = runtime {
        if !envelope
            .get("ok")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
        {
            return Err(runtime_failure(
                &envelope,
                &format!("Runtime 启动异常退出（code {code}）：{stderr}"),
            ));
        }
        return Ok(runtime_message(&envelope));
    }
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

/// 停止 Stella。对应 `deploy stop` / runtime stop，可能等待在途任务收尾。
///
/// 不设「Bot 是否由本 GUI 进程启动」的门卫：Bot 是 detach 的常驻进程，GUI
/// 重启后进程内记忆即丢失；若据此拒绝停止，关闭窗口就会留下孤儿 Bot 占住
/// 服务端口（2026-09-24 实测：上次会话的 Bot 存活，GUI 关闭后 8080 一直
/// 被占）。跨安装的安全边界由 Python 侧 ownership 校验把守——instance_id /
/// project_root / launch_token 不匹配（别的安装或手工启动的进程）时
/// `deploy stop` 会拒绝，宁可不动也不误杀。
#[tauri::command]
pub async fn stop_bot() -> Result<String, String> {
    let runtime =
        tauri::async_runtime::spawn_blocking(|| try_runtime_operation("stop", false, false))
            .await
            .map_err(|e| format!("Runtime 停止任务未能完成：{e}"))?;
    if let Some((envelope, _stdout, stderr, code)) = runtime {
        if !envelope
            .get("ok")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
        {
            return Err(runtime_failure(
                &envelope,
                &format!("Runtime 停止异常退出（code {code}）：{stderr}"),
            ));
        }
        return Ok(runtime_message(&envelope));
    }
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
        let path = python::data_root().join(".env");
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
        // 卡片值优先读新键；没走过迁移的旧 .env 只有旧键，回落读取保证显示连续。
        let get2 = |key: &str, legacy: &str, fallback: &str| {
            values
                .get(key)
                .cloned()
                .or_else(|| values.get(legacy).cloned())
                .unwrap_or_else(|| fallback.to_owned())
        };
        // 「配置过了没有」不能只看本机模型：纯在线部署（角色全绑在线端点）根本
        // 不需要填本机模型 ID，只认它会把这类用户永久判成「未配置」，
        // index.html 于是每次启动都把人送回向导。对话角色填了模型就算配过。
        // LM_STUDIO_MODEL 是旧键（SUPERSEDED），未迁移的 .env 里可能只有它。
        let empty = String::new();
        let configured = path.is_file()
            && (!values.get("LLM_ENDPOINT_LOCAL_MODEL").unwrap_or(&empty).is_empty()
                || !values.get("LM_STUDIO_MODEL").unwrap_or(&empty).is_empty()
                || !values.get("LLM_ROLE_CHAT_MODEL").unwrap_or(&empty).is_empty());
        let ws_urls = values
            .get("ONEBOT_WS_URLS")
            .map(|raw| {
                serde_json::from_str::<Vec<String>>(raw)
                    .map(|urls| urls.join(","))
                    .unwrap_or_else(|_| raw.clone())
            })
            .unwrap_or_default();
        let root = python::data_root();
        let mut spaces = read_spaces(&root);
        let allowed_groups = values.get("ALLOWED_GROUPS").cloned().unwrap_or_default();
        spaces = merge_default_spaces(&root, &spaces, &allowed_groups);
        // .env 在用户数据目录，模板 .env.example 随发布包在程序目录
        let advanced_env = std::fs::read_to_string(root.join(".env"))
            .or_else(|_| std::fs::read_to_string(python::project_root().join(".env.example")))
            .unwrap_or_default();
        serde_json::to_string(&serde_json::json!({
            "configured": configured,
            "allowed_groups": values.get("ALLOWED_GROUPS").cloned().unwrap_or_default(),
            "onebot_mode": if ws_urls.is_empty() { "reverse" } else { "forward" },
            "host": get("HOST", "0.0.0.0"),
            "port": get("PORT", "8080").parse::<u16>().unwrap_or(8080),
            "ws_urls": ws_urls,
            "access_token": get("ONEBOT_ACCESS_TOKEN", ""),
            "lm_base_url": get2("LLM_ENDPOINT_LOCAL_BASE_URL", "LM_STUDIO_BASE_URL", "http://127.0.0.1:1234"),
            "chat_model": get2("LLM_ENDPOINT_LOCAL_MODEL", "LM_STUDIO_MODEL", ""),
            "consolidation_model": get2("LLM_ROLE_CONSOLIDATION_MODEL", "CONSOLIDATION_LM_STUDIO_MODEL", ""),
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
        let answers_path = python::project_root().join(".stella-installer.answers.toml");
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
        // parse_spaces 放行空群组的空间后，这里的兜底校验不能再省：所有空间都没绑
        // 群、允许群号也空着，写出的 ALLOWED_GROUPS 为空等于谁都不允许。
        if groups.is_empty() {
            return Err("至少给一个空间绑定群号，或填写允许的群号列表".to_owned());
        }
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
        // init 会在首次运行时 mkdir 数据目录并写指针文件——数据目录的位置可能刚刚才
        // 确定下来。必须先失效缓存再取 root，否则下面的空间配置与高级 .env 会被写进
        // init 之前的旧位置（用户看到的是「保存成功，但设置没生效」）。
        python::invalidate_data_root();
        let (stdout, stderr, code) = result?;
        if code != 0 {
            return Err(if stderr.trim().is_empty() { stdout } else { stderr });
        }
        let root = python::data_root();
        write_spaces(&root, &spaces)?;
        apply_advanced_env(&root, &config.advanced_env, &config, &groups)?;
        Ok(stdout)
    })
    .await
    .map_err(|e| format!("保存配置任务未能完成：{e}"))?
}

/// 从任意 OpenAI 兼容端点读取模型列表（本机 LM Studio 与在线服务商共用一条路径）。
///
/// `api_key` 可空：本机 LM Studio 通常不校验，在线端点必填——所以带 key 时挂
/// `Authorization: Bearer`，不带就照旧发裸请求。**key 只作为请求头用掉，不落盘、
/// 不进任何返回值**，错误信息里也只说 HTTP 状态码而不回显 key（报告与日志都可能
/// 被贴进 issue）。
#[tauri::command]
pub async fn list_models(base_url: String, api_key: Option<String>) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let url = format!("{}/v1/models", base_url.trim_end_matches('/'));
        // 在线服务商跨公网，5 秒会在正常网络下就误报「连不上」
        let mut request = ureq::get(&url).timeout(std::time::Duration::from_secs(10));
        if let Some(key) = api_key.as_deref().map(str::trim).filter(|k| !k.is_empty()) {
            request = request.set("Authorization", &format!("Bearer {key}"));
        }
        let response = request.call().map_err(|e| match e {
            ureq::Error::Status(code @ (401 | 403), _) => {
                format!("端点拒绝了这把 API key（HTTP {code}）：检查 key 是否填对、账户是否可用。")
            }
            ureq::Error::Status(404, _) => {
                "端点没有 /v1/models（HTTP 404）：地址应填服务根地址，不要带 /v1。".to_owned()
            }
            ureq::Error::Status(code, _) => format!("端点返回 HTTP {code}。"),
            other => format!("无法连接端点：{other}"),
        })?;
        let mut body = String::new();
        response
            .into_reader()
            .read_to_string(&mut body)
            .map_err(|e| format!("读取端点响应失败：{e}"))?;
        let data: serde_json::Value = serde_json::from_str(&body)
            .map_err(|e| format!("端点返回数据无效：{e}"))?;
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
        let root = python::data_root();
        let program = python::project_root();
        // 兜底人格随发布包出厂，始终在程序目录
        let fallback_path = program.join("memory").join("SYSTEM.md");
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
            // 用户改过的人格在数据目录，发布包自带的默认人格在程序目录：用户的优先
            let custom_path = if prompt.is_empty() {
                None
            } else {
                let in_data = root.join("system_prompts").join(&prompt);
                if in_data.is_file() {
                    Some(in_data)
                } else {
                    Some(program.join("system_prompts").join(&prompt))
                }
            };
            let custom = custom_path
                .as_ref()
                .filter(|path| path.is_file())
                .and_then(|path| std::fs::read_to_string(path).ok())
                // 只建了空间、还没写正文的空 md 不算自定义人格：按默认人格展示。
                // 否则 0 字节文件会把编辑器顶成空白，还标成「当前使用自定义人格」
                // （2026-09-20 实测）。
                .filter(|text| !text.trim().is_empty());
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
    groups: Option<Vec<i64>>,
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
        let root = python::data_root();
        let dir = root.join("system_prompts");
        std::fs::create_dir_all(&dir).map_err(|e| format!("无法创建人格目录：{e}"))?;
        // 正文留空保存 = 用默认人格覆盖：空 md 文件只会得到「空白自定义人格」，
        // 聊天侧等于没有人格。默认人格与 get_personas 的回退同源（程序目录
        // memory/SYSTEM.md）；默认文件缺失时按原文写入，展示层会把空文件当回退。
        let content = if content.trim().is_empty() {
            std::fs::read_to_string(python::project_root().join("memory").join("SYSTEM.md"))
                .unwrap_or(content)
        } else {
            content
        };
        std::fs::write(dir.join(&file), content).map_err(|e| format!("无法保存人格：{e}"))?;
        let spaces_dir = root.join("config").join("spaces");
        std::fs::create_dir_all(&spaces_dir).map_err(|e| format!("无法创建空间目录：{e}"))?;
        let space_path = spaces_dir.join(format!("{space}.toml"));
        let old = std::fs::read_to_string(&space_path).unwrap_or_else(|_| "qq_groups = []\n".to_owned());
        // 「保存人格」保存的是整张卡片：正文写 system_prompts，群号写 qq_groups。
        // 群号不随卡片保存的话，用户在卡片里填的群号会在重新拉取后悄悄退回旧值
        // （2026-09-20 实测）。groups 传 None 时保留旧值（兼容旧前端调用）。
        let mut output = Vec::new();
        let mut replaced_prompt = false;
        let mut replaced_groups = false;
        for line in old.lines() {
            let key = line.trim_start();
            if key.starts_with("system_prompt") {
                if !replaced_prompt {
                    output.push(format!("system_prompt = {}", toml_string(&file)));
                    replaced_prompt = true;
                }
            } else if key.starts_with("qq_groups") {
                if let Some(groups) = &groups {
                    if !replaced_groups {
                        let joined = groups.iter().map(|value| value.to_string()).collect::<Vec<_>>().join(", ");
                        output.push(format!("qq_groups = [{joined}]"));
                        replaced_groups = true;
                    }
                } else {
                    output.push(line.to_owned());
                }
            } else {
                output.push(line.to_owned());
            }
        }
        if !replaced_prompt {
            output.push(format!("system_prompt = {}", toml_string(&file)));
        }
        if let Some(groups) = &groups {
            if !replaced_groups {
                let joined = groups.iter().map(|value| value.to_string()).collect::<Vec<_>>().join(", ");
                output.push(format!("qq_groups = [{joined}]"));
            }
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
        let root = python::data_root();
        let path = resolve_log_path(&root, path.as_deref())?;
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

/// Windows 的 canonicalize 产出 `\\?\E:\...` 扩展前缀路径，而 status 载荷里的
/// 日志路径是普通前缀——同一目录两种写法直接做 `starts_with` 会互相误判
/// （2026-09-20 实测：日志目录尚不存在时普通路径被判成越界）。统一剥掉前缀。
fn canonical_plain(path: &Path) -> std::io::Result<PathBuf> {
    let canonical = std::fs::canonicalize(path)?;
    let text = canonical.as_os_str().to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        Ok(PathBuf::from(format!(r"\\{rest}")))
    } else if let Some(rest) = text.strip_prefix(r"\\?\") {
        Ok(PathBuf::from(rest))
    } else {
        Ok(canonical)
    }
}

/// Resolve a GUI-provided log path without allowing reads outside STELLA_HOME.
///
/// Runtime component paths are relative to the same data root, while the legacy
/// status payload may still provide an absolute `STELLA_JSON_LOG_PATH`. Existing
/// files are canonicalized so symlinked paths cannot escape the root; missing
/// files keep their parent anchored so a not-yet-created component log remains a
/// normal empty result. All comparisons happen on the de-verbified form (see
/// `canonical_plain`).
fn resolve_log_path(root: &Path, requested: Option<&str>) -> Result<PathBuf, String> {
    let root = canonical_plain(root)
        .map_err(|error| format!("无法定位 Stella 数据目录：{error}"))?;
    let raw = requested
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| root.join("logs").join("stella.jsonl"));
    let candidate = if raw.is_absolute() {
        raw
    } else {
        root.join(raw)
    };

    let resolved = match canonical_plain(&candidate) {
        Ok(path) => path,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            let parent = candidate
                .parent()
                .ok_or_else(|| "日志路径缺少父目录".to_owned())?;
            match canonical_plain(parent) {
                Ok(parent) => {
                    let name = candidate
                        .file_name()
                        .ok_or_else(|| "日志路径缺少文件名".to_owned())?;
                    parent.join(name)
                }
                // 日志目录本身也不存在（全新数据目录、Bot 首次启动前）：candidate
                // 要么由验证过的 root 拼出、要么是载荷里的绝对路径（下方统一做越界
                // 检查）。返回原样即可——read_log_tail 对不存在的文件返回空日志。
                Err(not_found) if not_found.kind() == std::io::ErrorKind::NotFound => candidate,
                Err(parent_error) => {
                    return Err(format!("无法定位日志目录：{parent_error}"))
                }
            }
        }
        Err(error) => return Err(format!("无法解析日志路径：{error}")),
    };

    if !resolved.starts_with(&root) || resolved == root {
        return Err("日志路径必须位于 Stella 数据目录内".to_owned());
    }
    Ok(resolved)
}

/// 从旧版本安装目录导入用户数据。对应 `deploy migrate`。
///
/// 返回的是 Markdown 报告原文（不是 JSON）：这份报告同时会被写成
/// `migration_report.md` 给用户留档，两处内容必须一致，所以只生成一次。
///
/// `dry_run` 既是预览也是探测：找不到旧目录时 Python 侧以 code 1 返回，报告里
/// 写明原因。code 0/1 都是「有结论」，其余才是异常（Python 崩了等）。
#[tauri::command]
pub async fn run_migrate(source: Option<String>, dry_run: bool) -> Result<String, String> {
    let (stdout, stderr, code) = tauri::async_runtime::spawn_blocking(move || {
        let mut args: Vec<String> = vec!["migrate".to_owned()];
        if let Some(dir) = source.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            args.push("--from".to_owned());
            args.push(dir.to_owned());
        }
        if dry_run {
            args.push("--dry-run".to_owned());
        }
        let borrowed: Vec<&str> = args.iter().map(String::as_str).collect();
        let result = python::run_deploy(&borrowed);
        // deploy migrate（非预演）会 mkdir 数据目录并写指针文件，也就是**改变了
        // data_root 的答案**。不在这里失效缓存，后续 get_config / save_config 会继续
        // 读写导入之前的旧位置——v3.1.0 的「导入成功但配置是空的」就是这么来的。
        // 预演不落盘，但失效一次也无害（顶多多跑一次 deploy paths）。
        python::invalidate_data_root();
        result
    })
    .await
    .map_err(|e| format!("导入任务未能完成：{e}"))??;
    if code != 0 && code != 1 {
        return Err(format!(
            "deploy migrate 异常退出（code {code}）：\n{}",
            if stderr.trim().is_empty() { stdout.clone() } else { stderr }
        ));
    }
    if stdout.trim().is_empty() {
        return Err(format!("deploy migrate 没有输出报告。\nstderr: {stderr}"));
    }
    Ok(stdout)
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
        // 空群组必须放行：「创建人格空间」就是先建空间、后绑群号的流程，
        // save_persona 给新空间写的默认 toml 就是 `qq_groups = []`。这里若沿
        // 用 parse_groups 的「至少一个群号」校验，一个没绑群的空间会让整个
        // parse_spaces 报错、get_personas 吞成空列表——所有空间一起消失
        // （2026-09-20 实测）。非空的非法值（乱码、非正整数）仍然报错。
        let groups = if groups.trim().is_empty() {
            Vec::new()
        } else {
            parse_groups(groups)?
        };
        result.push((name.to_owned(), prompt.to_owned(), groups));
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
        // 卡片写新键（2026-09-18 起）：LM_STUDIO_* 已 SUPERSEDED，强写清单若
        // 继续生产旧键，迁移就永远走不完。旧 .env 里遗留的旧键行由保存前半段
        // 的 deploy init --force 合并迁移负责移除。
        (
            "LLM_ENDPOINT_LOCAL_BASE_URL",
            config.lm_base_url.clone(),
        ),
        ("LLM_ENDPOINT_LOCAL_MODEL", config.chat_model.clone()),
        (
            "LLM_ROLE_CONSOLIDATION_MODEL",
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

/// 只有完整且 operation 匹配的 envelope 才能启用 Runtime 路径。
///
/// 旧版 Python 没有 `runtime` 子命令，argparse 错误不会带 envelope；这时
/// 返回 None，调用方才会走 legacy deploy fallback。Runtime 自身的失败结果
/// 仍然是合法 envelope，不能被误判成「不可用」。
fn try_runtime_operation(
    operation: &str,
    force: bool,
    prepare: bool,
) -> Option<(serde_json::Value, String, String, i32)> {
    let (stdout, stderr, code) =
        python::run_runtime_operation(operation, "stella", None, force, prepare).ok()?;
    let value: serde_json::Value = serde_json::from_str(extract_json(&stdout)?).ok()?;
    if value.get("operation").and_then(serde_json::Value::as_str) != Some(operation) {
        return None;
    }
    Some((value, stdout, stderr, code))
}

fn runtime_message(envelope: &serde_json::Value) -> String {
    envelope
        .get("message")
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .or_else(|| {
            envelope
                .get("data")
                .and_then(|data| serde_json::to_string(data).ok())
        })
        .unwrap_or_default()
}

fn runtime_failure(envelope: &serde_json::Value, fallback: &str) -> String {
    let message = envelope
        .get("error")
        .and_then(|error| error.get("message"))
        .and_then(serde_json::Value::as_str)
        .filter(|message| !message.is_empty());
    match message {
        Some(message) => message.to_owned(),
        None => fallback.to_owned(),
    }
}

#[cfg(test)]
mod tests {
    use super::{canonical_plain, extract_json, resolve_log_path, runtime_failure, runtime_message};
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_root(label: &str) -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "stella-tauri-log-{label}-{}-{stamp}",
            std::process::id()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    #[test]
    fn runtime_envelope_parser_requires_matching_operation() {
        let stdout = r#"warning
{"ok":true,"operation":"status","component":"stella","data":{"alive":false}}"#;
        let parsed: serde_json::Value =
            serde_json::from_str(extract_json(stdout).unwrap()).unwrap();
        assert_eq!(
            parsed.get("operation").and_then(serde_json::Value::as_str),
            Some("status")
        );
    }

    #[test]
    fn runtime_message_prefers_legacy_compatible_message() {
        let envelope = serde_json::json!({
            "ok": true,
            "operation": "start",
            "message": "started"
        });
        assert_eq!(runtime_message(&envelope), "started");
    }

    #[test]
    fn runtime_failure_prefers_structured_error() {
        let envelope = serde_json::json!({
            "ok": false,
            "error": {"code": "operation_failed", "message": "启动失败"}
        });
        assert_eq!(runtime_failure(&envelope, "fallback"), "启动失败");
    }

    #[test]
    fn log_path_defaults_inside_data_root() {
        let root = test_root("default");
        let logs = root.join("logs");
        fs::create_dir_all(&logs).unwrap();

        let path = resolve_log_path(&root, None).unwrap();

        // resolve_log_path 返回去扩展前缀的普通形态（见 canonical_plain）
        assert_eq!(path, canonical_plain(&logs).unwrap().join("stella.jsonl"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn log_path_tolerates_missing_logs_dir() {
        // 全新数据目录：logs/ 还没建（Bot 首次启动前）。必须正常解析且落在 root 内，
        // read_log_tail 对不存在的文件返回空日志——不能把「还没有日志」报成错误。
        let root = test_root("fresh");

        let path = resolve_log_path(&root, None).unwrap();

        // 候选锚定在 canonicalize 之后的 root 上（8.3 短路径会被展开为完整形式）
        let expected_root = canonical_plain(&root).unwrap();
        assert_eq!(path, expected_root.join("logs").join("stella.jsonl"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn log_path_accepts_runtime_relative_path() {
        let root = test_root("runtime");
        let logs = root.join("runtime").join("logs");
        fs::create_dir_all(&logs).unwrap();

        let path = resolve_log_path(&root, Some("runtime/logs/onebot.log")).unwrap();

        assert_eq!(path, canonical_plain(&logs).unwrap().join("onebot.log"));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn log_path_rejects_escape_from_data_root() {
        let root = test_root("escape");
        let outside = root.parent().unwrap().join("stella-tauri-outside.log");
        fs::write(&outside, "secret").unwrap();

        let result = resolve_log_path(&root, Some("../stella-tauri-outside.log"));

        assert!(result.is_err());
        let _ = fs::remove_file(outside);
        let _ = fs::remove_dir_all(root);
    }

    /// 关闭窗口时的停止不得设「Bot 是否由本 GUI 进程启动」的进程内门卫。
    ///
    /// Bot 是 detach 的常驻进程，GUI 重启后进程内标志即丢失；曾经的进程内
    /// 门卫让「上次会话留下的 Bot」在关窗时被有意跳过，孤儿进程一直占着
    /// 服务端口（2026-09-24 实测）。跨安装安全由 Python 侧 ownership 校验
    /// 把守，Rust 侧不再重复一道会误伤的防线。
    #[test]
    fn stop_bot_has_no_process_local_ownership_gate() {
        let src = fs::read_to_string(Path::new(file!())).expect("无法读取 commands.rs");
        // 旧门卫的静态名。拆开拼接以免本测试的源码自身包含该字面量。
        let legacy_flag = format!("GUI_{}{}", "OWNS", "_BOT");
        assert!(
            !src.contains(&legacy_flag),
            "stop_bot 不得用进程内标志决定是否停止 Bot——GUI 重启后该标志丢失，\
             关窗会留下孤儿 Bot 占住端口"
        );
        assert!(
            src.contains("pub async fn stop_bot"),
            "stop_bot 命令必须仍然存在"
        );
    }

    /// 关闭窗口时停止失败也必须销毁窗口：失败分支几乎总是「Bot 不归本安装
    /// 管」（deploy stop 的 ownership 校验拒绝），此时扣住窗口等于把用户锁在
    /// 关不掉的界面外。本测试防止将来把「失败即不开窗」的老语义加回来。
    #[test]
    fn window_close_destroys_even_when_stop_fails() {
        let lib_src =
            fs::read_to_string(Path::new(file!()).with_file_name("lib.rs")).expect("无法读取 lib.rs");
        let close_handler = lib_src
            .find("CloseRequested")
            .map(|at| &lib_src[at..])
            .expect("lib.rs 必须处理 CloseRequested");
        let emit_at = close_handler
            .find("close-failed")
            .expect("关闭路径必须发出 close-failed 事件供前端感知");
        let destroy_at = close_handler
            .find("window.destroy()")
            .expect("关闭路径必须销毁窗口");
        assert!(
            emit_at < destroy_at,
            "close-failed 事件必须先于销毁窗口发出"
        );
        assert!(
            !close_handler[emit_at..destroy_at].contains("return;"),
            "停止失败不得提前返回跳过 window.destroy()——窗口必须照常关闭"
        );
    }
}
