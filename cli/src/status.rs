// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! status 的渲染层与 docker 形态的状态聚合。
//!
//! 本地形态：消费 `deploy status --json`（契约见 deploy/process.py 的 status()）。
//! docker 形态：compose 容器状态（docker inspect）+ 容器内状态接口
//! （`docker exec ... curl`——接口只接受容器回环，宿主机直连必 403）。
//! 两种形态共用 render_inner（字段来自进程内状态接口，link 的字段有
//! **显式 null** 语义，见 extensions/link_monitor 的契约说明，不能当缺省值处理）。

use std::io::Write;

use anstyle::Reset;
use anyhow::Result;
use serde_json::{json, Value};

use crate::ctx::Ctx;
use crate::runner;
use crate::style;

/// 本地形态：渲染 `deploy status --json` 的结果。
pub fn render_local(v: &Value, root: &std::path::Path, out: &mut dyn Write) -> Result<()> {
    writeln!(
        out,
        "形态：{}（项目根 {}）",
        crate::ctx::Mode::Local.label(),
        root.display()
    )?;
    let alive = v.get("alive").and_then(Value::as_bool).unwrap_or(false);
    let pid = v.get("pid").and_then(Value::as_i64);
    let api_ok = v
        .get("api_reachable")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if alive {
        let pid_text = pid
            .map(|p| format!("PID {p}"))
            .unwrap_or_else(|| "PID 未知".into());
        let api_text = if api_ok {
            "状态接口可达"
        } else {
            "状态接口不可达（可能刚启动，或已关闭状态接口）"
        };
        writeln!(
            out,
            "{}● 运行中{}（{pid_text}，{api_text}）",
            style::OK.render(),
            Reset.render()
        )?;
    } else {
        writeln!(out, "{}○ 未运行{}", style::DIM.render(), Reset.render())?;
    }
    render_inner(v, out)
}

/// docker 形态：聚合容器状态与容器内状态接口。
pub fn docker_status(ctx: &Ctx, as_json: bool, out: &mut dyn Write) -> Result<i32> {
    let stella_state = inspect_state(ctx, "stella");
    let stella_health = inspect_health(ctx, "stella");
    let napcat_state = inspect_state(ctx, "napcat");
    let inner = exec_status(ctx);

    if as_json {
        let doc = json!({
            "mode": "docker",
            "stella": {"state": stella_state, "health": stella_health},
            "napcat": {"state": napcat_state},
            "inner": inner,
        });
        writeln!(out, "{}", serde_json::to_string_pretty(&doc)?)?;
        return Ok(0);
    }

    writeln!(
        out,
        "形态：{}（项目根 {}）",
        ctx.mode.label(),
        ctx.root.display()
    )?;
    match &stella_state {
        Some(state) => {
            let health = stella_health.as_deref().unwrap_or("");
            let health_text = if health.is_empty() {
                String::new()
            } else {
                format!("（健康检查 {health}）")
            };
            writeln!(out, "stella 容器：{state}{health_text}")?;
        }
        None => writeln!(
            out,
            "{}stella 容器：未创建（先 stellacli start）{}",
            style::WARN.render(),
            Reset.render()
        )?,
    }
    match &napcat_state {
        Some(state) => writeln!(out, "napcat 容器：{state}")?,
        None => writeln!(out, "napcat 容器：未部署")?,
    }
    match inner {
        Some(v) => render_inner(&v, out)?,
        None => writeln!(
            out,
            "{}容器内状态接口不可达（容器没起，或 HTTP 未就绪）{}",
            style::DIM.render(),
            Reset.render()
        )?,
    }
    Ok(0)
}

