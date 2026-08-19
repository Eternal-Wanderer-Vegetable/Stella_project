//! Tauri command 层。函数体只做「调 python + 转 JSON」，不含业务逻辑。

use crate::python;

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
