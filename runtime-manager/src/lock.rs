// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors

//! File-backed instance lock. The lock is intentionally scoped to one Runtime
//! instance directory and does not replace the legacy process ownership file.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

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

    pub fn path(&self) -> &Path {
        &self.path
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
}
