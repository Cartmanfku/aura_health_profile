---
name: aura_health_profile
description: "**将繁琐的病历管理，变为安心的日常陪伴。** 一款专为慢性病患者设计的智能健康助手技能，基于阿里云百炼 Qwen 与 Wan 模型，帮你把散乱的化验单、病历、药盒说明变成清晰易懂的健康档案与复诊简报。"
version: 1.0.0
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
---

# Aura Health Profile

Chronic-care workflow: **parse images → structured records + metrics → full profile MD/PDF → revisit brief (profile-based summary to MD/PDF + styled image)**. Prefer running the shipped Python scripts under `{baseDir}/scripts/` rather than reimplementing API calls ad hoc.

## Prerequisites and setup

**What you need**

- **Python 3** and the packages in `{baseDir}/requirements.txt` (installed via the commands below).
- **PDF (optional but recommended)** — When exporting Markdown to PDF, prefer this order: **(1)** the **pdf-generator** skill if it is installed in the agent (use it per that skill’s instructions); **(2)** [pandoc](https://pandoc.org) on `PATH` (not a Python package — install the binary separately, e.g. macOS: `brew install pandoc`); **(3)** `{baseDir}/scripts/md_to_pdf.py`, which uses pandoc when available and otherwise **fpdf2** from `requirements.txt`. For Chinese/CJK and complex Markdown, prefer (1) or (2) over the fpdf2 fallback inside (3).
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

## Paths

| Role | Path |
|------|------|
| Intermediate MD (per image) | `~/.aura-health/intermediate/{date}_{type}_{hash8}.md` |
| Time-series metrics | `~/.aura-health/metrics.json` |
| Processed image hashes (incremental) | `~/.aura-health/processed.json` |
| Last build/update QC (JSON) | `~/.aura-health/last_profile_qc.json` |
| Profile merge state (update mode) | `~/.aura-health/profile_merge_state.json` |
| Full profile MD/PDF | `~/Documents/AuraHealth/health_profile_YYYYMMDD.md` and `.pdf` |
| Brief assets | `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.md`, `~/Documents/AuraHealth/brief_YYYYMMDD.png`, `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.pdf` |

Ensure `~/Documents/AuraHealth/` and `~/.aura-health/` exist before writing outputs.

## Skill bundle layout

- `{baseDir}/SKILL.md` — this file (canonical metadata for ClawHub)  
- `{baseDir}/SKILL_CN.md` — Simplified Chinese mirror  
- `{baseDir}/ONBOARD.md`, `{baseDir}/README.md`, `{baseDir}/PUBLISHING.md`, `{baseDir}/LICENSE` — onboarding and human docs; `LICENSE` is MIT-0  
- `{baseDir}/requirements.txt` — Python dependencies (`pip` / venv)  
- `{baseDir}/.clawhubignore` — paths excluded from ClawHub zip publish  
- `{baseDir}/scripts/` — shipped: `config.py`, `vision_parser.py`, `intermediate_qc.py`, `build_profile.py`, `update_profile.py`, `profile_merge_state.py`, `md_to_pdf.py`, `generate_brief.py`  
- `{baseDir}/references/medical_reference.md`, `{baseDir}/references/medical_reference_cn.md` — English / Simplified Chinese normalization hints  
- `{baseDir}/assets/profile_template.md`, `{baseDir}/assets/profile_template_cn.md`, `{baseDir}/assets/brief_template.md`, `{baseDir}/assets/brief_template_cn.md` — profile / brief templates (EN + zh-CN)  

When consolidating with the model, choose localized assets by preferred language (`zh-CN` → `*_cn.md`; otherwise default English). Fallback to English files if localized files are missing.

## Mode 1 — Build full profile (`build`)

**Trigger:** First-time use, or the user asks to rebuild or initialize the medical record.

1. **Parse images**  
   - Scan the user-given directory for `.jpg` / `.jpeg` / `.png`.  
   - For each file, call Qwen 3.6 Plus to extract structured text.  
   - Write one intermediate file per image under `~/.aura-health/intermediate/` using the naming pattern above.  
   - Append extracted numeric lab metrics to `~/.aura-health/metrics.json` (time-ordered).  
   - Record content hashes in `~/.aura-health/processed.json` to support later incremental runs.  
   - Implementation: `{baseDir}/scripts/vision_parser.py` (user supplies input directory). The script **writes `processed.json` and `metrics.json` to disk every `--batch-size` image(s)** (default `5`) so API rate limits or timeouts lose at most one batch; use `--batch-size 1` for maximum safety. **Progress** (total count, completed count, new writes this run, estimated time remaining) is printed to **stderr**; paths of new intermediate `.md` files stay on **stdout**. **`--quiet`** suppresses the progress lines (batch saves still run). **Ctrl+C** saves state before exit.

   **Runnable commands** :

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/folder/with/photos"
   ```

   Include subfolders:

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py --recursive "/absolute/path/to/folder/with/photos"
   ```

   Optional: `--force` re-parse even if the image hash is already in `processed.json`; `--model MODEL` overrides the vision model (default `qwen3.6-plus`, env `AURA_VISION_MODEL`); `--batch-size N` flush state every *N* images (default `5`); `--quiet` hide progress/ETA on stderr.

2. **Merge into full Markdown**  
   - Read all `~/.aura-health/intermediate/*.md`.  
   - Call Qwen 3.6 Plus with `{baseDir}/assets/profile_template.md` to produce one chronological, de-duplicated profile.  
   - Save as `~/Documents/AuraHealth/health_profile_YYYYMMDD.md`.  
   - Writes `~/.aura-health/profile_merge_state.json` for later incremental updates.  
   - Implementation: `{baseDir}/scripts/build_profile.py`. Before calling the model, it runs **QC** on `~/.aura-health/intermediate/*.md`: files that are **duplicates** (same source-image sha256 as an earlier file, or same normalized text as an earlier file) or **abnormal** (missing sha header, too short, missing required sections, heavy replacement characters, etc.) are **excluded** from the merge and listed in `~/.aura-health/last_profile_qc.json` and in a **Build QC** table appended to the output Markdown. Only passing files are sent to the model; merge state records **included** source hashes only.

   **Runnable commands** :

   ```bash
   ./.venv/bin/python3 scripts/build_profile.py
   ```

   The script prints the path of the new Markdown file (default filename uses **today’s local date** as `YYYYMMDD`).

   Fix the output date explicitly:

   ```bash
   ./.venv/bin/python3 scripts/build_profile.py --date 20260413
   ```

   Optional: `--model MODEL` overrides the text model (default `qwen3.6-plus`, env `AURA_TEXT_MODEL`).

3. **PDF**  
   - Convert the Markdown from step 2 to `~/Documents/AuraHealth/health_profile_YYYYMMDD.pdf` (or the path you choose). **Order of preference:** **(1)** If the **pdf-generator** skill is installed, use it for this Markdown → PDF step. **(2)** Else if `pandoc` is on `PATH`, run pandoc on the `.md` file (e.g. `pandoc … -o …pdf`). **(3)** Else run `{baseDir}/scripts/md_to_pdf.py`, which uses pandoc when available and otherwise **fpdf2** (best for Latin; for Chinese/CJK or complex layout, prefer (1) or (2) or install [pandoc](https://pandoc.org)).

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

1. **Parse only new images** (hash not in `processed.json`); append new intermediate MD and update `metrics.json` / `processed.json`. Same script as Mode 1 step 1: `{baseDir}/scripts/vision_parser.py` (same batch saves, stderr progress, `--batch-size`, `--quiet`, and interrupt handling as above).

   **Runnable commands**  point at the folder that contains the **new** photos (or the same folder as before—only unseen files are processed):

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py "/absolute/path/to/folder/with/new/photos"
   ```

   Include subfolders:

   ```bash
   ./.venv/bin/python3 scripts/vision_parser.py --recursive "/absolute/path/to/folder/with/new/photos"
   ```

   Optional: `--force` re-parses even when the image hash is already in `processed.json`; `--model MODEL` overrides the vision model (default `qwen3.6-plus`, env `AURA_VISION_MODEL`); `--batch-size N`; `--quiet`.

2. **Re-merge**  
   - Load the **latest** `~/Documents/AuraHealth/health_profile_*.md` (by date in the filename) plus **new** intermediate files under `~/.aura-health/intermediate/` .  
   - Qwen re-orders, deduplicates, and normalizes format.  
   - Write a new `health_profile_YYYYMMDD.md` and refresh merge state.  
   - Implementation: `{baseDir}/scripts/update_profile.py`. The same **QC** as `build_profile.py` applies to **candidate new** files (not the baseline profile); excluded files are reported in `~/.aura-health/last_profile_qc.json` (label `update`) and appended to the output Markdown. Merge state is updated as **previous merged hashes ∪ hashes from included new files**.

   **Runnable commands**  after step 1 added new intermediates and a baseline profile exists under `~/Documents/AuraHealth/`:

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

3. **PDF** — Same priority as **Mode 1 — step 3**: pdf-generator skill → pandoc → `md_to_pdf.py`, using the Markdown path from step 2 (`update_profile.py` output or `~/Documents/AuraHealth/health_profile_YYYYMMDD.md`). Runnable examples for `md_to_pdf.py` — see **Mode 1 — step 3** above.


## Mode 3 — Revisit brief (`brief`)

**Bundle status:** This mode is available in this package via `{baseDir}/scripts/generate_brief.py`.

**Trigger:** User needs a short summary before a doctor visit.

1. **Summary card**  
   - Read latest full profile MD.  
   - Qwen summarizes using `{baseDir}/assets/brief_template.md` into one brief markdown: `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.md`.

2. **Styled brief image + PDF (same source content)**  
   - Use the generated brief markdown as the single source.  
   - Wan 2.7 renders a styled image with sectioned layout, key-item highlights, and lightweight indicator visualization → `~/Documents/AuraHealth/brief_YYYYMMDD.png`.  
   - Convert the same markdown to PDF → `~/Documents/AuraHealth/revisit_brief_YYYYMMDD.pdf` (via `{baseDir}/scripts/md_to_pdf.py` inside the orchestrator).
   - Implementation entry: `{baseDir}/scripts/generate_brief.py`.

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

   Optional: `--text-model MODEL` (default `qwen3.6-plus`), `--image-model MODEL` (default `wan2.7-image-pro`), `--size 1024*1024`, `--timeout SEC`.

## Agent execution notes

- **Choose mode** from user intent: full rebuild vs new images only vs revisit brief.  
- **Do not** put API keys in chat logs; rely on env or `~/.aura-health/config.json`.  
- **Idempotency:** incremental parsing must skip hashes already listed in `processed.json`.  
- **PDF export:** when producing the health-profile PDF from Markdown, try in order: **(1)** installed **pdf-generator** skill, **(2)** **pandoc** CLI if on `PATH`, **(3)** `{baseDir}/scripts/md_to_pdf.py`.  
- **Safety:** medical content is user-supplied documentation assistance only—not a diagnosis. Keep disclaimers in user-facing outputs if templates include them.

## OpenClaw install hint

Copy or symlink the `aura_health_profile/` skill directory into the agent workspace `skills/` (or another path configured in `skills.load.extraDirs`), then start a new session so `openclaw skills list` shows `aura_health_profile`. For ClawHub, the publish slug may need a hyphenated folder name — see `{baseDir}/PUBLISHING.md`. Chinese readers: `{baseDir}/SKILL_CN.md`.
