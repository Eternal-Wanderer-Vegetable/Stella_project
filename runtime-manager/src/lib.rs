// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors
// 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。

//! Shared Runtime Contract plus the safe, file-backed part of supervision.
//! Long-lived process handling is layered on top of this contract.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

pub mod backoff;
pub mod lock;

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Component {
    Stella,
    Llama,
    Onebot,
}

impl Component {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Stella => "stella",
            Self::Llama => "llama",
            Self::Onebot => "onebot",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Operation {
    Start,
    Stop,
    Restart,
    Status,
    Logs,
    Doctor,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthSpec {
    #[serde(rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogSpec {
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentManifest {
    pub kind: Component,
    pub enabled: bool,
    #[serde(default)]
    pub dependencies: Vec<Component>,
    #[serde(default)]
    pub health: Option<HealthSpec>,
    #[serde(default)]
    pub logs: Option<LogSpec>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeManifest {
    pub schema_version: u32,
    pub instance_id: String,
    pub project_root: String,
    pub runtime_dir: String,
    pub components: std::collections::BTreeMap<String, ComponentManifest>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ComponentStateKind {
    Disabled,
    Stopped,
    Starting,
    Running,
    Healthy,
    Degraded,
    Failed,
}

impl Default for ComponentStateKind {
    fn default() -> Self {
        Self::Stopped
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ComponentState {
    pub state: ComponentStateKind,
    #[serde(default)]
    pub pid: Option<u32>,
    #[serde(default)]
    pub endpoint: Option<String>,
    #[serde(default)]
    pub error: Option<RuntimeError>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeError {
    pub code: String,
    pub message: String,
    #[serde(default)]
    pub details: Option<std::collections::BTreeMap<String, serde_json::Value>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeState {
    pub schema_version: u32,
    pub instance_id: String,
    pub desired: ComponentStateKind,
    pub updated_at: String,
    pub components: std::collections::BTreeMap<String, ComponentState>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OperationRequest {
    pub operation: Operation,
    pub component: Component,
    #[serde(default)]
    pub parameters: std::collections::BTreeMap<String, serde_json::Value>,
}

pub fn validate_request(request: &OperationRequest) -> anyhow::Result<()> {
    if matches!(request.operation, Operation::Logs | Operation::Doctor)
        && matches!(request.component, Component::Onebot)
    {
        anyhow::bail!("onebot 不支持该 Runtime 操作");
    }
    validate_parameters(&request.parameters)?;
    Ok(())
}

fn validate_parameters(
    parameters: &std::collections::BTreeMap<String, serde_json::Value>,
) -> anyhow::Result<()> {
    const FORBIDDEN: [&str; 5] = ["command", "cmd", "shell", "shell_command", "executable"];
    for (key, value) in parameters {
        if FORBIDDEN
            .iter()
            .any(|forbidden| key.eq_ignore_ascii_case(forbidden))
        {
            anyhow::bail!("Runtime 参数禁止包含命令字段：{key}");
        }
        if let Some(object) = value.as_object() {
            let nested = object
                .iter()
                .map(|(key, value)| (key.clone(), value.clone()))
                .collect();
            validate_parameters(&nested)?;
        }
        if let Some(array) = value.as_array() {
            for item in array {
                if let Some(object) = item.as_object() {
                    let nested = object
                        .iter()
                        .map(|(key, value)| (key.clone(), value.clone()))
                        .collect();
                    validate_parameters(&nested)?;
                }
            }
        }
    }
    Ok(())
}

pub fn default_manifest(
    instance_id: impl Into<String>,
    project_root: impl Into<String>,
    runtime_dir: impl Into<String>,
) -> RuntimeManifest {
    let mut components = std::collections::BTreeMap::new();
    components.insert(
        "stella".into(),
        ComponentManifest {
            kind: Component::Stella,
            enabled: true,
            dependencies: vec![],
            health: Some(HealthSpec {
                kind: "http".into(),
                path: Some("/stella/status".into()),
            }),
            logs: Some(LogSpec {
                path: "logs/stella.log".into(),
            }),
        },
    );
    components.insert(
        "llama".into(),
        ComponentManifest {
            kind: Component::Llama,
            enabled: false,
            dependencies: vec![],
            health: Some(HealthSpec {
                kind: "http".into(),
                path: Some("/v1/models".into()),
            }),
            logs: Some(LogSpec {
                path: "logs/llama.log".into(),
            }),
        },
    );
    components.insert(
        "onebot".into(),
        ComponentManifest {
            kind: Component::Onebot,
            enabled: false,
            dependencies: vec![Component::Stella],
            health: Some(HealthSpec {
                kind: "link-status".into(),
                path: None,
            }),
            logs: Some(LogSpec {
                path: "logs/onebot.log".into(),
            }),
        },
    );
    RuntimeManifest {
        schema_version: SCHEMA_VERSION,
        instance_id: instance_id.into(),
        project_root: project_root.into(),
        runtime_dir: runtime_dir.into(),
        components,
    }
}

impl RuntimeState {
    pub fn new(instance_id: impl Into<String>) -> Self {
        let mut components = std::collections::BTreeMap::new();
        components.insert(
            "stella".into(),
            ComponentState {
                state: ComponentStateKind::Stopped,
                ..Default::default()
            },
        );
        components.insert(
            "llama".into(),
            ComponentState {
                state: ComponentStateKind::Disabled,
                ..Default::default()
            },
        );
        components.insert(
            "onebot".into(),
            ComponentState {
                state: ComponentStateKind::Disabled,
                ..Default::default()
            },
        );
        Self {
            schema_version: SCHEMA_VERSION,
            instance_id: instance_id.into(),
            desired: ComponentStateKind::Stopped,
            updated_at: now(),
            components,
        }
    }
}

pub struct RuntimeStore {
    root: PathBuf,
}

impl RuntimeStore {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn manifest_path(&self) -> PathBuf {
        self.root.join("runtime-manifest.json")
    }

    pub fn state_path(&self) -> PathBuf {
        self.root.join("runtime-state.json")
    }

    pub fn read_manifest(&self) -> anyhow::Result<RuntimeManifest> {
        Ok(serde_json::from_slice(&fs::read(self.manifest_path())?)?)
    }

    pub fn read_state(&self) -> anyhow::Result<RuntimeState> {
        Ok(serde_json::from_slice(&fs::read(self.state_path())?)?)
    }

    pub fn write_manifest(&self, value: &RuntimeManifest) -> anyhow::Result<()> {
        atomic_write(&self.manifest_path(), value)
    }

    pub fn write_state(&self, value: &RuntimeState) -> anyhow::Result<()> {
        atomic_write(&self.state_path(), value)
    }
}

fn now() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();
    seconds.to_string()
}

fn atomic_write<T: Serialize>(path: &Path, value: &T) -> anyhow::Result<()> {
    fs::create_dir_all(path.parent().unwrap_or_else(|| Path::new(".")))?;
    let temp = path.with_extension(format!("{}.tmp", std::process::id()));
    let bytes = serde_json::to_vec_pretty(value)?;
    fs::write(&temp, [bytes.as_slice(), b"\n"].concat())?;
    fs::rename(temp, path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_contract_contains_optional_components() {
        let manifest = default_manifest("demo", "C:/stella", "C:/data/.stella");
        assert_eq!(manifest.schema_version, 1);
        assert!(!manifest.components["llama"].enabled);
        assert_eq!(
            manifest.components["onebot"].dependencies,
            vec![Component::Stella]
        );
    }

    #[test]
    fn unsupported_operation_is_rejected() {
        let request = OperationRequest {
            operation: Operation::Logs,
            component: Component::Onebot,
            parameters: Default::default(),
        };
        assert!(validate_request(&request).is_err());
    }

    #[test]
    fn command_parameters_are_rejected() {
        let request = OperationRequest {
            operation: Operation::Start,
            component: Component::Stella,
            parameters: [("shell".into(), serde_json::json!("bot.py"))]
                .into_iter()
                .collect(),
        };
        assert!(validate_request(&request).is_err());
    }

    #[test]
    fn store_round_trips_atomically() {
        let dir = tempfile::tempdir().unwrap();
        let store = RuntimeStore::new(dir.path());
        let manifest = default_manifest("demo", "root", "runtime");
        let state = RuntimeState::new("demo");
        store.write_manifest(&manifest).unwrap();
        store.write_state(&state).unwrap();
        assert_eq!(store.read_manifest().unwrap().instance_id, "demo");
        assert_eq!(
            store.read_state().unwrap().desired,
            ComponentStateKind::Stopped
        );
    }
}
