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
    if code != 0 && code != 1 {
        let detail = if stderr.trim().is_empty() { stdout } else { stderr };
        return Err(format!("deploy doctor 异常退出（code={code}）:\n{detail}"));
    }
    // Python 的 warning 也可能打进 stdout（虽通常走 stderr）。保险做法是
    // 提取第一个 `{` 到最后一个 `}` 的片段，避免 JSON 前混入杂音导致解析失败。
    // 与 memory/consolidator 的 _parse_json 容错思路同源。
    match extract_json(&stdout) {
        Some(json) => Ok(json),
        None => Err(format!("deploy doctor 输出不是合法 JSON:\n{stdout}")),
    }
}

/// 从文本中提取第一个 `{` 到最后一个 `}` 之间的片段。
fn extract_json(text: &str) -> Option<String> {
    let start = text.find('{')?;
    let end = text.rfind('}')?;
    if end < start {
        return None;
    }
    Some(text[start..=end].to_string())
}
