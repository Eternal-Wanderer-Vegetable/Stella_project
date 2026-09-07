// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! doctor 的渲染层：消费 `deploy doctor --json`（契约见 deploy/report.py），
//! 输出与 Python 端 to_terminal 同语义的彩色报告。字段一律防御式读取——
//! 契约的定义方是 deploy 模块，它加字段时 CLI 不该崩。

use std::io::Write;

use anstyle::Reset;
use anyhow::Result;
use serde_json::Value;

use crate::style;

pub fn render(v: &Value, out: &mut dyn Write) -> Result<()> {
    // 契约应有 items，但防御式读取：上游异常时不让 CLI 崩在这半截
    let empty = Vec::new();
    let items = v.get("items").and_then(Value::as_array).unwrap_or(&empty);

    render_llm(v.get("llm"), out)?;

    for item in items {
        let level = s(item, "level").unwrap_or("ok");
        let (label, st) = match level {
            "error" => ("错误", style::ERROR),
            "warn" => ("警告", style::WARN),
            "info" => ("提示", style::INFO),
            _ => ("通过", style::OK),
        };
        let title = s(item, "title").unwrap_or("(无标题)");
        writeln!(out, "{}[{label}]{} {title}", st.render(), Reset.render())?;
        if let Some(detail) = s(item, "detail").filter(|d| !d.is_empty()) {
            writeln!(out, "    {detail}")?;
        }
        if let Some(hint) = s(item, "fix_hint").filter(|h| !h.is_empty()) {
            writeln!(out, "    解决：{hint}")?;
        }
    }

    writeln!(out)?;
    if let Some(sum) = v.get("summary") {
        let ok = sum.get("ok").and_then(Value::as_i64).unwrap_or_default();
        let warn = sum.get("warn").and_then(Value::as_i64).unwrap_or_default();
        let error = sum.get("error").and_then(Value::as_i64).unwrap_or_default();
        writeln!(
            out,
            "共 {} 项检查：{}{ok} 通过{} / {}{warn} 警告{} / {}{error} 错误{}",
            sum.get("total").and_then(Value::as_i64).unwrap_or_default(),
            style::OK.render(),
            Reset.render(),
            style::WARN.render(),
            Reset.render(),
            style::ERROR.render(),
            Reset.render(),
        )?;
    }
    let blocking = v
        .get("summary")
        .and_then(|s| s.get("blocking"))
        .and_then(Value::as_bool)
        .unwrap_or_else(|| items.iter().any(|i| s(i, "level") == Some("error")));
    if blocking {
        writeln!(
            out,
            "{}发现阻塞性问题，请先解决后再启动。{}",
            style::ERROR.render(),
            Reset.render()
        )?;
    } else {
        writeln!(out, "未发现阻塞性问题。")?;
    }
    Ok(())
}

