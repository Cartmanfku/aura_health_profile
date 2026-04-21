#!/usr/bin/env python3
"""Build consolidated profile using half-year time shards to reduce context pressure."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import (  # noqa: E402
    AURA_STATE_HOME,
    DEFAULT_TEXT_MODEL,
    INTERMEDIATE_DIR,
    OUTPUT_ROOT,
    chat_completions,
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
    merged_shas_from_paths,
    save_merge_state,
)
from vision_parse_common import _parse_metadata  # noqa: E402

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNDATED_KEY = "undated"


def _strip_header(md: str) -> str:
    if "-->" not in md:
        return md
    _, _, rest = md.partition("-->")
    return rest.lstrip("\n")


def _extract_doc_date(path: Path) -> str | None:
    body = _strip_header(path.read_text(encoding="utf-8"))
    raw_date, _ = _parse_metadata(body)
    if raw_date and _DATE_RE.fullmatch(raw_date):
        return raw_date
    # Fallback to intermediate filename prefix: YYYY-MM-DD_<type>_<hash>.md
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_", path.stem)
    if m:
        return m.group(1)
    return None


def _shard_key_from_date(doc_date: str | None, *, shard_mode: str) -> str:
    if not doc_date:
        return _UNDATED_KEY
    year = doc_date[:4]
    # Keep backward compatibility for legacy callers that still pass "year".
    if shard_mode == "year":
        shard_mode = "half-year"
    month = int(doc_date[5:7])
    half = "H1" if month <= 6 else "H2"
    return f"{year}{half}"


def _normalize_shard_mode(shard_mode: str) -> str:
    """Staged Summary mode always uses half-year shards."""
    if shard_mode == "year":
        print(
            "Warning: --shard-mode year is deprecated; using half-year instead.",
            file=sys.stderr,
        )
        return "half-year"
    return shard_mode


def _cleanup_legacy_yearly_period_profiles() -> int:
    """Remove old annual shard artifacts like period_profile_2024.md."""
    out_dir = AURA_STATE_HOME / "period_summaries"
    if not out_dir.is_dir():
        return 0
    removed = 0
    for p in out_dir.glob("period_profile_*.md"):
        if re.fullmatch(r"period_profile_\d{4}", p.stem):
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _sort_shard_keys(keys: list[str]) -> list[str]:
    dated = sorted(k for k in keys if k != _UNDATED_KEY)
    if _UNDATED_KEY in keys:
        dated.append(_UNDATED_KEY)
    return dated


def _shard_scope_rule(shard_key: str, *, use_chinese: bool) -> str:
    if shard_key == _UNDATED_KEY:
        return (
            "仅整理无法确定明确日期的记录，不要推断具体日期。"
            if use_chinese
            else "Only summarize records without reliable dates; do not invent exact dates."
        )
    m = re.fullmatch(r"(\d{4})(H[12])", shard_key)
    if not m:
        return (
            f"仅整理属于分片 `{shard_key}` 的信息。"
            if use_chinese
            else f"Only summarize facts belonging to shard `{shard_key}`."
        )
    year = int(m.group(1))
    half = m.group(2)
    if half == "H1":
        start = f"{year}-01-01"
        end = f"{year}-06-30"
    else:
        start = f"{year}-07-01"
        end = f"{year}-12-31"
    if use_chinese:
        return (
            f"时间范围严格限定在 {start} 到 {end}。"
            "若资料提到更早/更晚历史，仅可在“跨期背景”中一句带过，不得写入本分片主时间线。"
        )
    return (
        f"Strictly constrain main timeline to {start}..{end}. "
        "If records mention earlier/later history, keep at most one brief note under cross-period context, "
        "not in this shard's main timeline."
    )


def _batch_by_chars(paths: list[Path], max_chars: int) -> list[list[Path]]:
    batches: list[list[Path]] = []
    current: list[Path] = []
    current_chars = 0
    for p in paths:
        txt = p.read_text(encoding="utf-8")
        estimated = len(txt) + 120
        if current and current_chars + estimated > max_chars:
            batches.append(current)
            current = []
            current_chars = 0
        current.append(p)
        current_chars += estimated
    if current:
        batches.append(current)
    return batches


def _render_bundle(paths: list[Path]) -> str:
    chunks: list[str] = []
    for p in paths:
        chunks.append(f"### FILE: {p.name}\n\n{p.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(chunks)


def _summarize_one_batch(
    *,
    batch_paths: list[Path],
    shard_key: str,
    batch_index: int,
    batch_total: int,
    model: str,
    use_chinese: bool,
) -> str:
    language_rule = (
        "Output in Simplified Chinese (zh-CN)."
        if use_chinese
        else "Keep language consistent with the sources when reasonable."
    )
    scope_rule = _shard_scope_rule(shard_key, use_chinese=use_chinese)
    label = f"{batch_index}/{batch_total}"
    prompt = f"""Summarize these intermediate medical records into a shard-level draft.

