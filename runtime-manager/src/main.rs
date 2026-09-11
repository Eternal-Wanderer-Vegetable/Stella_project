// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。

use std::path::PathBuf;

use anyhow::{Context, Result};
use runtime_manager::{default_manifest, RuntimeState, RuntimeStore, SCHEMA_VERSION};

fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    let command = args.next().unwrap_or_else(|| "status".into());
    let mut root = PathBuf::from(".");
    while let Some(arg) = args.next() {
        if arg == "--root" {
            root = PathBuf::from(args.next().context("--root 缺少路径")?);
        } else {
            anyhow::bail!("不支持的参数：{arg}");
        }
    }
    let store = RuntimeStore::new(root.clone());

    match command.as_str() {
        "validate" => {
            let manifest = store
                .read_manifest()
                .context("无法读取 runtime-manifest.json")?;
            anyhow::ensure!(
                manifest.schema_version == SCHEMA_VERSION,
                "不支持的 manifest schema"
            );
            println!("ok");
        }
        "status" => {
            let state = store
                .read_state()
                .or_else(|_| Ok::<RuntimeState, anyhow::Error>(RuntimeState::new("unknown")))?;
            println!("{}", serde_json::to_string_pretty(&state)?);
        }
        "init" => {
            let manifest = default_manifest("unknown", ".", root.display().to_string());
            let state = RuntimeState::new("unknown");
            store.write_manifest(&manifest)?;
            store.write_state(&state)?;
            println!("ok");
        }
        other => anyhow::bail!("不支持的 Runtime 命令：{other}"),
    }
    Ok(())
}
