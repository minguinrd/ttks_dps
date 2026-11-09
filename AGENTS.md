# Agent notes (ttks_dps)

## Repo state (verified)
- Workspace is currently minimal: no `README*`, manifests, lockfiles, build/test/lint config, CI workflows, or git repository detected under `/home/minguin/Projects/ttks_dps` (only `.opencode/skills/` present).
- No existing agent instruction files (`AGENTS.md` previously absent, no `CLAUDE.md`, `.cursor/rules/`, `.cursorrules`, `.github/copilot-instructions.md`, or repo-local `opencode.json`) were found.

## Working guidance
- Before running or suggesting build/test/lint commands, confirm the actual toolchain by locating manifests/config (e.g., `package.json`, `pyproject.toml`, `Cargo.toml`, `Makefile`, CI files) once they are added.
- Do not assume language, framework, package manager, or test runner in this repository until verified from files in the repo.
