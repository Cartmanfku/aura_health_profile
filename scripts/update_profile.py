#!/usr/bin/env python3
"""Incremental merge: latest health_profile_*.md + new intermediate MD → new profile."""

from __future__ import annotations

import argparse
import re
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
from pdf_bundle_builder import choose_intermediates_for_profile
from profile_merge_state import (
    load_merge_state,
    list_new_intermediate_paths,
    merged_shas_from_paths,
    save_merge_state,
)


def _find_latest_profile(root: Path) -> Path | None:
    """Pick health_profile_YYYYMMDD.md with greatest YYYYMMDD; tie-break by mtime."""
    best: Path | None = None
    best_ymd = ""
    for p in root.glob("health_profile_*.md"):
        m = re.fullmatch(r"health_profile_(\d{8})", p.stem)
        ymd = m.group(1) if m else ""
        if best is None or ymd > best_ymd or (
            ymd == best_ymd and p.stat().st_mtime > best.stat().st_mtime
        ):
            best, best_ymd = p, ymd
    return best


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Update consolidated profile from the latest health_profile_*.md plus "
            "new intermediate files (or --full for all intermediates)."
        )
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
    parser.add_argument(
        "--profile",
        type=Path,
        help="Explicit baseline profile .md (default: latest health_profile_*.md)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Send all intermediate files to the model (reconcile with baseline profile)",
    )
    parser.add_argument(
        "--pdf-input-mode",
        choices=("auto", "raw", "bundle"),
        default="auto",
        help="How to feed PDF intermediates into merge (default: auto).",
    )
    parser.add_argument(
        "--pdf-bundle-threshold-pages",
        type=int,
        default=3,
        help="In auto mode, use bundle when PDF pages > N (default: 3).",
    )
    args = parser.parse_args()
    if args.pdf_bundle_threshold_pages < 1:
        raise SystemExit("--pdf-bundle-threshold-pages must be >= 1")

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

    baseline = args.profile.resolve() if args.profile else _find_latest_profile(OUTPUT_ROOT)
    if baseline is None or not baseline.is_file():
        raise SystemExit(
            f"No baseline profile found under {OUTPUT_ROOT} (health_profile_*.md). "
            "Run build_profile.py first, or pass --profile."
        )

    state = load_merge_state()
    known: set[str] = set()
    if state and isinstance(state.get("merged_source_sha256"), list):
        known = {str(x).lower() for x in state["merged_source_sha256"] if isinstance(x, str)}

    profile_mtime = baseline.stat().st_mtime
    new_paths = list_new_intermediate_paths(
        known_shas=known,
        profile_mtime=profile_mtime,
        full=args.full,
    )

    if state is None and not args.full:
        print(
            "Note: no profile_merge_state.json yet — every intermediate looks “new”. "
            "Run build_profile.py once to create merge state, or use --full explicitly.",
            file=sys.stderr,
        )

    if not new_paths:
        print(
            "No new intermediate files to merge. Run vision_parser.py (images) or "
            "pdf_vision_parser.py (PDFs) on new inputs first."
        )
        return
    merge_inputs, skipped_by_policy, policy_warnings = choose_intermediates_for_profile(
        new_paths,
        mode=args.pdf_input_mode,
        threshold_pages=args.pdf_bundle_threshold_pages,
    )
    for msg in policy_warnings:
        print(f"Bundle policy: {msg}", file=sys.stderr)
    if skipped_by_policy:
        print(
            f"Bundle policy skipped {len(skipped_by_policy)} candidate file(s).",
            file=sys.stderr,
        )
    if not merge_inputs:
        print(
            "No candidate files selected after PDF input policy "
            f"(mode={args.pdf_input_mode}).",
            file=sys.stderr,
        )
        return

    included, excluded = partition_intermediates(merge_inputs)
    for x in excluded:
        print(f"QC exclude {x.file}: {x.reason} ({x.detail})", file=sys.stderr)
    write_qc_artifact(
        path=AURA_STATE_HOME / "last_profile_qc.json",
        included=included,
        excluded=excluded,
        label="update",
    )
    if not included:
        print(
            "No usable new intermediate files after QC (all excluded as duplicate or abnormal). "
            f"See {AURA_STATE_HOME / 'last_profile_qc.json'}",
            file=sys.stderr,
        )
        return

    template = template_path.read_text(encoding="utf-8")
    reference = ""
    if ref_path.is_file():
        reference = ref_path.read_text(encoding="utf-8")

    baseline_text = baseline.read_text(encoding="utf-8")
    chunks = [f"### FILE: {p.name}\n\n{p.read_text(encoding='utf-8')}" for p in included]
    new_bundle = "\n\n---\n\n".join(chunks)

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
            "\n(Automated QC dropped some of the candidate new files (duplicate or invalid). "
            "Merge ONLY the new files listed below.)\n"
        )
        if use_chinese:
            qc_note = (
                "\n（自动 QC 已剔除部分候选新增文件：重复或结构异常。"
                "仅合并下方列出的新增文件。）\n"
            )

    language_rule = (
        "Output the final profile in Simplified Chinese (zh-CN)."
        if use_chinese
        else "Keep language consistent with the sources when reasonable."
    )

    user_msg = f"""You are updating an existing personal health profile with NEW intermediate records.

Rules:
- Start from the CURRENT PROFILE below as the source of truth for everything already merged.
- Integrate the NEW intermediate records: add missing facts, fix contradictions using the newer record when dates/sources conflict, and de-duplicate.
- Re-order chronologically where dates exist. Preserve qualifiers (e.g. fasting).
- {language_rule}
- Output ONE consolidated Markdown profile following the template structure.

Template (obey this outline):

{template}
{ref_block}

--- CURRENT PROFILE (baseline) ---

{baseline_text}

--- NEW intermediate records (merge these in) ---
{qc_note}
{new_bundle}

Output ONLY the final Markdown profile. No preamble."""

    messages = [
        {
            "role": "system",
            "content": "You update personal health records into a single clear Markdown document. You do not diagnose or prescribe.",
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

    merged_shas = known.union(merged_shas_from_paths(included))
    save_merge_state(
        last_profile_path=out_md,
        last_profile_ymd=ymd,
        merged_source_sha256=merged_shas,
    )
    print(out_md)


if __name__ == "__main__":
    main()