/// 进程内状态字段的公共渲染（本地 status 与 docker exec 共用同一接口形状）。
fn render_inner(v: &Value, out: &mut dyn Write) -> Result<()> {
    if let Some(secs) = v.get("uptime_seconds").and_then(Value::as_f64) {
        if secs >= 0.0 {
            writeln!(out, "运行时长：{}", fmt_duration(secs as i64))?;
        }
    }
    render_runtime(v.get("runtime"), out)?;
    if let Some(link) = v.get("link").filter(|l| l.is_object()) {
        let enabled = link
            .get("enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        if !enabled {
            writeln!(out, "链路（NapCat）：监控未启用")?;
        } else {
            let healthy = link
                .get("healthy")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let connected = link
                .get("connected")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            // connected_seconds / last_event_seconds_ago 未连接时是显式 null（键在、值为 null），
            // 不能拿缺省 0 去格式化——按契约语义分别处理。
            let conn_secs = link.get("connected_seconds").and_then(Value::as_f64);
            let last_event = link.get("last_event_seconds_ago").and_then(Value::as_f64);
            let text = if healthy {
                match conn_secs {
                    Some(s) => format!("健康（已连接 {}）", fmt_duration(s as i64)),
                    None => "健康".to_string(),
                }
            } else if connected {
                "已连接但事件不新鲜（NapCat 可能掉线）".to_string()
            } else {
                "未连接（NapCat 未接入或反向 WS 未配）".to_string()
            };
            let _ = last_event; // 保留字段：面板求精简，事件新鲜度已体现在 healthy 判定里
            writeln!(out, "链路（NapCat）：{text}")?;
        }
    }
    if let Some(waiting) = scheduler_waiting_summary(v.get("scheduler")) {
        writeln!(out, "调度器：{waiting}")?;
    }
    if let Some(usage) = v.get("usage").filter(|u| u.is_object()) {
        if usage.get("accounting").and_then(Value::as_bool) == Some(true) {
            let used = usage
                .get("used_tokens")
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let budget = usage.get("budget").and_then(Value::as_i64).unwrap_or(0);
            let calls = usage
                .get("totals")
                .and_then(|t| t.get("calls"))
                .and_then(Value::as_i64)
                .unwrap_or(0);
            let quota = if budget > 0 {
                format!("{used}/{budget}")
            } else {
                format!("{used}（不限）")
            };
            writeln!(out, "今日用量：{quota} token，{calls} 次调用")?;
        }
    }
    if let Some(caps) = v.get("capabilities") {
        if let Some(arr) = caps.as_array() {
            writeln!(
                out,
                "能力：{} 项（明细：stellacli capabilities）",
                arr.len()
            )?;
        }
    }
    Ok(())
}

fn render_runtime(runtime: Option<&Value>, out: &mut dyn Write) -> Result<()> {
    let Some(components) = runtime
        .and_then(Value::as_object)
        .and_then(|value| value.get("components"))
        .and_then(Value::as_object)
    else {
        return Ok(());
    };
    let mut parts = Vec::new();
    for name in ["stella", "llama", "onebot"] {
        if let Some(state) = components
            .get(name)
            .and_then(Value::as_object)
            .and_then(|component| component.get("state"))
            .and_then(Value::as_str)
        {
            parts.push(format!("{name}={state}"));
        }
    }
    if !parts.is_empty() {
        writeln!(out, "Runtime：{}", parts.join("，"))?;
    }
    Ok(())
}

/// 调度器摘要：有等待者才点名，空闲就一句话。
fn scheduler_waiting_summary(sched: Option<&Value>) -> Option<String> {
    let sched = sched.filter(|s| s.is_object())?;
    // core.llm.snapshot() 的结构是 {resources: {名: {...}}}；防御式兼容裸 map 形态
    let resources = sched
        .get("resources")
        .and_then(Value::as_object)
        .or_else(|| {
            sched
                .as_object()
                .filter(|m| m.values().all(|v| v.is_object()))
        })?;
    let mut waiting: Vec<String> = Vec::new();
    for (name, r) in resources {
        let w = r.get("waiting").and_then(Value::as_i64).unwrap_or(0);
        if w > 0 {
            waiting.push(format!("{name}×{w}"));
        }
    }
    Some(if waiting.is_empty() {
        "空闲".to_string()
    } else {
        format!("等待中 {}", waiting.join("、"))
    })
}

