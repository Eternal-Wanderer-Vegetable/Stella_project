// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors

//! File-backed instance lock. The lock is intentionally scoped to one Runtime
//! instance directory and does not replace the legacy process ownership file.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Command;

const LOCK_NAME: &str = "runtime.lock";

pub struct InstanceLock {
    path: PathBuf,
    _file: File,
}

impl InstanceLock {
    pub fn acquire(root: impl Into<PathBuf>) -> anyhow::Result<Self> {
        let root = root.into();
        fs::create_dir_all(&root)?;
        let path = root.join(LOCK_NAME);
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .map_err(|error| {
                anyhow::anyhow!(
                    "Runtime 实例已被占用或无法创建锁 {}: {error}",
                    path.display()
                )
            })?;
        writeln!(file, "pid={}", std::process::id())?;
        file.flush()?;
        Ok(Self { path, _file: file })
    }

    pub fn recover_stale(root: impl Into<PathBuf>) -> anyhow::Result<bool> {
        let root = root.into();
        let path = root.join(LOCK_NAME);
        if !path.is_file() {
            return Ok(false);
        }
        let text = fs::read_to_string(&path)?;
        let pid = text
            .lines()
            .find_map(|line| line.strip_prefix("pid="))
            .and_then(|value| value.trim().parse::<u32>().ok())
            .ok_or_else(|| anyhow::anyhow!("Runtime lock owner record is invalid"))?;
        if pid == 0 || process_is_running(pid) {
            return Ok(false);
        }
        fs::remove_file(path)?;
        Ok(true)
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

fn process_is_running(pid: u32) -> bool {
    #[cfg(unix)]
    {
        Command::new("kill")
            .args(["-0", &pid.to_string()])
            .status()
            .map(|status| status.success())
            .unwrap_or(true)
    }
    #[cfg(windows)]
    {
        Command::new("tasklist")
            .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
            .output()
            .map(|output| {
                let text = String::from_utf8_lossy(&output.stdout);
                output.status.success() && text.contains(&format!("\"{pid}\""))
            })
            .unwrap_or(true)
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = (pid, Command::new("true"));
        true
    }
}

impl Drop for InstanceLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_one_lock_can_be_held() {
        let dir = tempfile::tempdir().unwrap();
        let first = InstanceLock::acquire(dir.path()).unwrap();
        assert!(InstanceLock::acquire(dir.path()).is_err());
        drop(first);
        assert!(InstanceLock::acquire(dir.path()).is_ok());
    }

    #[test]
    fn stale_lock_with_dead_owner_can_be_recovered() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join(LOCK_NAME);
        fs::write(&path, "pid=4294967295\n").unwrap();
        assert!(InstanceLock::recover_stale(dir.path()).unwrap());
        assert!(!path.exists());
    }

    #[test]
    fn live_owner_lock_is_not_recovered() {
        let dir = tempfile::tempdir().unwrap();
        let lock = InstanceLock::acquire(dir.path()).unwrap();
        assert!(!InstanceLock::recover_stale(dir.path()).unwrap());
        drop(lock);
    }
}
