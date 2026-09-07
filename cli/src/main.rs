// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。

//! stellacli —— Stella 跨平台命令行控制台（Windows / Linux / docker 形态统一入口）。
//!
//! 定位（design_docs/跨平台 CLI 控制台方案 v1.0.md）：**编排层与渲染层**。
//! 领域逻辑一律透传 Python deploy 模块；docker 形态编排 docker compose。
//! 退出码纪律：领域命令透传 deploy 的退出码（doctor 有阻塞 = 1）；
//! stellacli 自身的编排错误 = 2，供脚本区分「Bot 有问题」与「工具用错了」。

mod ctx;
mod doctor;
mod logs;
mod runner;
mod status;
mod style;

use std::io::Write;
use std::path::PathBuf;

use anyhow::{bail, Result};
use clap::{Parser, Subcommand, ValueEnum};
use ctx::Mode;

use crate::logs::Target;

#[derive(Parser)]
#[command(
    name = "stellacli",
    version,
    about = "Stella 跨平台命令行控制台：本地运行 / docker compose 统一入口（编排层，领域逻辑由 deploy 模块提供）",
    after_help = "形态自动检测；显式指定用 --mode local|docker 或环境变量 STELLA_MODE。\n文档：docs/deployment-docker.md · 方案：design_docs/跨平台 CLI 控制台方案 v1.0.md"
)]
struct Cli {
    /// 部署形态（默认自动检测）
    #[arg(long, global = true, value_name = "FORM")]
    mode: Option<ModeArg>,
    #[command(subcommand)]
    command: Command,
}

#[derive(ValueEnum, Clone, Copy)]
enum ModeArg {
    Local,
    Docker,
}

impl From<ModeArg> for Mode {
    fn from(m: ModeArg) -> Self {
        match m {
            ModeArg::Local => Mode::Local,
            ModeArg::Docker => Mode::Docker,
        }
    }
}

#[derive(Subcommand)]
enum Command {
    /// 环境自检（透传 deploy doctor；--json 输出原始 JSON 供脚本消费）
    Doctor {
        /// 输出 deploy doctor --json 的原始 JSON（不渲染）
        #[arg(long)]
        json: bool,
    },
    /// 配置向导（交互式，透传 deploy init；docker 形态在容器内运行）
    Init {
        /// 应答文件（跳过交互）
        #[arg(long, value_name = "PATH")]
        answers: Option<PathBuf>,
        /// 覆盖已有 .env（会先备份）
        #[arg(long)]
        force: bool,
        /// 只打印将写入的内容
        #[arg(long)]
        dry_run: bool,
    },
    /// 启动（本地：deploy start --detach；docker：compose up -d）
    Start,
    /// 优雅停止（本地：deploy stop 哨兵协议；docker：compose stop）
    Stop,
    /// 重启
    Restart,
    /// 运行状态面板（本地读 deploy status，docker 聚合容器状态与容器内状态接口）
    Status {
        /// 输出 JSON（本地=deploy status 原样；docker=聚合结构）
        #[arg(long)]
        json: bool,
    },
    /// 查看日志：默认结构化日志 stella.jsonl；--boot 启动诊断；--thought 思考日志
    Logs {
        /// 跟随新增日志（Ctrl+C 退出）
        #[arg(short = 'f', long)]
        follow: bool,
        /// 启动诊断 boot_debug.log（排查插件加载的第一现场）
        #[arg(long)]
        boot: bool,
        /// 思考/决策日志 stella_thought_logs.md
        #[arg(long)]
        thought: bool,
        /// 指定任意日志文件
        #[arg(long = "file", value_name = "PATH")]
        file: Option<PathBuf>,
        /// docker 形态下改用 docker compose logs（默认直接读挂载的日志文件）
        #[arg(long)]
        compose: bool,
    },
    /// 升级（docker：拉取/构建新镜像并重建容器；本地：给出发布包下载指引）
    Upgrade,
    /// 数据迁移（参数原样透传 deploy migrate）
    Migrate {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
    /// 插件工具（check / scaffold，透传 deploy plugin-*）
    Plugin {
        #[command(subcommand)]
        cmd: PluginCmd,
    },
    /// 能力清单（透传 deploy capabilities）
    Capabilities {
        /// 输出 JSON
        #[arg(long)]
        json: bool,
    },
    /// 发布清单（透传 deploy manifest）
    Manifest {
        /// 生成/刷新 .stella-manifest.json
        #[arg(long)]
        write: bool,
    },
    /// docker 形态逃生舱：原样透传 docker compose（仅 --mode docker）
    Compose {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
}

#[derive(Subcommand)]
enum PluginCmd {
    /// 校验插件目录（透传 deploy plugin-check）
    Check {
        /// 插件目录
        path: String,
        /// 输出 JSON
        #[arg(long)]
        json: bool,
    },
    /// 生成插件脚手架（参数透传 deploy plugin-scaffold）
    Scaffold {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true)]
        args: Vec<String>,
    },
}

