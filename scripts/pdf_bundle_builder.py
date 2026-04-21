#!/usr/bin/env python3
"""Build compressed PDF bundles from per-page intermediates."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import DEFAULT_TEXT_MODEL, INTERMEDIATE_DIR, chat_completions, preferred_language
from vision_parse_common import _parse_metadata

_PAGE_SRC_RE = re.compile(
    r"<!--\s*source_file:\s*(.+?)\s+page:(\d+)/(\d+)\s+sha256:\s*([a-f0-9]{64})\b",
    re.IGNORECASE | re.DOTALL,
)
_BUNDLE_SRC_RE = re.compile(
    r"<!--\s*source_file:\s*(.+?)\s+pdf_bundle:\s*true\b[^>]*?\bsha256:\s*([a-f0-9]{64})\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class PageIntermediate:
    path: Path
    pdf_name: str
    page_no: int
    total_pages: int
    page_sha256: str
    body: str


@dataclass(frozen=True)
class BundleIntermediate:
    path: Path
    pdf_name: str
    bundle_sha256: str


def _strip_header(md: str) -> str:
    if "-->" not in md:
        return md
    _, _, rest = md.partition("-->")
    return rest.lstrip("\n")


def _safe_slug(name: str) -> str:
    stem = Path(name).stem.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", stem).strip("_")
    return slug or "pdf"


def _infer_doc_fields_from_intermediate_name(path: Path) -> tuple[str | None, str | None]:
    """
    Best-effort fallback from intermediate filename pattern:
    YYYY-MM-DD_<doc_type>_<hash...>.md
    """
    stem = path.stem
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_([a-zA-Z_]+)_", stem)
    if not m:
        return None, None
    date_s = m.group(1)
    doc_type = m.group(2).lower()
    return date_s, doc_type


def _enforce_bundle_shape(summary: str, *, doc_date: str, doc_type: str) -> str:
    """Ensure bundle markdown passes intermediate QC required headings."""
    text = summary.lstrip()
    low = text.lower()
    has_doc = "## document metadata" in low
    has_ext = "## extracted content" in low
    has_num = "## numeric metrics" in low

    if has_doc and has_ext:
        if not has_num:
            text = text.rstrip() + "\n\n## Numeric metrics\n```json\n[]\n```\n"
        return text

    body = text
    normalized = (
        "## Document metadata\n"
        f"- **Document date:** `{doc_date}`\n"
        f"- **Document type:** {doc_type}\n\n"
        "## Extracted content\n"
        f"{body.rstrip()}\n\n"
        "## Numeric metrics\n"
        "```json\n[]\n```\n"
    )
    return normalized


def _parse_page_intermediate(path: Path) -> PageIntermediate | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _PAGE_SRC_RE.search(text[:1200])
    if not m:
        return None
    return PageIntermediate(
        path=path,
        pdf_name=m.group(1).strip(),
        page_no=int(m.group(2)),
        total_pages=int(m.group(3)),
        page_sha256=m.group(4).lower(),
        body=_strip_header(text),
    )


def _parse_bundle_intermediate(path: Path) -> BundleIntermediate | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _BUNDLE_SRC_RE.search(text[:1200])
    if not m:
        return None
    return BundleIntermediate(path=path, pdf_name=m.group(1).strip(), bundle_sha256=m.group(2).lower())


def group_pdf_artifacts(
    paths: list[Path] | None = None,
) -> tuple[dict[str, list[PageIntermediate]], dict[str, list[BundleIntermediate]]]:
    page_map: dict[str, list[PageIntermediate]] = {}
    bundle_map: dict[str, list[BundleIntermediate]] = {}
    seq = paths if paths is not None else sorted(INTERMEDIATE_DIR.glob("*.md"))
    for p in seq:
        page = _parse_page_intermediate(p)
        if page:
            page_map.setdefault(page.pdf_name, []).append(page)
            continue
        bundle = _parse_bundle_intermediate(p)
        if bundle:
            bundle_map.setdefault(bundle.pdf_name, []).append(bundle)
    for items in page_map.values():
        items.sort(key=lambda x: x.page_no)
    for items in bundle_map.values():
        items.sort(key=lambda x: x.path.stat().st_mtime)
    return page_map, bundle_map


def choose_intermediates_for_profile(
    intermediates: list[Path],
    *,
    mode: str,
    threshold_pages: int,
) -> tuple[list[Path], list[Path], list[str]]:
    """Select intermediate files for merge input: raw / bundle / auto."""
    selected: list[Path] = []
    dropped: list[Path] = []
    warnings: list[str] = []

    pages_by_pdf, bundles_by_pdf = group_pdf_artifacts(intermediates)
    page_paths = {x.path for v in pages_by_pdf.values() for x in v}
    bundle_paths = {x.path for v in bundles_by_pdf.values() for x in v}

    for p in intermediates:
        if p not in page_paths and p not in bundle_paths:
            selected.append(p)

    for pdf_name in sorted(set(pages_by_pdf) | set(bundles_by_pdf)):
        pages = pages_by_pdf.get(pdf_name, [])
        bundles = bundles_by_pdf.get(pdf_name, [])
        latest_bundle = bundles[-1].path if bundles else None
        page_total = pages[-1].total_pages if pages else 0

        if mode == "raw":
            selected.extend(x.path for x in pages)
            dropped.extend(x.path for x in bundles)
            continue

        if mode == "bundle":
            if latest_bundle is not None:
                selected.append(latest_bundle)
                dropped.extend(x.path for x in pages)
                dropped.extend(x.path for x in bundles[:-1])
            else:
                selected.extend(x.path for x in pages)
                warnings.append(f"PDF {pdf_name}: no bundle found; fallback to raw pages.")
            continue

        # auto
        use_bundle = page_total > threshold_pages and latest_bundle is not None
        if use_bundle:
            selected.append(latest_bundle)
            dropped.extend(x.path for x in pages)
            dropped.extend(x.path for x in bundles[:-1])
        else:
            selected.extend(x.path for x in pages)
            if latest_bundle is not None:
                dropped.extend(x.path for x in bundles)
            if page_total > threshold_pages and latest_bundle is None:
                warnings.append(
                    f"PDF {pdf_name}: {page_total} pages but bundle missing; using raw pages."
                )

    seen: set[Path] = set()
    dedup_selected: list[Path] = []
    for p in selected:
        if p not in seen:
            dedup_selected.append(p)
            seen.add(p)
    return dedup_selected, dropped, warnings


def _summarize_chunk(
    pages: list[PageIntermediate],
    *,
    model: str,
    use_chinese: bool,
) -> str:
    page_label = f"{pages[0].page_no}-{pages[-1].page_no}"
    chunk = "\n\n---\n\n".join(f"### PAGE {x.page_no}\n\n{x.body}" for x in pages)
    lang_rule = "请使用简体中文输出。" if use_chinese else "Output in clear English."
    prompt = (
        "Summarize these pages from one medical PDF for profile merge. Keep only clinically useful facts, "
        "preserve numbers/units/dates exactly when present, and remove repeated boilerplate.\n"
        f"Page range: {page_label}\n{lang_rule}\n\n"
        "Return Markdown with sections:\n"
        "## Key findings\n## Diagnoses/assessments\n## Medications/interventions\n## Numeric metrics (table)\n## Follow-up recommendations\n## Unknown/ambiguous items\n\n"
        f"{chunk}"
    )
    messages = [
        {"role": "system", "content": "You summarize medical documents for personal record consolidation."},
        {"role": "user", "content": prompt},
    ]
    return chat_completions(messages, model=model, max_tokens=8192).strip()


def build_bundle_for_pdf_name(
    pdf_name: str,
    *,
    model: str,
    threshold_pages: int,
    chunk_pages: int,
    keep_raw_pages: bool = True,
) -> Path | None:
    pages_by_pdf, bundles_by_pdf = group_pdf_artifacts()
    pages = pages_by_pdf.get(pdf_name, [])
    if not pages:
        return None
    total = pages[-1].total_pages
    if total <= threshold_pages:
        return None

    use_chinese = preferred_language() == "zh-CN"
    chunks: list[str] = []
    for i in range(0, len(pages), chunk_pages):
        chunks.append(_summarize_chunk(pages[i : i + chunk_pages], model=model, use_chinese=use_chinese))

    combined = "\n\n---\n\n".join(
        f"### CHUNK {idx + 1}\n\n{txt}" for idx, txt in enumerate(chunks)
    )
    first_date, first_type = _parse_metadata(pages[0].body)
    # Prefer explicit metadata from page-1 body; fallback to intermediate filename fields.
    inferred_date, inferred_type = _infer_doc_fields_from_intermediate_name(pages[0].path)
    doc_date = first_date or inferred_date or "Unknown"
    doc_type = first_type or inferred_type or "other"
    page_sig = "|".join(f"{x.page_no}:{x.page_sha256}" for x in pages)
    bundle_sha = hashlib.sha256(f"{pdf_name}|{page_sig}".encode("utf-8")).hexdigest()
    bundle_name = f"{doc_date}_{doc_type}_{bundle_sha[:8]}_bundle.md"
    out = INTERMEDIATE_DIR / bundle_name

    final_prompt = (
        "Merge chunk summaries from one PDF into a compact document-level summary.\n"
        "Keep only high-value medical facts; preserve metrics with units and dates; dedupe repeated statements.\n"
        "Output Markdown with sections:\n"
        "## Document metadata\n## Consolidated findings\n## Numeric metrics\n## Follow-up / treatment plan\n## Source coverage\n\n"
        f"PDF filename: {pdf_name}\n"
        f"Total pages: {total}\n\n"
        f"{combined}"
    )
    final_messages = [
        {"role": "system", "content": "You produce concise but faithful medical record summaries."},
        {"role": "user", "content": final_prompt},
    ]
    summary = chat_completions(final_messages, model=model, max_tokens=8192).lstrip()
    summary = _enforce_bundle_shape(summary, doc_date=doc_date, doc_type=doc_type)
    header = (
        f"<!-- source_file: {pdf_name} pdf_bundle: true pages:{total} sha256: {bundle_sha} "
        f"keep_raw_pages: {str(keep_raw_pages).lower()} -->\n\n"
    )
    out.write_text(header + summary, encoding="utf-8")

    # Keep only newest bundle for same source PDF.
    for old in bundles_by_pdf.get(pdf_name, []):
        if old.path != out:
            try:
                old.path.unlink()
            except OSError:
                pass
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PDF bundle Markdown from per-page intermediates.")
    parser.add_argument("--model", default=DEFAULT_TEXT_MODEL, help=f"Text model (default: {DEFAULT_TEXT_MODEL})")
    parser.add_argument("--threshold-pages", type=int, default=4, help="Build bundle when pages > N (default: 4).")
    parser.add_argument("--chunk-pages", type=int, default=4, help="Pages per map-chunk (default: 4).")
    parser.add_argument("--pdf-name", help="Only build bundle for this source PDF filename.")
    args = parser.parse_args()
    if args.threshold_pages < 1 or args.chunk_pages < 1:
        raise SystemExit("--threshold-pages and --chunk-pages must be >= 1")

    pages_by_pdf, _ = group_pdf_artifacts()
    names = [args.pdf_name] if args.pdf_name else sorted(pages_by_pdf.keys())
    written: list[Path] = []
    for name in names:
        out = build_bundle_for_pdf_name(
            name,
            model=args.model,
            threshold_pages=args.threshold_pages,
            chunk_pages=args.chunk_pages,
        )
        if out is not None:
            print(out)
            written.append(out)
    print(f"Done. {len(written)} bundle file(s).")


if __name__ == "__main__":
    main()