You are processing shard `{shard_key}`, batch `{label}`.

Rules:
- Keep only factual medical details from the provided records.
- Preserve dates, numeric values, and units exactly when present.
- Deduplicate repeated boilerplate.
- Keep chronology explicit.
- {scope_rule}
- {language_rule}

Output Markdown with sections:
## Timeline facts
## Cross-period context (brief)
## Diagnoses and assessments
## Medications and interventions
## Lab metrics (table when possible)
## Imaging / procedures / pathology / inpatient / surgery
## Follow-up / unresolved questions

--- Intermediate records ---
{_render_bundle(batch_paths)}
"""
    messages = [
        {
            "role": "system",
            "content": "You summarize medical records for personal longitudinal profile consolidation.",
        },
        {"role": "user", "content": prompt},
    ]
    return chat_completions(messages, model=model, max_tokens=8192).strip()


def _merge_batch_summaries(
    *,
    shard_key: str,
    summaries: list[str],
    model: str,
    use_chinese: bool,
) -> str:
    if len(summaries) == 1:
        return summaries[0]
    language_rule = (
        "Output in Simplified Chinese (zh-CN)."
        if use_chinese
        else "Keep language consistent with the sources when reasonable."
    )
    scope_rule = _shard_scope_rule(shard_key, use_chinese=use_chinese)
    merged = "\n\n---\n\n".join(
        f"### PART {i + 1}\n\n{s}" for i, s in enumerate(summaries)
    )
    prompt = f"""Merge these partial summaries from the same time shard into ONE shard summary.

Shard: `{shard_key}`

Rules:
- Remove overlap and contradiction where possible.
- Keep the most recent fact when two entries conflict by date.
- Preserve important qualifiers (e.g. fasting, postprandial).
- {scope_rule}
- {language_rule}

Output Markdown with sections:
## Shard timeline
## Cross-period context (brief)
## Key problems and clinical status
## Medications
## Labs and trend hints
## Imaging/procedures/pathology/inpatient/surgery
## Open follow-up questions

Partial summaries:
{merged}
"""
    messages = [
        {
            "role": "system",
            "content": "You merge medical timeline summaries into one coherent shard summary.",
        },
        {"role": "user", "content": prompt},
    ]
    return chat_completions(messages, model=model, max_tokens=8192).strip()


def _build_shard_summary(
    *,
    shard_key: str,
    paths: list[Path],
    model: str,
    use_chinese: bool,
    shard_max_chars: int,
) -> str:
    batches = _batch_by_chars(paths, shard_max_chars)
    parts: list[str] = []
    for idx, batch in enumerate(batches, start=1):
        parts.append(
            _summarize_one_batch(
                batch_paths=batch,
                shard_key=shard_key,
                batch_index=idx,
                batch_total=len(batches),
                model=model,
                use_chinese=use_chinese,
            )
        )
    return _merge_batch_summaries(
        shard_key=shard_key,
        summaries=parts,
        model=model,
        use_chinese=use_chinese,
    )


def _write_shard_markdown(*, shard_key: str, text: str) -> Path:
    out_dir = AURA_STATE_HOME / "period_summaries"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"period_profile_{shard_key}.md"
    out.write_text(text.rstrip() + "\n", encoding="utf-8")
    return out


def _final_merge(
    *,
    template: str,
    reference: str,
    shard_docs: list[tuple[str, Path]],
    model: str,
    use_chinese: bool,
) -> str:
    language_rule = (
        "Output the final profile in Simplified Chinese (zh-CN)."
        if use_chinese
        else (
            "Keep the same language as the sources when reasonable "
            "(e.g. Chinese stays Chinese unless translating improves clarity)."
        )
    )
    ref_block = ""
    if reference.strip():
        ref_block = (
            "\n\nUse the following reference for standard lab names and units when normalizing:\n\n"
            + reference.strip()
        )
        if use_chinese:
            ref_block = (
                "\n\n归一化检验项目名称与单位时，可参考下列术语对照：\n\n"
                + reference.strip()
            )
    shard_chunks = []
    for key, p in shard_docs:
        shard_chunks.append(f"### SHARD: {key}\n\n{p.read_text(encoding='utf-8')}")
    shard_bundle = "\n\n---\n\n".join(shard_chunks)
    user_msg = f"""You will merge time-sharded medical summaries into ONE consolidated health profile.

