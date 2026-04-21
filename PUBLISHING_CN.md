# 发布指南（GitHub + ClawHub）

简体中文版本。英文版见 [`PUBLISHING.md`](PUBLISHING.md)。

本项目在两个位置发布：

1. **GitHub**（代码、Issue、PR、标签的事实来源）
2. **ClawHub**（OpenClaw 技能分发包）

以下检查项基于当前仓库文件与 [ClawHub 技能格式](https://github.com/openclaw/clawhub/blob/main/docs/skill-format.md)。

## 1）文件格式要求清单

### 核心元数据与文档

- `SKILL.md`（必需）：YAML frontmatter 至少包含 `name`、`description`、`version`（semver）、`metadata.openclaw`。
- `SKILL_CN.md`（推荐）：与 `SKILL.md` 对齐的简体中文镜像。
- `README.md`（推荐）：英文项目简介与用法概览。
- `README_CN.md`（推荐）：简体中文 README。
- `LICENSE`（必需）：保持 **MIT-0**，以符合 ClawHub 政策。
- `PUBLISHING.md`：面向维护者的英文发布说明；[`PUBLISHING_CN.md`](PUBLISHING_CN.md) 为本文件。
- `CHANGELOG.md`（推荐）：按 semver 记录的英文用户可见变更。
- `CHANGELOG_CN.md`（推荐）：与 `CHANGELOG.md` 同步的简体中文变更日志。

### 安装说明与依赖清单

- `ONBOARD.md`、`ONBOARD_CN.md`（推荐）：首次环境检查、API key、连通性与示例流程。
- `requirements.txt`（必需）：`scripts/` 的 Python 依赖说明（venv 内 `pip install -r requirements.txt`）。
- `.clawhubignore`（推荐）：ClawHub 打包 zip 时排除 venv、`__pycache__`、本机构建目录等。

### 资源与参考（随技能分发）

- `assets/profile_template.md`、`assets/profile_template_cn.md`、`assets/brief_template.md`、`assets/brief_template_cn.md`
- `references/medical_reference.md`、`references/medical_reference_cn.md`

### `scripts/` 脚本清单

**可执行入口**（每次发布前应对其运行 `--help`）：

- `vision_parser.py` — 栅格医学图片解析  
- `pdf_vision_parser.py` — PDF 逐页转图 → 视觉解析 → 中间稿（可选 bundle）  
- `pdf_bundle_builder.py` — 由逐页中间稿生成 PDF bundle 稿  
- `build_profile.py`、`update_profile.py` — **快速合并**建档 / 增量更新  
- `build_profile_sharded.py`、`update_profile_sharded.py` — **分期汇总**建档 / 增量更新  
- `md_to_pdf.py` — Markdown → PDF（无 pandoc 时的回退路径）  
- `generate_brief.py` — 复诊简报及配图、PDF  

**仅被引用的库模块**（无独立 `__main__` CLI）：

- `config.py`、`vision_parse_common.py`、`intermediate_qc.py`、`profile_merge_state.py`

## 发布包约束

- 发布包以文本类文件为主（`.md`、`.py`、`.json`、`.txt` 等）。
- 总大小不超过 **50MB**。
- 不包含密钥（API key、私密配置、token）。
- 用 `.clawhubignore` 排除本地产物（已含 `.venv/`、`__pycache__/`、`.DS_Store`、构建输出等）。

## 命名与版本

- `version` 须为 semver（`MAJOR.MINOR.PATCH`），例如 `1.0.0`。
- ClawHub slug / 目录名宜为 URL 安全字符（`^[a-z0-9][a-z0-9-]*$`）。
- 若 ClawHub 不接受下划线目录名，可改用连字符目录名发布，例如 `aura-health-profile`。

## 2）发布前校验（推荐）

在技能根目录（`aura_health_profile/`）执行：

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

并人工确认：

- `SKILL.md` 与 `SKILL_CN.md` 的 frontmatter 中 `description`、`version`、`author`、`metadata.openclaw.homepage`（若已设置）一致。
- `CHANGELOG.md` 与 `CHANGELOG_CN.md` 的最新一节与待发布 `version` 一致。
- `README.md` / `README_CN.md` 中的能力描述与当前实现一致（模式一至三、PDF 流程、快速合并与分期汇总、简报产物等）。
- `requirements.txt` 与 `scripts/` 下实际 import 一致（如 `requests`、`mistune`、`reportlab`、`pymupdf`）。
- `scripts/` 与文档中无密钥残留；`.clawhubignore` 仍排除 `.venv/` 与本机构建产物。

## 3）发布到 GitHub

若目录尚未初始化 git：

```bash
cd /path/to/aura_health_profile
git init
git add .
git commit -m "Initial release: aura health profile skill"
git branch -M main
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```

后续版本：

```bash
git add .
git commit -m "Release vX.Y.Z"
git tag vX.Y.Z
git push origin main --tags
```

仓库公开后：

- 替换 `README.md` / `README_CN.md` 中仍存在的 GitHub 占位链接（仓库、Issue、PR 等）。
- 确认 `SKILL.md` 与 `SKILL_CN.md` 的 `metadata.openclaw.homepage` 指向公开仓库 URL（若无则添加，并与 `README*` 一致）。

## 4）发布到 ClawHub

先安装并登录（见 [OpenClaw 文档](https://docs.openclaw.ai/tools/clawhub)）。

```bash
clawhub login
cd /path/to/aura_health_profile   # 含 SKILL.md 的目录
clawhub skill publish . --version X.Y.Z
```

注意：

- 每次发布前提升版本号，并保持 git 标签与 ClawHub 版本一致。
- 若 CLI 支持，正式发布前可先 dry-run / 校验。
- 若因 slug 命名发布失败，从连字符目录名重试。

## 5）发布一致性检查清单

对外宣布发布前，确认：

- Git 标签 `vX.Y.Z` 存在，且与 `SKILL*.md` 的 `version` 一致。
- ClawHub 已发布版本亦为 `X.Y.Z`。
- README 链接与 GitHub 占位内容已更新。
- `CHANGELOG.md`、`CHANGELOG_CN.md` 与 GitHub Release 说明已概括用户可见变更。