/// 模型服务事实表（llm 段是「当前生效配置」的事实而非检查结论，deploy/report.py
/// 的设计说明：用户必须能一眼看到角色到底走的哪个端点）。
fn render_llm(llm: Option<&Value>, out: &mut dyn Write) -> Result<()> {
    let Some(llm) = llm.filter(|v| v.is_object()) else {
        return Ok(());
    };
    let roles = llm.get("roles").and_then(Value::as_object);
    let endpoints = llm.get("endpoints").and_then(Value::as_object);
    if roles.map(|r| r.is_empty()).unwrap_or(true)
        && endpoints.map(|e| e.is_empty()).unwrap_or(true)
    {
        return Ok(());
    }

    writeln!(out, "{}模型服务{}", style::TITLE.render(), Reset.render())?;
    if let Some(roles) = roles {
        for (role, rb) in roles {
            let slot = rb
                .get("slot")
                .and_then(Value::as_str)
                .unwrap_or("（未绑定）");
            let model = rb
                .get("model")
                .and_then(Value::as_str)
                .filter(|m| !m.is_empty())
                .unwrap_or("（服务端默认）");
            let gate = rb.get("gate").and_then(Value::as_str).unwrap_or("");
            writeln!(out, "  角色 {role} → {slot} · {model} · 闸门 {gate}")?;
        }
    }
    if let Some(eps) = endpoints {
        for (slot, ep) in eps {
            let url = ep.get("base_url").and_then(Value::as_str).unwrap_or("");
            let kind = ep.get("kind").and_then(Value::as_str).unwrap_or("");
            let key = if ep
                .get("has_api_key")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                "有 key"
            } else {
                "无 key"
            };
            let reach = match ep.get("reachable") {
                Some(Value::Bool(true)) => "可达",
                Some(Value::Bool(false)) => "不可达",
                _ => "未探测",
            };
            writeln!(out, "  端点 {slot}：{url}（{kind}，{key}，{reach}）")?;
        }
    }
    let gate = llm.get("embedding_gate").and_then(Value::as_str);
    if let Some(base) = llm.get("embedding_base_url").and_then(Value::as_str) {
        let g = gate.filter(|g| !g.is_empty()).unwrap_or("none");
        writeln!(out, "  embedding：{base}（闸门 {g}，恒定本地）")?;
    }
    if let Some(usage) = llm.get("usage") {
        if usage.get("accounting").and_then(Value::as_bool) == Some(true) {
            let used = usage
                .get("used_tokens")
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let budget = usage.get("budget").and_then(Value::as_i64).unwrap_or(0);
            let quota = if budget > 0 {
                format!("{used}/{budget} token")
            } else {
                format!("{used} token（预算不限）")
            };
            let totals = usage.get("totals");
            let calls = totals
                .and_then(|t| t.get("calls"))
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let rate = totals
                .and_then(|t| t.get("cache_hit_rate"))
                .and_then(Value::as_f64)
                .unwrap_or(0.0)
                * 100.0;
            writeln!(
                out,
                "  今日用量：{quota}，调用 {calls} 次，缓存命中率 {rate:.1}%"
            )?;
        }
    }
    writeln!(out)?;
    Ok(())
}

fn s<'a>(v: &'a Value, key: &str) -> Option<&'a str> {
    v.get(key).and_then(Value::as_str)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 渲染目标包一层 AutoStream(ColorChoice::Never)：与生产路径（anstream::stdout()）
    /// 一致地剥离 ANSI，断言可以直接落在纯文本上。
    fn render_to_string(v: &Value) -> String {
        let mut buf = anstream::AutoStream::new(Vec::<u8>::new(), anstream::ColorChoice::Never);
        render(v, &mut buf).unwrap();
        let inner = buf.into_inner();
        String::from_utf8(inner).unwrap()
    }

    #[test]
    fn renders_items_and_blocking_banner() {
        let v: Value = serde_json::json!({
            "summary": {"ok": 3, "warn": 1, "error": 1, "blocking": true, "total": 5},
            "items": [
                {"id": "x", "level": "error", "title": "缺少 .env", "detail": "没找到", "fix_hint": "跑 deploy init"},
                {"id": "y", "level": "warn", "title": "缓存未启用", "detail": "", "fix_hint": ""},
                {"id": "z", "level": "ok", "title": "Python 可用", "detail": "3.12", "fix_hint": ""}
            ]
        });
        let text = render_to_string(&v);
        assert!(text.contains("[错误] 缺少 .env"));
        assert!(text.contains("解决：跑 deploy init"));
        assert!(text.contains("[警告] 缓存未启用"));
        assert!(text.contains("[通过] Python 可用"));
        assert!(text.contains("发现阻塞性问题"));
        assert!(text.contains("3 通过 / 1 警告 / 1 错误"));
    }

    #[test]
    fn missing_llm_section_is_silent() {
        let v: Value = serde_json::json!({"summary": {"blocking": false, "total": 1},
            "items": [{"id": "a", "level": "ok", "title": "t", "detail": "", "fix_hint": ""}]});
        let text = render_to_string(&v);
        assert!(!text.contains("模型服务"));
        assert!(text.contains("未发现阻塞性问题"));
    }

    #[test]
    fn anstream_strip_is_attached_in_tests() {
        // AutoStream 在非终端时剥离 ANSI——渲染函数里混着样式码也能拿到纯文本，
        // 上面的断言依赖这个行为；此用例显式钉住该前提。
        let mut buf = anstream::AutoStream::new(Vec::<u8>::new(), anstream::ColorChoice::Auto);
        write!(buf, "\x1b[31mred\x1b[0m").unwrap();
        let inner = buf.into_inner();
        assert_eq!(String::from_utf8(inner).unwrap(), "red");
    }
}
