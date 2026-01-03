# rust-release-tools

Release automation tools for Rust/Cargo projects.

## Installation

```bash
pipx install git+https://github.com/raine/rust-release-tools.git
```

## Updating

```bash
pipx install --force git+https://github.com/raine/rust-release-tools.git
```

## Commands

### cargo-release

Release a new version of a Cargo crate.

```bash
cargo-release patch          # Bump patch version (0.1.0 -> 0.1.1)
cargo-release minor          # Bump minor version (0.1.0 -> 0.2.0)
cargo-release major          # Bump major version (0.1.0 -> 1.0.0)
cargo-release current        # Release existing version (for first release)
cargo-release --dry-run patch  # Preview without committing
cargo-release --continue     # Resume failed release
```

### update-changelog

Generate changelog entries from git tags using AI.

```bash
update-changelog                  # Backfill all missing tags
update-changelog --pending v0.1.5 # Generate entry for upcoming release
```

## Requirements

- git
- cargo
- claude (Anthropic CLI)
- cc-batch (for batch changelog generation)
- prettier (for formatting)
