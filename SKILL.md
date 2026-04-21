---
name: aura_health_profile(奥拉健康档案)
description: "**将繁琐的病历管理，变为安心的日常陪伴。** 一款专为慢性病患者设计的智能健康助手技能，基于阿里云百炼 Qwen 与 Wan 模型，帮你把散乱的化验单、病历、药盒说明变成清晰易懂的健康档案与复诊简报。"
version: 1.1.0
author: cartman
metadata:
  openclaw:
    emoji: ""
    requires:
      bins:
        - python3
      env:
        - DASHSCOPE_API_KEY
        - AURA_VISION_MODEL
        - AURA_TEXT_MODEL
        - AURA_STATE_HOME
        - AURA_OUTPUT_DIR
      config:
        - ~/.aura-health/config.json
    primaryEnv: DASHSCOPE_API_KEY
    homepage: https://github.com/Cartmanfku/aura_health_profile
---

# Aura Health Profile

Chronic-care workflow: **parse images and PDF pages → structured records + metrics → full profile MD/PDF → revisit brief (profile-based summary to MD/PDF + styled image)**. Prefer running the shipped Python scripts under `{baseDir}/scripts/` rather than reimplementing API calls ad hoc.

## Prerequisites and setup

**What you need**

- **Python 3** and the packages in `{baseDir}/requirements.txt` (installed via the commands below).
- **PDF (optional but recommended)** — When exporting Markdown to PDF, prefer this order: **(1)** the **pdf-generator** skill if it is installed in the agent (use it per that skill’s instructions); **(2)** [pandoc](https://pandoc.org) on `PATH` (not a Python package — install the binary separately, e.g. macOS: `brew install pandoc`); **(3)** `{baseDir}/scripts/md_to_pdf.py`, which uses pandoc when available and otherwise **mistune + ReportLab** (parses Markdown to an AST and lays out PDF directly; embeds CJK when a system font is found or when `AURA_PDF_FONT` points to a `.ttf`/`.ttc`). For the richest Markdown features, prefer (1) or (2).
- **DashScope API key** (Alibaba Cloud Bailian / Model Studio), read by `{baseDir}/scripts/config.py`:  
  - Preferred: `export DASHSCOPE_API_KEY="sk-..."`  
  - Or: `~/.aura-health/config.json` with `{ "dashscope_api_key": "sk-..." }`
- **Preferred profile language (optional)** for `build_profile.py` / `update_profile.py`:  
  - Environment: `AURA_USER_LANGUAGE=zh-CN` (or `AURA_PROFILE_LANGUAGE=zh-CN`) to force Simplified Chinese output  
  - Or config: `~/.aura-health/config.json` with `"preferred_language": "zh-CN"` (also accepts `"common_language"` / `"language"`)
- **Models (reference)**  
  - Vision / text: OpenAI-compatible chat completions — `qwen3.6-plus` at `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`  
  - Image generation (Mode 3): `wan2.7-image-pro` at `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`

**First-time install** — follow `ONBOARD.md` from the skill root `{baseDir}` (folder containing `SKILL.md` and `scripts/`).

`ONBOARD.md` covers environment checks, API-key setup + connectivity verification, PDF tool selection, preferred language configuration, and post-setup examples.

## Build mode selection

Choose one mode before running merge scripts (parse scripts are the same in both modes):

- **Quick Merge mode (default)**  
  - Scripts: `build_profile.py` / `update_profile.py`  
  - Use when records are limited in size and timeline span.
- **Staged Summary mode**  
  - Scripts: `build_profile_sharded.py` / `update_profile_sharded.py`  
  - Use when records accumulate over long periods (for example multi-year history, many PDFs, or very large intermediate sets).

Quick rule of thumb: if intermediate files are numerous (for example, >50) or cover many years, prefer **Staged Summary mode**.

## Paths

| Role | Path |
|------|------|
| Intermediate MD (per raster image or PDF page) | `~/.aura-health/intermediate/{date}_{type}_{hash8}.md` |
| Time-series metrics | `~/.aura-health/metrics.json` |
| Processed content hashes (incremental; whole image file, or per-PDF-page digest) | `~/.aura-health/processed.json` |
| Last build/update QC (JSON) | `~/.aura-health/last_profile_qc.json` |
| Profile merge state (update mode) | `~/.aura-health/profile_merge_state.json` |
| Full profile MD/PDF | `~/Documents/AuraHealth/health_profile_YYYYMMDD.md` and `.pdf` |
| Brief assets | `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.md`, `~/Documents/AuraHealth/brief_YYYYMMDD.png` (doctor-facing styled sheet), `~/Documents/AuraHealth/brief_user_comic_YYYYMMDD.png` (6–9 panel lay-language comic), `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.pdf` |

Ensure `~/Documents/AuraHealth/` and `~/.aura-health/` exist before writing outputs.

## Skill bundle layout

- `{baseDir}/SKILL.md` — this file (canonical metadata for ClawHub)  
- `{baseDir}/SKILL_CN.md` — Simplified Chinese mirror  
- `{baseDir}/ONBOARD.md`, `{baseDir}/README.md`, `{baseDir}/PUBLISHING.md`, `{baseDir}/PUBLISHING_CN.md`, `{baseDir}/CHANGELOG.md`, `{baseDir}/CHANGELOG_CN.md`, `{baseDir}/LICENSE` — onboarding, publishing, changelog, and license; `LICENSE` is MIT-0  
- `{baseDir}/requirements.txt` — Python dependencies (`pip` / venv)  
- `{baseDir}/.clawhubignore` — paths excluded from ClawHub zip publish  
- `{baseDir}/scripts/` — shipped: `config.py`, `vision_parse_common.py`, `vision_parser.py`, `pdf_vision_parser.py`, `pdf_bundle_builder.py`, `intermediate_qc.py`, `build_profile.py`, `build_profile_sharded.py`, `update_profile.py`, `update_profile_sharded.py`, `profile_merge_state.py`, `md_to_pdf.py`, `generate_brief.py`  
- `{baseDir}/references/medical_reference.md`, `{baseDir}/references/medical_reference_cn.md` — English / Simplified Chinese normalization hints  
- `{baseDir}/assets/profile_template.md`, `{baseDir}/assets/profile_template_cn.md`, `{baseDir}/assets/brief_template.md`, `{baseDir}/assets/brief_template_cn.md` — profile / brief templates (EN + zh-CN)  

When consolidating with the model, choose localized assets by preferred language (`zh-CN` → `*_cn.md`; otherwise default English). Fallback to English files if localized files are missing.

## Mode 1 — Build full profile (`build`)

**Trigger:** First-time use, or the user asks to rebuild or initialize the medical record.

1. **Parse inputs (images vs PDFs — two scripts)**  
   - **Raster images** (`.jpg` / `.jpeg` / `.png` / `.webp`): `{baseDir}/scripts/vision_parser.py`. Each file → one intermediate Markdown. **`processed.json` + `metrics.json` are flushed every `--batch-size` image(s)** (default `5`; use `1` to minimize loss if the process stops mid-folder). Each successful image writes its `.md` **before** the next flush; if a later image fails, earlier `.md` files remain on disk. If the process dies after writing an `.md` but before the next flush, the next run still skips those sources because `vision_parse_common.load_existing_intermediate_hashes()` rescans comment headers. **Ctrl+C** flushes current state.  
   - **PDF reports** (`.pdf`): `{baseDir}/scripts/pdf_vision_parser.py`. **PyMuPDF** rasterizes each page; **one Markdown per page**. After **each successful page**, the script writes that page’s `.md` and **immediately flushes** `processed.json` and `metrics.json`, so a failure on a later page does not lose completed pages—re-run without `--force` to resume only missing pages. **Document date and document type** are taken from **page 1** (cover) and written consistently into every page’s `## Document metadata` block (inner pages are normalized to match). Prompts and RGB rendering aim to reduce garbled Chinese. For long reports, the parser can also build a compressed PDF bundle (`--bundle-threshold-pages`, `--bundle-chunk-pages`; disable via `--no-bundle`), and profile merge can prefer bundles via `build_profile.py --pdf-input-mode auto|bundle`.

   **Images — runnable commands** :

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/folder/with/photos"
   ```

   Include subfolders:

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py --recursive "/absolute/path/to/folder/with/photos"
   ```

   Optional: `--force`; `--model MODEL` (env `AURA_VISION_MODEL`); `--batch-size N`; `--quiet`.

   **PDFs — runnable commands** :

   ```bash
   ./.venv/bin/python3 scripts/pdf_vision_parser.py "/absolute/path/to/folder/with/pdfs"
   ```

   ```bash
   ./.venv/bin/python3 scripts/pdf_vision_parser.py --recursive "/absolute/path/to/folder/with/pdfs"
   ```

   Optional: `--force`; `--model MODEL`; `--pdf-zoom Z`; `--quiet`.

2. **Merge into full Markdown**  
   - Both scripts generate `health_profile_YYYYMMDD.md` and update merge state.
   - **Important:** this step does not auto-export PDF; PDF conversion is step 3.

   **Quick Merge mode (`build_profile.py`)**
   - Reads all `~/.aura-health/intermediate/*.md` and performs one direct merge.
   - Runs **QC** before model call; duplicate/abnormal intermediates are excluded and reported in `~/.aura-health/last_profile_qc.json` and the output Markdown.

   **Runnable commands (Quick Merge mode)** :

   ```bash
   ./.venv/bin/python3 scripts/build_profile.py
   ```

   The script prints the path of the new Markdown file (default filename uses **today’s local date** as `YYYYMMDD`).

   Fix the output date explicitly:

   ```bash
   ./.venv/bin/python3 scripts/build_profile.py --date 20260413
   ```

  Optional: `--model MODEL` overrides the text model (default `qwen3.6-plus`, env `AURA_TEXT_MODEL`).

   **Staged Summary mode (`build_profile_sharded.py`)**
   - Uses half-year shard summaries first, then final merge.
   - Also writes shard artifacts under `~/.aura-health/period_summaries/period_profile_YYYYH1.md` / `period_profile_YYYYH2.md` (and possibly `period_profile_undated.md`).

   **Runnable commands (Staged Summary mode)**:

   ```bash
   ./.venv/bin/python3 scripts/build_profile_sharded.py
   ```

   Useful options: `--shard-mode half-year` (`year` is deprecated and auto-normalized to `half-year`); `--shard-max-chars N`; `--pdf-input-mode auto|raw|bundle`; `--pdf-bundle-threshold-pages N`; `--date YYYYMMDD`.

3. **PDF**  
   - Convert the Markdown from step 2 to `~/Documents/AuraHealth/health_profile_YYYYMMDD.pdf` (or the path you choose). **Order of preference:** **(1)** If the **pdf-generator** skill is installed, use it for this Markdown → PDF step. **(2)** Else if `pandoc` is on `PATH`, run pandoc on the `.md` file (e.g. `pandoc … -o …pdf`). **(3)** Else run `{baseDir}/scripts/md_to_pdf.py`, which uses pandoc when available and otherwise **mistune + ReportLab** (CJK via system font or `AURA_PDF_FONT`; for the richest layout, prefer (1) or (2) or install [pandoc](https://pandoc.org)).

   **Runnable commands** (when using step **(3)** — `md_to_pdf.py`) use the `.md` path printed by `build_profile.py`, or build it from today’s date:

   ```bash
   ./.venv/bin/python3 scripts/md_to_pdf.py \
     "$HOME/Documents/AuraHealth/health_profile_$(date +%Y%m%d).md"
   ```

   With no second argument, the PDF is written next to the Markdown with the same basename (e.g. `health_profile_20260413.pdf`).

   Explicit input and output paths:

   ```bash
   ./.venv/bin/python3 scripts/md_to_pdf.py \
     "$HOME/Documents/AuraHealth/health_profile_20260413.md" \
     "$HOME/Documents/AuraHealth/health_profile_20260413.pdf"
   ```

   The script prints the PDF path on success.

## Mode 2 — Incremental update (`update`)

**Trigger:** User adds new images.

1. **Parse only new images or new PDF pages** (hash not in `processed.json`); append intermediate MD and update `metrics.json` / `processed.json`. Use `{baseDir}/scripts/vision_parser.py` for new images and `{baseDir}/scripts/pdf_vision_parser.py` for new PDFs (same resume and flush semantics as Mode 1 step 1).

   **New images** :

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/folder/with/new/photos"
   ./.venv/bin/python3 scripts/vision_parser.py --recursive "/absolute/path/to/folder/with/new/photos"
   ```

   **New PDFs** :

   ```bash
   ./.venv/bin/python3 scripts/pdf_vision_parser.py "/absolute/path/to/folder/with/new/pdfs"
   ./.venv/bin/python3 scripts/pdf_vision_parser.py --recursive "/absolute/path/to/folder/with/new/pdfs"
   ```

   Optional: `--force`; `--model MODEL`; for images also `--batch-size N`, `--quiet`; for PDFs also `--pdf-zoom Z`, `--quiet`.

2. **Re-merge**  
   - Both update scripts load a baseline profile plus new intermediates, then write a new `health_profile_YYYYMMDD.md`.
   - **Important:** this step does not auto-export PDF; PDF conversion is step 3.

   **Quick Merge mode (`update_profile.py`)**
   - Uses merge state to pick new, not-yet-merged sources.
   - Applies **QC** to current candidate new intermediates; exclusions are recorded in `~/.aura-health/last_profile_qc.json` (`label=update`).

   **Runnable commands (Quick Merge mode)** after step 1 added new intermediates and a baseline profile exists under `~/Documents/AuraHealth/`:

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py
   ```

   The script prints the path of the new Markdown file (default **today’s local** `YYYYMMDD` in the filename). If there is nothing new to merge, it exits after a short message.

   Set the output date explicitly:

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py --date 20260413
   ```

   Use a specific baseline profile instead of the latest `health_profile_*.md`:

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py \
     --profile "$HOME/Documents/AuraHealth/health_profile_20260101.md"
   ```

   Re-send **all** intermediates to the model for a full reconcile (higher token use):

   ```bash
   ./.venv/bin/python3 scripts/update_profile.py --full
   ```

   Optional: `--model MODEL` overrides the text model (default `qwen3.6-plus`, env `AURA_TEXT_MODEL`).

   **Staged Summary mode (`update_profile_sharded.py`)**
   - Rebuilds only impacted time shards, then runs final merge.
   - Reuses/updates shard artifacts under `~/.aura-health/period_summaries/period_profile_YYYYH1.md`, `period_profile_YYYYH2.md` (and possibly `period_profile_undated.md`).

   **Runnable commands (Staged Summary mode)**:

   ```bash
   ./.venv/bin/python3 scripts/update_profile_sharded.py
   ```

   Useful options: `--shard-mode half-year` (`year` is deprecated and auto-normalized to `half-year`); `--shard-max-chars N`; `--pdf-input-mode auto|raw|bundle`; `--pdf-bundle-threshold-pages N`; `--full`; `--profile PATH`; `--date YYYYMMDD`.

3. **PDF** — Same priority as **Mode 1 — step 3**: pdf-generator skill → pandoc → `md_to_pdf.py`, using the Markdown path from step 2 (`update_profile.py` or `update_profile_sharded.py` output, or `~/Documents/AuraHealth/health_profile_YYYYMMDD.md`). Runnable examples for `md_to_pdf.py` — see **Mode 1 — step 3** above.


## Mode 3 — Revisit brief (`brief`)

**Bundle status:** This mode is available in this package via `{baseDir}/scripts/generate_brief.py`.

**Trigger:** User needs a short summary before a doctor visit.

1. **Summary card**  
   - Read latest full profile MD.  
   - Qwen summarizes using `{baseDir}/assets/brief_template.md` into one brief markdown: `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.md`.

2. **Styled brief image + lay-language comic + PDF (same textual source)**  
   - Use the generated brief markdown as the single source.  
   - Wan 2.7 renders a **doctor-facing** styled one-pager (clinical layout, professional terminology preserved) → `~/Documents/AuraHealth/brief_YYYYMMDD.png`.  
   - Qwen then derives a **6–9 panel** plain-language comic storyboard from the same brief; Wan renders it for patients/families → `~/Documents/AuraHealth/brief_user_comic_YYYYMMDD.png`.  
   - Convert the same markdown to PDF → `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.pdf` (via `{baseDir}/scripts/md_to_pdf.py` inside the orchestrator).
   - Implementation entry: `{baseDir}/scripts/generate_brief.py`. Pass `--skip-user-comic` (or set `AURA_BRIEF_SKIP_USER_COMIC=1`) to skip the second Wan call.

   **Runnable command** (default: latest `health_profile_*.md`, today date):

   ```bash
   ./.venv/bin/python3 scripts/generate_brief.py
   ```

   Use a specific profile and date:

   ```bash
   ./.venv/bin/python3 scripts/generate_brief.py \
     --profile "$HOME/Documents/AuraHealth/health_profile_20260413.md" \
     --date 20260414
   ```

   Optional: `--text-model MODEL` (default `qwen3.6-plus`), `--image-model MODEL` (default `wan2.7-image-pro`), `--size 1024*1024`, `--comic-size 1024*1792`, `--timeout SEC`, `--skip-user-comic`.

## Agent execution notes

- **Choose mode** from user intent: full rebuild vs new images only vs revisit brief.  
- **Do not** put API keys in chat logs; rely on env or `~/.aura-health/config.json`.  
- **Idempotency:** incremental parsing must skip hashes already listed in `processed.json`.  
- **PDF export:** when producing the health-profile PDF from Markdown, try in order: **(1)** installed **pdf-generator** skill, **(2)** **pandoc** CLI if on `PATH`, **(3)** `{baseDir}/scripts/md_to_pdf.py`.  
- **Safety:** medical content is user-supplied documentation assistance only—not a diagnosis. Keep disclaimers in user-facing outputs if templates include them.

## OpenClaw install hint

Copy or symlink the `aura_health_profile/` skill directory into the agent workspace `skills/` (or another path configured in `skills.load.extraDirs`), then start a new session so `openclaw skills list` shows `aura_health_profile`. For ClawHub, the publish slug may need a hyphenated folder name — see `{baseDir}/PUBLISHING.md` (Chinese: `{baseDir}/PUBLISHING_CN.md`). Chinese skill text: `{baseDir}/SKILL_CN.md`.
