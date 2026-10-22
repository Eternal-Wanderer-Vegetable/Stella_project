#!/usr/bin/env python3
"""Safely fast-forward a test checkout to its configured upstream branch."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class SyncError(RuntimeError):
    """The checkout cannot be updated without risking local work."""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise SyncError(f"could not start Git: {error}") from error
    if check and result.returncode:
        detail = os.fsdecode(result.stderr).strip()
        command = " ".join(("git", *args))
        message = f"{command} failed with exit code {result.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise SyncError(message)
    return result


def _git_text(repo: Path, *args: str) -> str:
    return os.fsdecode(_git(repo, *args).stdout).strip()


def _repo_root() -> Path:
    script_dir = Path(__file__).resolve().parent
    root = _git(script_dir, "rev-parse", "--show-toplevel")
    return Path(os.fsdecode(root.stdout).strip())


def _ensure_no_operation(repo: Path) -> None:
    operation_markers = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-apply",
        "rebase-merge",
        "BISECT_LOG",
    )
    for marker in operation_markers:
        raw_path = Path(_git_text(repo, "rev-parse", "--git-path", marker))
        marker_path = raw_path if raw_path.is_absolute() else repo / raw_path
        if marker_path.exists():
            raise SyncError(
                f"Git operation in progress ({marker}); finish or abort it manually before syncing."
            )


def _ensure_clean(repo: Path) -> None:
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    if status.stdout:
        raise SyncError(
            "working tree has modified or untracked files; nothing was merged. "
            "Review `git status`, then commit or move local changes before retrying."
        )


def _paths_overlap(left: str, right: str) -> bool:
    left = left.replace("\\", "/").rstrip("/")
    right = right.replace("\\", "/").rstrip("/")
    if os.name == "nt":
        left = left.casefold()
        right = right.casefold()
    return (
        left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


def _ensure_no_ignored_path_conflicts(repo: Path, upstream: str) -> None:
    changed = _git(
        repo,
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        "HEAD",
        upstream,
    ).stdout
    ignored = _git(
        repo,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
        "-z",
    ).stdout
    changed_paths = [os.fsdecode(path) for path in changed.split(b"\0") if path]
    ignored_paths = [os.fsdecode(path) for path in ignored.split(b"\0") if path]
    conflicts = [
        local_path
        for local_path in ignored_paths
        if any(_paths_overlap(local_path, incoming_path) for incoming_path in changed_paths)
    ]
    if conflicts:
        raise SyncError(
            "incoming files overlap ignored local data; nothing was merged. "
            "Move or back up the conflicting local paths, then retry."
        )


def sync() -> int:
    repo = _repo_root()

    branch_result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if branch_result.returncode:
        raise SyncError("HEAD is detached; check out a branch with an upstream before syncing.")
    branch = os.fsdecode(branch_result.stdout).strip()

    upstream_result = _git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    )
    if upstream_result.returncode:
        raise SyncError(
            f"branch `{branch}` has no upstream; configure its remote tracking branch before syncing."
        )
    upstream = os.fsdecode(upstream_result.stdout).strip()

    remote_result = _git(repo, "config", "--get", f"branch.{branch}.remote", check=False)
    if remote_result.returncode:
        raise SyncError(f"could not determine the remote for upstream `{upstream}`.")
    remote = os.fsdecode(remote_result.stdout).strip()
    if not remote or remote == ".":
        raise SyncError(f"upstream `{upstream}` is not a remote branch.")

    _ensure_no_operation(repo)
    _ensure_clean(repo)

    before = _git_text(repo, "rev-parse", "HEAD")
    print(f"Fetching `{upstream}` for branch `{branch}`...")
    _git(repo, "fetch", "--quiet", "--no-tags", "--", remote)

    # Fetch changes refs only, but check again in case another process edited the checkout.
    _ensure_no_operation(repo)
    _ensure_clean(repo)
    current_branch_result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    current_head = _git_text(repo, "rev-parse", "HEAD")
    if (
        current_branch_result.returncode
        or os.fsdecode(current_branch_result.stdout).strip() != branch
        or current_head != before
    ):
        raise SyncError("the checkout changed during fetch; no merge was attempted.")

    target = _git_text(repo, "rev-parse", "--verify", f"{upstream}^{{commit}}")
    if before == target:
        print(f"`{branch}` is already up to date ({before[:12]}).")
        return 0

    ancestry = _git(repo, "merge-base", "--is-ancestor", "HEAD", target, check=False)
    if ancestry.returncode == 1:
        raise SyncError(
            f"local branch `{branch}` is ahead of or diverged from `{upstream}`; "
            "automatic sync only allows fast-forward updates."
        )
    if ancestry.returncode:
        detail = os.fsdecode(ancestry.stderr).strip()
        raise SyncError(f"could not compare HEAD with `{upstream}`: {detail}")

    _ensure_no_ignored_path_conflicts(repo, target)
    _ensure_clean(repo)
    _git(repo, "merge", "--ff-only", target)

    after = _git_text(repo, "rev-parse", "HEAD")
    print(f"Updated `{branch}` from {before[:12]} to {after[:12]} using fast-forward.")
    return 0


def main() -> int:
    try:
        return sync()
    except SyncError as error:
        print(f"Test repository sync stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
