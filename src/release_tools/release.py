#!/usr/bin/env python3
"""
Release helper for cargo crate.

Usage:
    cargo-release patch|minor|major   # Normal release
    cargo-release --dry-run patch     # Preview changes without committing
    cargo-release --continue          # Resume a failed release

The --continue flag is useful when cargo publish fails (e.g., network issues)
after the release commit has been created. It will:
  1. Verify the last commit is a release commit
  2. Retry cargo publish
  3. Create the git tag (if not already created)
  4. Push the commit and tags
"""

import argparse
import os
import pathlib
import re
import shlex
import subprocess
import sys
from typing import Tuple

from . import changelog


def find_project_root() -> pathlib.Path:
    """Find project root by looking for Cargo.toml in CWD or parents."""
    cwd = pathlib.Path.cwd()
    if (cwd / "Cargo.toml").exists():
        return cwd
    for parent in cwd.parents:
        if (parent / "Cargo.toml").exists():
            return parent
    sys.stderr.write("error: Cargo.toml not found in current directory or parents\n")
    sys.exit(1)


def run(cmd: list[str], root: pathlib.Path, *, check: bool = True) -> subprocess.CompletedProcess:
    """Execute a command relative to the repo root."""
    return subprocess.run(cmd, cwd=root, check=check)


