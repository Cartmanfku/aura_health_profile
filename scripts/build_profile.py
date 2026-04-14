#!/usr/bin/env python3
"""Merge ~/.aura-health/intermediate/*.md into one profile via Qwen + template."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import (
    AURA_STATE_HOME,
    DEFAULT_TEXT_MODEL,
    OUTPUT_ROOT,
    INTERMEDIATE_DIR,
    chat_completions,
    ensure_state_dirs,
    preferred_language,
    skill_dir,
)
from intermediate_qc import (
    format_qc_markdown_section,
    partition_intermediates,
    write_qc_artifact,
)
from profile_merge_state import merged_shas_from_paths, save_merge_state


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build consolidated health_profile_YYYYMMDD.md from intermediate records."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_TEXT_MODEL,
        help=f"Text model (default: {DEFAULT_TEXT_MODEL})",
    )
    parser.add_argument(
        "--date",
        help="YYYYMMDD for output filename (default: today local)",
    )
    args = parser.parse_args()

    ensure_state_dirs()
    base = skill_dir()
    lang = preferred_language()
    use_chinese = lang == "zh-CN"
    template_path = (
        base / "assets" / "profile_template_cn.md"
        if use_chinese
        else base / "assets" / "profile_template.md"
    )
    ref_path = (
        base / "references" / "medical_reference_cn.md"
        if use_chinese
        else base / "references" / "medical_reference.md"
    )
    if not template_path.is_file():
        template_path = base / "assets" / "profile_template.md"
    if not ref_path.is_file():
        ref_path = base / "references" / "medical_reference.md"

    if not template_path.is_file():
        raise SystemExit(f"Missing template: {template_path}")

    intermediates = sorted(INTERMEDIATE_DIR.glob("*.md"))
    if not intermediates:
        raise SystemExit(f"No intermediate files in {INTERMEDIATE_DIR}")

    included, excluded = partition_intermediates(intermediates)
    for x in excluded:
        print(f"QC exclude {x.file}: {x.reason} ({x.detail})", file=sys.stderr)
    qc_path = AURA_STATE_HOME / "last_profile_qc.json"
    write_qc_artifact(
        path=qc_path,
        included=included,
        excluded=excluded,
        label="build",
    )
    if not included:
        raise SystemExit(
            "No usable intermediate files after QC (all excluded as duplicate or abnormal). "
            f"See {qc_path} for details; fix or remove files under intermediate/."
        )

    template = template_path.read_text(encoding="utf-8")
    reference = ""
    if ref_path.is_file():
        reference = ref_path.read_text(encoding="utf-8")

    chunks: list[str] = []
    for p in included:
        chunks.append(f"### FILE: {p.name}\n\n{p.read_text(encoding='utf-8')}")
    bundle = "\n\n---\n\n".join(chunks)

    ref_block = ""
    if reference.strip():
        ref_block = (
            "\n\nUse the following reference for standard lab names and units "
            "when normalizing:\n\n"
            + reference.strip()
        )
        if use_chinese:
            ref_block = (
                "\n\n归一化检验项目名称与单位时，可参考下列术语对照：\n\n"
                + reference.strip()
            )

    qc_note = ""
    if excluded:
        qc_note = (
            "\n(Automated QC dropped some intermediate files (duplicate image or duplicate text, "
            "or invalid structure). Use ONLY the files in this bundle as sources.)\n"
        )
        if use_chinese:
            qc_note = (
                "\n（自动 QC 已剔除部分中间文件：重复图片、重复文本或结构异常。"
                "仅可使用本次打包中列出的文件作为来源。）\n"
            )

    language_rule = (
        "Output the final profile in Simplified Chinese (zh-CN)."
        if use_chinese
        else (
            "Keep the same language as the sources when reasonable "
            "(e.g. Chinese stays Chinese unless translating improves clarity)."
        )
    )

    user_msg = f"""You will merge multiple intermediate Markdown records into ONE consolidated health profile.

Follow the structure and section headings in the template below. De-duplicate overlapping facts. Order content chronologically where dates exist. Preserve important qualifiers (e.g. fasting, postprandial). {language_rule}

Template (obey this outline):

{template}
{ref_block}

--- Intermediate records ---
{qc_note}
{bundle}

Output ONLY the final Markdown profile. No preamble."""

    messages = [
        {
            "role": "system",
            "content": "You consolidate personal health records into a single clear Markdown document. You do not diagnose or prescribe.",
        },
        {"role": "user", "content": user_msg},
    ]

    text = chat_completions(messages, model=args.model, max_tokens=16384)

    ymd = args.date or datetime.now().strftime("%Y%m%d")
    if not (ymd.isdigit() and len(ymd) == 8):
        raise SystemExit("--date must be YYYYMMDD")

    out_md = OUTPUT_ROOT / f"health_profile_{ymd}.md"
    disclaimer = (
        "> **免责声明：** 仅用于个人资料整理，不构成医疗建议。\n\n"
        if use_chinese
        else "> **Disclaimer:** For personal documentation only. Not medical advice.\n\n"
    )
    out_md.write_text(
        disclaimer + text.lstrip() + format_qc_markdown_section(excluded),
        encoding="utf-8",
    )
    save_merge_state(
        last_profile_path=out_md,
        last_profile_ymd=ymd,
        merged_source_sha256=merged_shas_from_paths(included),
    )
    print(out_md)


if __name__ == "__main__":
    main()