fn main() {
    let cli = Cli::parse();
    let code = match run(cli) {
        Ok(c) => c,
        Err(e) => {
            let mut err = anstream::stderr();
            let _ = writeln!(
                err,
                "{}错误：{e:#}{}",
                style::ERROR.render(),
                anstyle::Reset.render()
            );
            2
        }
    };
    std::process::exit(code);
}

fn run(cli: Cli) -> Result<i32> {
    let ctx = ctx::resolve(cli.mode.map(Into::into))?;
    let mut out = anstream::stdout();
    match cli.command {
        Command::Doctor { json } => {
            let cmd = ctx.domain_cmd(&["doctor", "--json"], false);
            let (v, raw, code) = runner::capture_json(&cmd, &ctx.root, "deploy doctor")?;
            if json {
                writeln!(out, "{raw}")?;
            } else {
                doctor::render(&v, &mut out)?;
            }
            Ok(code) // deploy 的退出码：有阻塞项 = 1，脚本据此判断
        }
        Command::Init {
            answers,
            force,
            dry_run,
        } => {
            let mut sub: Vec<String> = vec!["init".into()];
            if let Some(a) = answers {
                sub.push("--answers".into());
                sub.push(a.to_string_lossy().into_owned());
            }
            if force {
                sub.push("--force".into());
            }
            if dry_run {
                sub.push("--dry-run".into());
            }
            let sub_ref: Vec<&str> = sub.iter().map(String::as_str).collect();
            // 交互向导：必须继承 TTY（docker 形态下不加 -T）
            runner::run_passthrough(&ctx.domain_cmd(&sub_ref, true), &ctx.root)
        }
        Command::Start => match ctx.mode {
            Mode::Local => {
                runner::run_passthrough(&ctx.deploy_cmd(&["start", "--detach"]), &ctx.root)
            }
            Mode::Docker => runner::run_passthrough(&ctx.compose_cmd(&["up", "-d"]), &ctx.root),
        },
        Command::Stop => match ctx.mode {
            Mode::Local => runner::run_passthrough(&ctx.deploy_cmd(&["stop"]), &ctx.root),
            Mode::Docker => runner::run_passthrough(&ctx.compose_cmd(&["stop"]), &ctx.root),
        },
        Command::Restart => match ctx.mode {
            Mode::Local => {
                let code = runner::run_passthrough(&ctx.deploy_cmd(&["stop"]), &ctx.root)?;
                if code != 0 {
                    bail!("stop 阶段失败（退出码 {code}），已中止，未重新启动");
                }
                runner::run_passthrough(&ctx.deploy_cmd(&["start", "--detach"]), &ctx.root)
            }
            Mode::Docker => runner::run_passthrough(&ctx.compose_cmd(&["restart"]), &ctx.root),
        },
        Command::Status { json } => match ctx.mode {
            Mode::Local => {
                let cmd = ctx.deploy_cmd(&["status", "--json"]);
                let (_, raw, _) = runner::capture_json(&cmd, &ctx.root, "deploy status")?;
                if json {
                    writeln!(out, "{raw}")?;
                } else if let Ok(v) = serde_json::from_str::<serde_json::Value>(&raw) {
                    status::render_local(&v, &ctx.root, &mut out)?;
                } else {
                    // capture_json 已确保能解析；这里只是双保险，不吞现场
                    writeln!(out, "{raw}")?;
                }
                Ok(0)
            }
            Mode::Docker => status::docker_status(&ctx, json, &mut out),
        },
        Command::Logs {
            follow,
            boot,
            thought,
            file,
            compose: use_compose,
        } => {
            let selected = [boot, thought, file.is_some()]
                .iter()
                .filter(|b| **b)
                .count();
            if selected > 1 {
                bail!("--boot / --thought / --file 只能选一个日志源");
            }
            if use_compose {
                if ctx.mode != Mode::Docker {
                    bail!("--compose 只适用于 docker 形态（本地形态的日志就是文件，直接读取）");
                }
                let mut sub: Vec<&str> = vec!["logs"];
                if follow {
                    sub.push("-f");
                }
                sub.push("stella");
                return runner::run_passthrough(&ctx.compose_cmd(&sub), &ctx.root);
            }
            let target = if boot {
                Target::Boot
            } else if thought {
                Target::Thought
            } else {
                Target::Jsonl
            };
            logs::run(
                &ctx.root,
                ctx.mode == Mode::Docker,
                target,
                file.as_deref(),
                follow,
                &mut out,
            )
        }
        Command::Upgrade => {
            match ctx.mode {
                Mode::Local => {
                    writeln!(out, "本地形态升级 = 换发布包目录，数据不动：")?;
                    writeln!(out, "  1. 停止：stellacli stop")?;
                    writeln!(out, "  2. 下载新版：https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases")?;
                    writeln!(out, "  3. 解压到新目录，把旧目录的 StellaData/ 保持在新目录同级（或沿用原位置）")?;
                    writeln!(
                        out,
                        "  细节见 docs/deployment-docker.md 的迁移章节与「升级与数据迁移方案」。"
                    )?;
                    Ok(0)
                }
                Mode::Docker => {
                    // 与 docs/deployment-docker.md §5 的升级流程一致；git pull 属版本管理，
                    // CLI 不代办，只在前面提示
                    writeln!(out, "提示：如用 git 管理代码，先 git pull 再升级镜像。")?;
                    let steps: [(&str, Vec<&str>); 3] = [
                        ("拉取 napcat 镜像", vec!["pull", "napcat"]),
                        ("构建 stella 镜像", vec!["build", "stella"]),
                        ("重建容器", vec!["up", "-d"]),
                    ];
                    for (name, sub) in steps {
                        writeln!(out, "==> {name}")?;
                        let code = runner::run_passthrough(&ctx.compose_cmd(&sub), &ctx.root)?;
                        if code != 0 {
                            bail!("步骤「{name}」失败（退出码 {code}），后续步骤已跳过");
                        }
                    }
                    writeln!(out, "升级完成。数据卷未受影响。")?;
                    Ok(0)
                }
            }
        }
        Command::Migrate { args } => {
            let mut sub: Vec<String> = vec!["migrate".into()];
            sub.extend(args);
            let sub_ref: Vec<&str> = sub.iter().map(String::as_str).collect();
            runner::run_passthrough(&ctx.domain_cmd(&sub_ref, true), &ctx.root)
        }
        Command::Plugin { cmd } => {
            let sub: Vec<String> = match cmd {
                PluginCmd::Check { path, json } => {
                    let mut v = vec!["plugin-check".to_string(), path];
                    if json {
                        v.push("--json".into());
                    }
                    v
                }
                PluginCmd::Scaffold { args } => {
                    let mut v = vec!["plugin-scaffold".to_string()];
                    v.extend(args);
                    v
                }
            };
            let sub_ref: Vec<&str> = sub.iter().map(String::as_str).collect();
            runner::run_passthrough(&ctx.domain_cmd(&sub_ref, true), &ctx.root)
        }
        Command::Capabilities { json } => {
            let sub: Vec<&str> = if json {
                vec!["capabilities", "--json"]
            } else {
                vec!["capabilities"]
            };
            runner::run_passthrough(&ctx.domain_cmd(&sub, true), &ctx.root)
        }
        Command::Manifest { write } => {
            let sub: Vec<&str> = if write {
                vec!["manifest", "--write"]
            } else {
                vec!["manifest"]
            };
            runner::run_passthrough(&ctx.domain_cmd(&sub, true), &ctx.root)
        }
        Command::Compose { args } => match ctx.mode {
            Mode::Docker => {
                let sub_ref: Vec<&str> = args.iter().map(String::as_str).collect();
                runner::run_passthrough(&ctx.compose_cmd(&sub_ref), &ctx.root)
            }
            Mode::Local => bail!(
                "compose 子命令只适用于 docker 形态（当前是本地形态）。\
                 本地形态的启停/日志请直接用 stellacli start/stop/logs。"
            ),
        },
    }
}