def run_capture(cmd: list[str], root: pathlib.Path) -> str:
    result = subprocess.run(
        cmd,
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout


def ensure_main_branch(root: pathlib.Path) -> None:
    branch = run_capture(["git", "rev-parse", "--abbrev-ref", "HEAD"], root).strip()
    if branch != "main":
        sys.stderr.write(f"error: releases must be made from main branch (currently on '{branch}')\n")
        sys.exit(1)


def ensure_clean_worktree(root: pathlib.Path) -> None:
    status = run_capture(["git", "status", "--porcelain", "--ignore-submodules"], root)
    if status.strip():
        sys.stderr.write("error: working tree must be clean before releasing\n")
        sys.stderr.write(status)
        sys.exit(1)


def read_package_info(cargo_toml: pathlib.Path) -> Tuple[str, str]:
    toml_text = cargo_toml.read_text()

    name_match = re.search(r'(?m)^\s*name\s*=\s*"([^"]+)"\s*$', toml_text)
    version_match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"\s*$', toml_text)

    if not name_match or not version_match:
        sys.stderr.write(
            "error: unable to extract package name/version from Cargo.toml\n"
        )
        sys.exit(1)

    return name_match.group(1), version_match.group(1)


def bump_version(current: str, bump: str) -> str:
    parts = current.split(".")
    if len(parts) != 3 or any(not p.isdigit() for p in parts):
        sys.stderr.write(f"error: unsupported version format '{current}'\n")
        sys.exit(1)

    if bump == "current":
        return current

    major, minor, patch = map(int, parts)

    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        sys.stderr.write(f"error: unknown bump '{bump}'\n")
        sys.exit(1)

    return f"{major}.{minor}.{patch}"


def update_cargo_files(cargo_toml: pathlib.Path, new_version: str, root: pathlib.Path) -> None:
    toml_text = cargo_toml.read_text()
    new_toml_text, replaced = re.subn(
        r'(?m)^(version\s*=\s*")([^"]+)(")',
        lambda m: f"{m.group(1)}{new_version}{m.group(3)}",
        toml_text,
        count=1,
    )
    if replaced != 1:
        sys.stderr.write("error: failed to update Cargo.toml\n")
        sys.exit(1)

    # Only write if actual changes occurred (e.g., bump='current' won't change anything)
    if new_toml_text != toml_text:
        cargo_toml.write_text(new_toml_text)
        # Let cargo update Cargo.lock automatically
        run(["cargo", "check", "--quiet"], root)


def commit_release(new_version: str, root: pathlib.Path) -> None:
    message = f"release v{new_version}"
    run(["git", "add", "Cargo.toml", "Cargo.lock", "CHANGELOG.md"], root)
    run(["git", "commit", "-m", message], root)


def tag_release(new_version: str, root: pathlib.Path) -> None:
    message = f"release v{new_version}"
    run(["git", "tag", "-a", f"v{new_version}", "-m", message], root)


def push_release(root: pathlib.Path) -> None:
    run(["git", "push"], root)
    run(["git", "push", "--tags"], root)


def publish_crate(root: pathlib.Path) -> None:
    run(["cargo", "publish"], root)


def continue_release(root: pathlib.Path, cargo_toml: pathlib.Path) -> None:
    """Continue a release that failed after commit but before completion."""
    # Get the last commit message to extract version
    last_commit = run_capture(["git", "log", "-1", "--format=%s"], root).strip()

    match = re.match(r"^release v(\d+\.\d+\.\d+)$", last_commit)
    if not match:
        sys.stderr.write(
            f"error: last commit doesn't look like a release commit: '{last_commit}'\n"
        )
        sys.stderr.write("Expected format: 'release vX.Y.Z'\n")
        sys.exit(1)

    version = match.group(1)
    crate_name, cargo_version = read_package_info(cargo_toml)

    if cargo_version != version:
        sys.stderr.write(
            f"error: Cargo.toml version ({cargo_version}) doesn't match "
            f"commit version ({version})\n"
        )
        sys.exit(1)

    # Check if tag already exists
    tag_exists = subprocess.run(
        ["git", "rev-parse", f"v{version}"],
        cwd=root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0

    print(f"Continuing release of {crate_name} v{version}")

    publish_crate(root)

    if not tag_exists:
        tag_release(version, root)

    push_release(root)

    print(f"Released {crate_name} v{version}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Release helper for cargo crate")
    parser.add_argument(
        "bump",
        nargs="?",
        choices=("patch", "minor", "major", "current"),
        help="Semver component to bump, or 'current' to release existing version",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate changelog only, don't commit/publish/push",
    )
    parser.add_argument(
        "--continue",
        dest="continue_release",
        action="store_true",
        help="Continue a failed release (publish, tag, and push)",
    )
    args = parser.parse_args()

    # Find project root after parsing args (so --help works anywhere)
    root = find_project_root()
    cargo_toml = root / "Cargo.toml"

    # Change to repo root so changelog module works correctly
    os.chdir(root)

    ensure_main_branch(root)

    if args.continue_release:
        if args.bump:
            parser.error("--continue does not take a bump argument")
        continue_release(root, cargo_toml)
        return

    if not args.bump:
        parser.error("bump is required unless using --continue")

    ensure_clean_worktree(root)

    crate_name, current_version = read_package_info(cargo_toml)
    new_version = bump_version(current_version, args.bump)

    # Check for existing tag before doing work
    tag_name = f"v{new_version}"
    if subprocess.run(
        ["git", "rev-parse", tag_name],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0:
        sys.stderr.write(f"error: tag {tag_name} already exists\n")
        sys.exit(1)

    update_cargo_files(cargo_toml, new_version, root)

    # Generate changelog entry for the new version
    changelog.generate_for_pending(f"v{new_version}")

    status_after_update = run_capture(
        ["git", "status", "--porcelain", "--ignore-submodules"], root
    )
    if not status_after_update.strip():
        sys.stderr.write("error: version bump produced no changes; aborting\n")
        sys.exit(1)

    if args.dry_run:
        print(f"Dry run complete for {crate_name} v{new_version}")
        print("Changes staged but not committed. Run 'git diff' to review.")
        return

    # Let user review/edit changelog before proceeding
    editor_cmd = shlex.split(os.environ.get("EDITOR", "vim"))
    subprocess.run(editor_cmd + ["CHANGELOG.md"], check=True)

    response = input("Proceed with release? [y/N] ").strip().lower()
    if response != "y":
        print("Aborting release.")
        sys.exit(1)

    commit_release(new_version, root)

    publish_crate(root)

    tag_release(new_version, root)
    push_release(root)

    print(f"Released {crate_name} v{new_version}")


if __name__ == "__main__":
    main()