fn inspect_state(ctx: &Ctx, container: &str) -> Option<String> {
    let cmd = vec![
        "docker".to_string(),
        "inspect".to_string(),
        "--format".to_string(),
        "{{.State.Status}}".to_string(),
        container.to_string(),
    ];
    let out = runner::run_output(&cmd, &ctx.root).ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (!s.is_empty()).then_some(s)
}

fn inspect_health(ctx: &Ctx, container: &str) -> Option<String> {
    let cmd = vec![
        "docker".to_string(),
        "inspect".to_string(),
        "--format".to_string(),
        "{{.State.Health.Status}}".to_string(),
        container.to_string(),
    ];
    let out = runner::run_output(&cmd, &ctx.root).ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (!s.is_empty()).then_some(s)
}

/// 经 docker exec 取容器内状态接口（回环限制决定了只能这样取，方案 §3）。
fn exec_status(ctx: &Ctx) -> Option<Value> {
    let cmd = vec![
        "docker".to_string(),
        "exec".to_string(),
        "stella".to_string(),
        "curl".to_string(),
        "-fsS".to_string(),
        "--max-time".to_string(),
        "2".to_string(),
        "http://127.0.0.1:8080/stella/status".to_string(),
    ];
    let out = runner::run_output(&cmd, &ctx.root).ok()?;
    if !out.status.success() {
        return None;
    }
    serde_json::from_slice(&out.stdout).ok()
}

/// 秒数 → 「2天3时4分 / 3时4分 / 4分5秒 / 5秒」。
pub fn fmt_duration(total_secs: i64) -> String {
    if total_secs < 0 {
        return "0秒".to_string();
    }
    let days = total_secs / 86400;
    let hours = (total_secs % 86400) / 3600;
    let mins = (total_secs % 3600) / 60;
    let secs = total_secs % 60;
    if days > 0 {
        format!("{days}天{hours}时{mins}分")
    } else if hours > 0 {
        format!("{hours}时{mins}分")
    } else if mins > 0 {
        format!("{mins}分{secs}秒")
    } else {
        format!("{secs}秒")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn render_inner_to_string(v: &Value) -> String {
        let mut buf = anstream::AutoStream::new(Vec::<u8>::new(), anstream::ColorChoice::Never);
        render_inner(v, &mut buf).unwrap();
        String::from_utf8(buf.into_inner()).unwrap()
    }

    #[test]
    fn duration_format() {
        assert_eq!(fmt_duration(5), "5秒");
        assert_eq!(fmt_duration(65), "1分5秒");
        assert_eq!(fmt_duration(3661), "1时1分");
        assert_eq!(fmt_duration(90061), "1天1时1分");
    }

    #[test]
    fn link_null_semantics_do_not_panic() {
        // 未连接时 connected_seconds 等是显式 null——这里钉住「不崩、文案正确」
        let v: Value = serde_json::json!({
            "link": {"enabled": true, "connected": false, "healthy": false,
                      "connected_seconds": null, "last_event_seconds_ago": null}
        });
        let text = render_inner_to_string(&v);
        assert!(text.contains("未连接"));
    }

    #[test]
    fn scheduler_waiting_lists_names() {
        let v: Value = serde_json::json!({
            "scheduler": {"resources": {
                "llm_chat": {"waiting": 2, "limit": 2},
                "embed": {"waiting": 0, "limit": 1}
            }}
        });
        let text = render_inner_to_string(&v);
        assert!(text.contains("llm_chat×2"), "{text}");
    }

    #[test]
    fn runtime_states_are_rendered_when_present() {
        let v: Value = serde_json::json!({
            "runtime": {"components": {
                "stella": {"state": "healthy"},
                "llama": {"state": "disabled"},
                "onebot": {"state": "degraded"}
            }}
        });
        let text = render_inner_to_string(&v);
        assert!(text.contains("stella=healthy"));
        assert!(text.contains("llama=disabled"));
        assert!(text.contains("onebot=degraded"));
    }
}
