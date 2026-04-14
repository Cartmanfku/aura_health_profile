# Publishing Guide (GitHub + ClawHub)

This project is published in two places:

1. **GitHub** (source of truth for code, issues, PRs, tags)
2. **ClawHub** (distributed OpenClaw skill package)

The checks below are based on current project files and [ClawHub skill format](https://github.com/openclaw/clawhub/blob/main/docs/skill-format.md).

## 1) File format requirements checklist

## Core metadata and docs

- `SKILL.md` (required): YAML frontmatter must include at least `name`, `description`, `version` (semver), and `metadata.openclaw`.
- `SKILL_CN.md` (recommended): Chinese mirror aligned with `SKILL.md`.
- `README.md` (recommended): English project intro and usage overview.
- `README_CN.md` (recommended): Simplified Chinese README.
- `LICENSE` (required): keep **MIT-0** to match ClawHub policy.
- `PUBLISHING.md` (this file): release/runbook for maintainers.

## Bundle/package constraints

- Keep publish bundle text-based (`.md`, `.py`, `.json`, `.txt`, etc.).
- Keep total bundle size under **50MB**.
- Do not include secrets (API keys, private configs, tokens).
- Exclude local artifacts with `.clawhubignore` (already includes `.venv/`, `__pycache__/`, `.DS_Store`, build outputs).

## Naming and versioning

- `version` must be semver (`MAJOR.MINOR.PATCH`), e.g. `1.0.0`.
- ClawHub slug/folder name should be URL-safe (`^[a-z0-9][a-z0-9-]*$`).
- If underscore folder names are rejected by ClawHub, publish from a hyphenated folder name such as `aura-health-profile`.

## 2) Pre-publish validation (recommended)

Run from the skill root (`aura_health_profile/`):

```bash
python3 -m compileall scripts
python3 scripts/vision_parser.py --help
python3 scripts/build_profile.py --help
python3 scripts/update_profile.py --help
python3 scripts/generate_brief.py --help
```

Also manually confirm:

- `SKILL.md` and `SKILL_CN.md` frontmatter are in sync for `description`, `version`, `author`.
- `README.md` / `README_CN.md` mention correct capabilities (Mode 1/2/3).
- `requirements.txt` matches real runtime dependencies.

## 3) Publish to GitHub

If this directory is not yet a git repo:

```bash
cd /path/to/aura_health_profile
git init
git add .
git commit -m "Initial release: aura health profile skill"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

For subsequent releases:

```bash
git add .
git commit -m "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

After repo is public:

- Replace GitHub placeholders in `README.md` / `README_CN.md` (`Repository`, `Issues`, `Pull Requests`).
- Add `homepage: <YOUR_GITHUB_REPO_URL>` to `SKILL.md` and `SKILL_CN.md` frontmatter.

## 4) Publish to ClawHub

Install and log in first (per [OpenClaw docs](https://docs.openclaw.ai/tools/clawhub)).

```bash
clawhub login
cd /path/to/aura_health_profile   # folder containing SKILL.md
clawhub skill publish . --version X.Y.Z
```

Notes:

- Bump version before each publish (and keep git tag + ClawHub version aligned).
- If available in your CLI, run dry-run/validation flags before final publish.
- If publish fails on slug naming, retry from a hyphenated directory name.

## 5) Release consistency checklist

Before announcing a release, confirm all of the following:

- Git tag `vX.Y.Z` exists and matches `SKILL*.md` `version`.
- ClawHub published version is also `X.Y.Z`.
- README links and GitHub placeholders are up to date.
- Changelog/release notes (GitHub Release) summarize user-visible changes.
