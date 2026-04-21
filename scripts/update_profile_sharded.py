#!/usr/bin/env python3
"""Incremental update for sharded profile: recompute changed shards, then final merge."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from build_profile_sharded import (  # noqa: E402
    _build_shard_summary,
    _cleanup_legacy_yearly_period_profiles,
    _extract_doc_date,
    _final_merge,
    _normalize_shard_mode,
    _shard_key_from_date,
    _sort_shard_keys,
    _write_shard_markdown,
)
from config import (  # noqa: E402
    AURA_STATE_HOME,
    DEFAULT_TEXT_MODEL,
    INTERMEDIATE_DIR,
    OUTPUT_ROOT,
    ensure_state_dirs,
    preferred_language,
    skill_dir,
)
from intermediate_qc import (  # noqa: E402
    format_qc_markdown_section,
    partition_intermediates,
    write_qc_artifact,
)
from pdf_bundle_builder import choose_intermediates_for_profile  # noqa: E402
from profile_merge_state import (  # noqa: E402
    list_new_intermediate_paths,
    load_merge_state,
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


def _group_paths_by_shard(paths: list[Path], *, shard_mode: str) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for p in paths:
        doc_date = _extract_doc_date(p)
        key = _shard_key_from_date(doc_date, shard_mode=shard_mode)
        out.setdefault(key, []).append(p)
    for items in out.values():
        items.sort(key=lambda x: x.name)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Update consolidated profile using half-year time shards. "
            "Recomputes only changed shards unless --full."
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
        help="Recompute all shards from all selected intermediates.",
    )
    parser.add_argument(
        "--shard-mode",
        choices=("half-year", "year"),
        default="half-year",
        help="Shard granularity for intermediate records (year is deprecated; default: half-year).",
    )
    parser.add_argument(
        "--shard-max-chars",
        type=int,
        default=70000,
        help="Approximate max characters sent per shard sub-batch (default: 70000).",
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
    if args.shard_max_chars < 2000:
        raise SystemExit("--shard-max-chars must be >= 2000")
    if args.pdf_bundle_threshold_pages < 1:
        raise SystemExit("--pdf-bundle-threshold-pages must be >= 1")

    ensure_state_dirs()
    args.shard_mode = _normalize_shard_mode(args.shard_mode)
    removed_yearly = _cleanup_legacy_yearly_period_profiles()
    if removed_yearly:
        print(
            f"Removed {removed_yearly} legacy yearly period profile(s).",
            file=sys.stderr,
        )
    base = skill_dir()
    use_chinese = preferred_language() == "zh-CN"
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

    baseline = args.profile.resolve() if args.profile else _find_latest_profile(OUTPUT_ROOT)
    if baseline is None or not baseline.is_file():
        raise SystemExit(
            f"No baseline profile found under {OUTPUT_ROOT} (health_profile_*.md). "
            "Run build_profile_sharded.py first, or pass --profile."
        )

    intermediates = sorted(INTERMEDIATE_DIR.glob("*.md"))
    if not intermediates:
        raise SystemExit(f"No intermediate files in {INTERMEDIATE_DIR}")

    all_inputs, skipped_all, warnings_all = choose_intermediates_for_profile(
        intermediates,
        mode=args.pdf_input_mode,
        threshold_pages=args.pdf_bundle_threshold_pages,
    )
    for msg in warnings_all:
        print(f"Bundle policy: {msg}", file=sys.stderr)
    if skipped_all:
        print(
            f"Bundle policy skipped {len(skipped_all)} intermediate file(s) in full candidate set.",
            file=sys.stderr,
        )
    if not all_inputs:
        raise SystemExit("No intermediate files selected after PDF input policy.")
    included_all, excluded_all = partition_intermediates(all_inputs)
    if not included_all:
        qc_path = AURA_STATE_HOME / "last_profile_qc.json"
        write_qc_artifact(
            path=qc_path,
            included=included_all,
            excluded=excluded_all,
            label="update_sharded",
        )
        raise SystemExit(
            "No usable intermediate files after QC (all excluded as duplicate or abnormal). "
            f"See {qc_path} for details."
        )

    report_included: list[Path] = included_all
    report_excluded = excluded_all
    changed_candidates: list[Path] = included_all if args.full else []

    if not args.full:
        state = load_merge_state()
        known: set[str] = set()
        if state and isinstance(state.get("merged_source_sha256"), list):
            known = {
                str(x).lower()
                for x in state["merged_source_sha256"]
                if isinstance(x, str)
            }

        profile_mtime = baseline.stat().st_mtime
        new_paths = list_new_intermediate_paths(
            known_shas=known,
            profile_mtime=profile_mtime,
            full=False,
        )
        if state is None:
            print(
                "Note: no profile_merge_state.json yet — every intermediate may look new. "
                "Consider running with --full once.",
                file=sys.stderr,
            )
        if not new_paths:
            print(
                "No new intermediate files to merge. Run vision_parser.py (images) or "
                "pdf_vision_parser.py (PDFs) on new inputs first."
            )
            return
        new_inputs, skipped_new, warnings_new = choose_intermediates_for_profile(
            new_paths,
            mode=args.pdf_input_mode,
            threshold_pages=args.pdf_bundle_threshold_pages,
        )
        for msg in warnings_new:
            print(f"Bundle policy(new): {msg}", file=sys.stderr)
        if skipped_new:
            print(
                f"Bundle policy skipped {len(skipped_new)} candidate new file(s).",
                file=sys.stderr,
            )
        if not new_inputs:
            print(
                "No candidate files selected after PDF input policy "
                f"(mode={args.pdf_input_mode}).",
                file=sys.stderr,
            )
            return
        included_new, excluded_new = partition_intermediates(new_inputs)
        report_included = included_new
        report_excluded = excluded_new
        if not included_new:
            qc_path = AURA_STATE_HOME / "last_profile_qc.json"
            write_qc_artifact(
                path=qc_path,
                included=report_included,
                excluded=report_excluded,
                label="update_sharded",
            )
            print(
                "No usable new intermediate files after QC (all excluded as duplicate or abnormal). "
                f"See {qc_path}",
                file=sys.stderr,
            )
            return
        all_included_set = set(included_all)
        changed_candidates = [p for p in included_new if p in all_included_set]
        if not changed_candidates:
            print(
                "No shard-impacting files remain after policy/QC filtering; nothing to update.",
                file=sys.stderr,
            )
            return

    qc_path = AURA_STATE_HOME / "last_profile_qc.json"
    write_qc_artifact(
        path=qc_path,
        included=report_included,
        excluded=report_excluded,
        label="update_sharded",
    )

    all_shards = _group_paths_by_shard(included_all, shard_mode=args.shard_mode)
    changed_shards = set(
        _group_paths_by_shard(changed_candidates, shard_mode=args.shard_mode).keys()
    )
    if args.full:
        changed_shards = set(all_shards.keys())

    shard_docs: list[tuple[str, Path]] = []
    for key in _sort_shard_keys(list(all_shards.keys())):
        shard_doc = AURA_STATE_HOME / "period_summaries" / f"period_profile_{key}.md"
        should_rebuild = args.full or key in changed_shards or (not shard_doc.is_file())
        if should_rebuild:
            summary = _build_shard_summary(
                shard_key=key,
                paths=all_shards[key],
                model=args.model,
                use_chinese=use_chinese,
                shard_max_chars=args.shard_max_chars,
            )
            shard_doc = _write_shard_markdown(shard_key=key, text=summary)
            print(f"Rebuilt shard: {shard_doc}", file=sys.stderr)
        shard_docs.append((key, shard_doc))

    template = template_path.read_text(encoding="utf-8")
    reference = ref_path.read_text(encoding="utf-8") if ref_path.is_file() else ""
    final_text = _final_merge(
        template=template,
        reference=reference,
        shard_docs=shard_docs,
        model=args.model,
        use_chinese=use_chinese,
    )

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
        disclaimer + final_text.lstrip() + format_qc_markdown_section(report_excluded),
        encoding="utf-8",
    )
    save_merge_state(
        last_profile_path=out_md,
        last_profile_ymd=ymd,
        merged_source_sha256=merged_shas_from_paths(included_all),
    )
    print(out_md)


if __name__ == "__main__":
    main()
