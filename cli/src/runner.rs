// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! 子进程执行助手与命令构造：本地形态透传 Python deploy 模块，docker 形态
//! 编排 docker compose。**stellacli 不实现任何领域逻辑**（方案 §2 铁律）——
//! doctor/init/stop 等一律落到 deploy，这里只有 spawn 与包装。

use std::path::Path;
use std::process::{Command, Output, Stdio};

use anyhow::{Context, Result};
use serde_json::Value;

use crate::ctx::Ctx;

/// 捕获输出执行（stdout/stderr 不外泄，由调用方决定怎么呈现）。
pub fn run_output(cmd: &[String], cwd: &Path) -> Result<Output> {
    Command::new(&cmd[0])
        .args(&cmd[1..])
        .current_dir(cwd)
        .stdin(Stdio::null())
        .output()
        .with_context(|| format!("无法执行 {}（PATH 里有没有？）", cmd[0]))
}

/// 继承 stdio 执行（交互向导、compose 启停这类要看实时输出的命令）。
/// 返回子进程退出码。
pub fn run_passthrough(cmd: &[String], cwd: &Path) -> Result<i32> {
    let status = Command::new(&cmd[0])
        .args(&cmd[1..])
        .current_dir(cwd)
        .status()
        .with_context(|| format!("无法执行 {}（PATH 里有没有？）", cmd[0]))?;
    Ok(status.code().unwrap_or(1))
}

/// 捕获输出并解析 stdout 为 JSON。返回 (JSON, 原始 stdout, 退出码)。
///
/// deploy 的 --json 输出理论上是纯 JSON，但防御性处理两种脏情况：
/// 前面混入告警行（从第一个 '{' 起解析）、整体不是 JSON（报错并带出 stdout
/// 现场，方便用户贴日志排查）。
pub fn capture_json(cmd: &[String], cwd: &Path, what: &str) -> Result<(Value, String, i32)> {
    let out = run_output(cmd, cwd)?;
    let code = out.status.code().unwrap_or(1);
    let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
    let parsed = serde_json::from_str(&stdout).ok().or_else(|| {
        stdout
            .find('{')
            .and_then(|i| serde_json::from_str(&stdout[i..]).ok())
    });
    let v = parsed.with_context(|| {
        format!(
            "{what} 的输出不是 JSON（退出码 {code}）。\nstdout: {stdout}\nstderr: {}",
            String::from_utf8_lossy(&out.stderr)
        )
    })?;
    Ok((v, stdout, code))
}

impl Ctx {
    /// 构造 `python -m deploy <sub...>`（本地形态）。
    pub fn deploy_cmd(&self, sub: &[&str]) -> Vec<String> {
        let mut cmd = self.python.clone();
        cmd.push("-m".into());
        cmd.push("deploy".into());
        cmd.extend(sub.iter().map(|s| s.to_string()));
        cmd
    }

    /// 构造 `docker compose <sub...>`。
    pub fn compose_cmd(&self, sub: &[&str]) -> Vec<String> {
        let mut cmd = vec!["docker".to_string(), "compose".to_string()];
        cmd.extend(sub.iter().map(|s| s.to_string()));
        cmd
    }

    /// 在容器里跑 deploy（docker 形态的领域命令通道）。
    ///
    /// ``tty = false`` 加 ``-T``：捕获输出的场景必须关掉 TTY 分配，否则
    /// compose 在非交互 stdin 下可能挂住；交互向导（init）传 ``tty = true``，
    /// 让 compose 按默认行为接上当前终端。
    pub fn compose_deploy_cmd(&self, sub: &[&str], tty: bool) -> Vec<String> {
        let mut cmd = self.compose_cmd(&[]);
        cmd.push("run".into());
        cmd.push("--rm".into());
        if !tty {
            cmd.push("-T".into());
        }
        cmd.push("stella".into());
        cmd.push("python".into());
        cmd.push("-m".into());
        cmd.push("deploy".into());
        cmd.extend(sub.iter().map(|s| s.to_string()));
        cmd
    }

    /// 形态适配后的领域命令：本地 → python -m deploy；docker → compose run。
    pub fn domain_cmd(&self, sub: &[&str], tty: bool) -> Vec<String> {
        match self.mode {
            crate::ctx::Mode::Local => self.deploy_cmd(sub),
            crate::ctx::Mode::Docker => self.compose_deploy_cmd(sub, tty),
        }
    }

    /// 构造统一 Runtime 操作命令。
    ///
    /// Runtime 不可用时，调用方应回退到对应的 legacy deploy 命令；这样旧
    /// 发布包和旧 Docker 镜像仍能被同一版 CLI 控制。
    pub fn runtime_cmd(&self, operation: &str) -> Vec<String> {
        self.domain_cmd(&["runtime", operation, "--component", "stella"], false)
    }
}

/// 优先读取 Runtime envelope 的 data，无法识别时回退 legacy JSON 命令。
pub fn capture_runtime_or_legacy_json(
    ctx: &Ctx,
    operation: &str,
    legacy_sub: &[&str],
    what: &str,
) -> Result<(Value, String, i32)> {
    let runtime_cmd = ctx.runtime_cmd(operation);
    if let Ok(out) = run_output(&runtime_cmd, &ctx.root) {
        let code = out.status.code().unwrap_or(1);
        let stdout = String::from_utf8_lossy(&out.stdout).into_owned();
        let stderr = String::from_utf8_lossy(&out.stderr).into_owned();
        let parsed = serde_json::from_str::<Value>(&stdout).ok().or_else(|| {
            stdout
                .find('{')
                .and_then(|i| serde_json::from_str(&stdout[i..]).ok())
        });
        if let Some(envelope) = parsed {
            if envelope.get("operation").and_then(Value::as_str) == Some(operation) {
                let data = envelope.get("data").cloned().with_context(|| {
                    format!(
                        "{what} 的 Runtime envelope 缺少 data（退出码 {code}）。\
                         \nstderr: {stderr}"
                    )
                })?;
                let raw = serde_json::to_string_pretty(&data)?;
                return Ok((data, raw, code));
            }
        }
    }
    let legacy_cmd = ctx.domain_cmd(legacy_sub, false);
    capture_json(&legacy_cmd, &ctx.root, what)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ctx::Mode;

    #[test]
    fn runtime_command_uses_local_deploy() {
        let ctx = Ctx {
            mode: Mode::Local,
            root: Path::new(".").to_path_buf(),
            python: vec!["python".to_owned()],
        };
        assert_eq!(
            ctx.runtime_cmd("status"),
            vec![
                "python",
                "-m",
                "deploy",
                "runtime",
                "status",
                "--component",
                "stella"
            ]
        );
    }

    #[test]
    fn runtime_command_uses_non_tty_compose_run() {
        let ctx = Ctx {
            mode: Mode::Docker,
            root: Path::new(".").to_path_buf(),
            python: Vec::new(),
        };
        assert_eq!(
            ctx.runtime_cmd("doctor"),
            vec![
                "docker",
                "compose",
                "run",
                "--rm",
                "-T",
                "stella",
                "python",
                "-m",
                "deploy",
                "runtime",
                "doctor",
                "--component",
                "stella"
            ]
        );
    }
}
