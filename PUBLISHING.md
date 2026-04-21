# Publishing Guide (GitHub + ClawHub)

简体中文见 [`PUBLISHING_CN.md`](PUBLISHING_CN.md).

This project is published in two places:

1. **GitHub** (source of truth for code, issues, PRs, tags)
2. **ClawHub** (distributed OpenClaw skill package)

The checks below are based on current project files and [ClawHub skill format](https://github.com/openclaw/clawhub/blob/main/docs/skill-format.md).

## 1) File format requirements checklist

### Core metadata and docs

- `SKILL.md` (required): YAML frontmatter must include at least `name`, `description`, `version` (semver), and `metadata.openclaw`.
- `SKILL_CN.md` (recommended): Chinese mirror aligned with `SKILL.md`.
- `README.md` (recommended): English project intro and usage overview.
- `README_CN.md` (recommended): Simplified Chinese README.
- `LICENSE` (required): keep **MIT-0** to match ClawHub policy.
- `PUBLISHING.md` (this file): English release/runbook for maintainers; [`PUBLISHING_CN.md`](PUBLISHING_CN.md) is the Simplified Chinese edition.
- `CHANGELOG.md` (recommended): English user-visible changes per semver release.
- `CHANGELOG_CN.md` (recommended): Simplified Chinese changelog, kept in sync with `CHANGELOG.md`.

### Onboarding and install inputs

- `ONBOARD.md`, `ONBOARD_CN.md` (recommended): first-run environment checks, API key setup, and sample flow.
- `requirements.txt` (required): Python dependencies for `scripts/` (`pip install -r requirements.txt` in a venv).
- `.clawhubignore` (recommended): patterns excluded from the ClawHub zip (venv, `__pycache__`, local build dirs).

### Assets and references (shipped with the skill)

- `assets/profile_template.md`, `assets/profile_template_cn.md`, `assets/brief_template.md`, `assets/brief_template_cn.md`
- `references/medical_reference.md`, `references/medical_reference_cn.md`

### `scripts/` inventory

**CLI entrypoints** (run `--help` before each publish):

- `vision_parser.py` — raster medical images  
- `pdf_vision_parser.py` — PDF pages → vision → per-page intermediates (optional bundles)  
- `pdf_bundle_builder.py` — build bundle Markdown from per-page PDF intermediates  
- `build_profile.py`, `update_profile.py` — fast merge profile build / update  
- `build_profile_sharded.py`, `update_profile_sharded.py` — time-sharded merge build / update  
- `md_to_pdf.py` — Markdown → PDF fallback path  
- `generate_brief.py` — revisit brief + images + PDF  

**Shared libraries** (imported only; no `__main__` CLI):

- `config.py`, `vision_parse_common.py`, `intermediate_qc.py`, `profile_merge_state.py`

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
python3 scripts/pdf_vision_parser.py --help
python3 scripts/pdf_bundle_builder.py --help
python3 scripts/build_profile.py --help
python3 scripts/build_profile_sharded.py --help
python3 scripts/update_profile.py --help
python3 scripts/update_profile_sharded.py --help
python3 scripts/md_to_pdf.py --help
python3 scripts/generate_brief.py --help
```

Also manually confirm:

- `SKILL.md` and `SKILL_CN.md` frontmatter are in sync for `description`, `version`, `author`, and `metadata.openclaw.homepage` (if set).
- The latest sections in `CHANGELOG.md` and `CHANGELOG_CN.md` match the published `version` (both languages updated for each release).
- `README.md` / `README_CN.md` describe current capabilities (modes 1–3, PDF path, fast vs sharded merge, brief outputs).
- `requirements.txt` matches imports used under `scripts/` (e.g. `requests`, `mistune`, `reportlab`, `pymupdf`).
- No stray secrets under `scripts/` or docs; `.clawhubignore` still excludes `.venv/` and build artifacts.

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

- Replace any remaining GitHub placeholders in `README.md` / `README_CN.md` (repository / Issues / PR links).
- Ensure `metadata.openclaw.homepage` in `SKILL.md` and `SKILL_CN.md` points at the public repo URL (add or update to match `README*`).

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
- `CHANGELOG.md`, `CHANGELOG_CN.md`, and GitHub Release notes summarize user-visible changes.