Follow the structure and section headings in the template below.
De-duplicate overlapping facts and keep chronology coherent across shards.
Preserve important qualifiers (e.g. fasting, postprandial). {language_rule}

Template (obey this outline):

{template}
{ref_block}

--- Time shard summaries ---
{shard_bundle}

Output ONLY the final Markdown profile. No preamble."""
    messages = [
        {
            "role": "system",
            "content": "You consolidate personal health records into a single clear Markdown document. You do not diagnose or prescribe.",
        },
        {"role": "user", "content": user_msg},
    ]
    return chat_completions(messages, model=model, max_tokens=16384)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build health_profile_YYYYMMDD.md via half-year time shards to reduce token pressure."
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

    intermediates = sorted(INTERMEDIATE_DIR.glob("*.md"))
    if not intermediates:
        raise SystemExit(f"No intermediate files in {INTERMEDIATE_DIR}")
    merge_inputs, skipped_by_policy, policy_warnings = choose_intermediates_for_profile(
        intermediates,
        mode=args.pdf_input_mode,
        threshold_pages=args.pdf_bundle_threshold_pages,
    )
    for msg in policy_warnings:
        print(f"Bundle policy: {msg}", file=sys.stderr)
    if skipped_by_policy:
        print(
            f"Bundle policy skipped {len(skipped_by_policy)} intermediate file(s).",
            file=sys.stderr,
        )
    if not merge_inputs:
        raise SystemExit("No intermediate files selected for merge after PDF input policy.")

    included, excluded = partition_intermediates(merge_inputs)
    for x in excluded:
        print(f"QC exclude {x.file}: {x.reason} ({x.detail})", file=sys.stderr)
    qc_path = AURA_STATE_HOME / "last_profile_qc.json"
    write_qc_artifact(
        path=qc_path,
        included=included,
        excluded=excluded,
        label="build_sharded",
    )
    if not included:
        raise SystemExit(
            "No usable intermediate files after QC (all excluded as duplicate or abnormal). "
            f"See {qc_path} for details; fix or remove files under intermediate/."
        )

    shards: dict[str, list[Path]] = {}
    for p in included:
        doc_date = _extract_doc_date(p)
        key = _shard_key_from_date(doc_date, shard_mode=args.shard_mode)
        shards.setdefault(key, []).append(p)
    if not shards:
        raise SystemExit("No shard candidates found.")

    shard_docs: list[tuple[str, Path]] = []
    for key in _sort_shard_keys(list(shards.keys())):
        shard_paths = sorted(shards[key], key=lambda p: p.name)
        summary = _build_shard_summary(
            shard_key=key,
            paths=shard_paths,
            model=args.model,
            use_chinese=use_chinese,
            shard_max_chars=args.shard_max_chars,
        )
        shard_doc = _write_shard_markdown(shard_key=key, text=summary)
        shard_docs.append((key, shard_doc))
        print(shard_doc, file=sys.stderr)

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
        disclaimer + final_text.lstrip() + format_qc_markdown_section(excluded),
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
