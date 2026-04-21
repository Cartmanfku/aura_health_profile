#!/usr/bin/env python3
"""Parse medical PDFs page-by-page via Qwen vision; one UTF-8 intermediate Markdown per page.

- Each successful page writes ``*.md`` immediately, then flushes ``processed.json`` + ``metrics.json`` so a
  later API failure does not lose completed pages. If a page fails, re-run without ``--force``: finished
  pages stay skipped; only missing pages are retried.
- Document **date** and **type** are taken from **page 1** (cover) and injected into every page's Markdown
  metadata block so downstream merge sees a consistent report identity.
- Rendering uses PyMuPDF RGB pixmaps (helps CJK clarity); prompts ask the model to preserve Chinese in UTF-8.

Raster images are handled by ``vision_parser.py`` instead.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
import sys
import time
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import DEFAULT_VISION_MODEL, INTERMEDIATE_DIR, METRICS_PATH, ensure_state_dirs
from pdf_bundle_builder import build_bundle_for_pdf_name

from vision_parse_common import (
    SOURCE_SHA_RE,
    flush_state,
    format_eta,
    load_existing_intermediate_hashes,
    load_metrics_doc,
    load_processed,
    progress_print,
    write_intermediate_from_vision_with_doc_fields,
    _call_vision,
    _data_url_from_bytes,
    _parse_metadata,
    _sha256_file,
)


def _import_fitz():  # pragma: no cover
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError as e:
        raise SystemExit(
            "PDF parsing requires PyMuPDF. Install: pip install pymupdf "
            f"(from the skill directory: pip install -r requirements.txt). Original error: {e}"
        ) from e
    return fitz


def _pdf_page_digest(file_sha256: str, page_index: int) -> str:
    return hashlib.sha256(f"{file_sha256}:{page_index}".encode()).hexdigest()


def _render_pdf_page_png(doc: object, page_index: int, zoom: float) -> bytes:
    fitz = _import_fitz()
    page = doc.load_page(page_index)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(
        matrix=mat,
        alpha=False,
        colorspace=fitz.csRGB,
        annots=False,
    )
    return pix.tobytes("png")


def apply_canonical_document_metadata(md: str, doc_date: str, doc_type: str) -> str:
    """Replace the ## Document metadata section so all pages match the PDF cover (page 1)."""
    new_block = (
        "## Document metadata\n\n"
        f"- **Document date:** `{doc_date}`\n"
        f"- **Document type:** {doc_type}\n\n"
    )
    pattern = r"(?ms)^##\s*Document metadata\s*$\s*[\s\S]+?^(?=##\s*Extracted\s+content\s*$)"
    m = re.search(pattern, md)
    if not m:
        return md
    return md[: m.start()] + new_block + md[m.end() :]


def _intermediate_path_for_page_digest(page_digest: str) -> Path | None:
    needle = page_digest.lower()
    for p in INTERMEDIATE_DIR.glob("*.md"):
        try:
            head = p.read_text(encoding="utf-8")[:1200]
        except OSError:
            continue
        m = SOURCE_SHA_RE.search(head)
        if m and m.group(1).lower() == needle:
            return p
    return None


def load_canonical_from_existing_page0(page0_digest: str) -> tuple[str, str] | None:
    path = _intermediate_path_for_page_digest(page0_digest)
    if not path:
        return None
    body = path.read_text(encoding="utf-8")
    if "-->" in body:
        _, _, rest = body.partition("-->")
        rest = rest.lstrip("\n")
    else:
        rest = body
    return _parse_metadata(rest)


def _list_pdf_paths(root: Path, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(
            p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"
        )
    return sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")


def process_pdf_file(
    pdf_path: Path,
    *,
    model: str,
    force: bool,
    pdf_zoom: float,
    processed: set[str],
    attempted: set[str],
    metrics_doc: dict,
    used_basenames: set[str],
) -> list[Path]:
    fitz = _import_fitz()
    doc = fitz.open(pdf_path)
    try:
        total = len(doc)
        if total == 0:
            print(f"SKIP empty PDF: {pdf_path}", file=sys.stderr)
            return []
        file_digest = _sha256_file(pdf_path)
        page0_digest = _pdf_page_digest(file_digest, 0)
        unknown_date = "Unknown"

        canon_date: str | None = None
        canon_type: str | None = None
        if not force and page0_digest in processed:
            pre = load_canonical_from_existing_page0(page0_digest)
            if pre:
                d, t = pre
                if d:
                    canon_date = d
                canon_type = t or None

        written_here: list[Path] = []
        for page_index in range(total):
            page_digest = _pdf_page_digest(file_digest, page_index)
            human = page_index + 1

            if page_digest in attempted:
                continue
            attempted.add(page_digest)
            if not force and page_digest in processed:
                if page_index == 0:
                    pre = load_canonical_from_existing_page0(page_digest)
                    if pre:
                        d, t = pre
                        if d:
                            canon_date = d
                        if t:
                            canon_type = t
                elif canon_date is None or canon_type is None:
                    pre0 = load_canonical_from_existing_page0(page0_digest)
                    if pre0:
                        d0, t0 = pre0
                        canon_date = canon_date or d0 or unknown_date
                        canon_type = canon_type or t0 or "other"
                continue

            try:
                png = _render_pdf_page_png(doc, page_index, pdf_zoom)
                url = _data_url_from_bytes("image/png", png)
                label = f"{pdf_path.name} (PDF page {human}/{total})"
                suffix = ""
                if page_index > 0:
                    suffix = (
                        "This is an inner page of the same PDF report. Transcribe all visible text and tables "
                        "faithfully. Report title / institution / dates on the cover are not repeated here; "
                        "still output the required ## Document metadata section (placeholders are fine)."
                    )
                text = _call_vision(url, label, model=model, user_suffix=suffix)

                if page_index == 0:
                    d, t = _parse_metadata(text)
                    canon_date = d or unknown_date
                    canon_type = t or "other"
                    text_to_store = text
                else:
                    if canon_date is None or canon_type is None:
                        pre = load_canonical_from_existing_page0(page0_digest)
                        if pre:
                            d0, t0 = pre
                            if canon_date is None and d0:
                                canon_date = d0
                            if canon_type is None:
                                canon_type = t0 or "other"
                        if canon_date is None:
                            canon_date = unknown_date
                        if canon_type is None:
                            canon_type = "other"
                    text_to_store = apply_canonical_document_metadata(
                        text, canon_date, canon_type
                    )

                out = write_intermediate_from_vision_with_doc_fields(
                    text_to_store,
                    content_digest=page_digest,
                    source_comment=(
                        f"{pdf_path.name} page:{human}/{total} sha256: {page_digest}"
                    ),
                    path_for_mtime=pdf_path,
                    metrics_source_file=f"{pdf_path.name}#p{human}",
                    document_date=canon_date or unknown_date,
                    document_type=canon_type or "other",
                    processed=processed,
                    metrics_doc=metrics_doc,
                    used_basenames=used_basenames,
                )
                written_here.append(out)
                print(out, flush=True)
                flush_state(processed, metrics_doc)
            except SystemExit:
                raise
            except Exception as e:
                flush_state(processed, metrics_doc)
                print(f"FAIL {pdf_path} (page {human}/{total}): {e}", file=sys.stderr)

        return written_here
    finally:
        doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse medical PDFs (vision, one Markdown per page). "
        "See vision_parser.py for raster images only."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing .pdf files",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include subdirectories",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-parse every page even if its digest is already in processed.json",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_VISION_MODEL,
        help=f"Vision model (default: {DEFAULT_VISION_MODEL})",
    )
    parser.add_argument(
        "--pdf-zoom",
        type=float,
        default=2.0,
        metavar="Z",
        help=(
            "Rasterize each page at this zoom (1 = base resolution, 2 is typical). "
            "Higher improves small Chinese text; larger payloads. Default: 2."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-page progress / ETA lines",
    )
    parser.add_argument(
        "--bundle-threshold-pages",
        type=int,
        default=3,
        help="Build PDF bundle when pages > N (default: 3).",
    )
    parser.add_argument(
        "--bundle-chunk-pages",
        type=int,
        default=4,
        help="Pages per chunk while summarizing long PDFs (default: 4).",
    )
    parser.add_argument(
        "--no-bundle",
        action="store_true",
        help="Disable bundle generation after page parsing.",
    )
    args = parser.parse_args()
    if not math.isfinite(args.pdf_zoom) or args.pdf_zoom <= 0:
        raise SystemExit("--pdf-zoom must be a finite number > 0")
    if args.bundle_threshold_pages < 1:
        raise SystemExit("--bundle-threshold-pages must be >= 1")
    if args.bundle_chunk_pages < 1:
        raise SystemExit("--bundle-chunk-pages must be >= 1")

    ensure_state_dirs()
    root = args.input_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    pdfs = _list_pdf_paths(root, args.recursive)
    if not pdfs:
        print("No PDF files found.")
        return

    processed = load_processed()
    if not args.force:
        processed.update(load_existing_intermediate_hashes())
    metrics_doc = load_metrics_doc()
    used_basenames = {p.stem for p in INTERMEDIATE_DIR.glob("*.md")}
    attempted: set[str] = set()

    written: list[Path] = []
    total_pages = 0
    fitz = _import_fitz()
    page_counts: list[tuple[Path, int]] = []
    for p in pdfs:
        try:
            d = fitz.open(p)
            try:
                n = len(d)
                total_pages += n
                page_counts.append((p, n))
            finally:
                d.close()
        except Exception as e:
            print(f"FAIL count pages {p}: {e}")

    if total_pages == 0:
        print("No PDF pages to process.")
        return

    tty = sys.stderr.isatty()
    t0 = time.perf_counter()
    completed_pages = 0
    interrupted = False

    try:
        for pdf_path, n in page_counts:
            try:
                outs = process_pdf_file(
                    pdf_path,
                    model=args.model,
                    force=args.force,
                    pdf_zoom=args.pdf_zoom,
                    processed=processed,
                    attempted=attempted,
                    metrics_doc=metrics_doc,
                    used_basenames=used_basenames,
                )
            except SystemExit:
                raise
            except Exception as e:
                flush_state(processed, metrics_doc)
                print(f"FAIL {pdf_path}: {e}")
                outs = []
            if not args.no_bundle and n > args.bundle_threshold_pages:
                try:
                    bundle_path = build_bundle_for_pdf_name(
                        pdf_path.name,
                        model=args.model,
                        threshold_pages=args.bundle_threshold_pages,
                        chunk_pages=args.bundle_chunk_pages,
                    )
                    if bundle_path is not None:
                        print(bundle_path)
                except Exception as e:
                    print(f"FAIL bundle {pdf_path}: {e}", file=sys.stderr)

            written.extend(outs)
            completed_pages += n

            if not args.quiet and n:
                elapsed = time.perf_counter() - t0
                rate = completed_pages / elapsed if elapsed > 0 else 0.0
                remaining = total_pages - completed_pages
                eta_sec = (remaining / rate) if rate > 0 else None
                line = (
                    f"PDF进度(页): {completed_pages}/{total_pages}  本运行新写入 {len(written)}  "
                    f"预计剩余约 {format_eta(eta_sec)}"
                )
                progress_print(line, tty=tty, newline=not tty)

        flush_state(processed, metrics_doc)

    except KeyboardInterrupt:
        interrupted = True
        flush_state(processed, metrics_doc)
        if tty and not args.quiet:
            print()
        print("已中断，进度已保存。", file=sys.stderr)

    if tty and not args.quiet:
        print(file=sys.stderr)

    if interrupted:
        raise SystemExit(130)

    print(f"Done. {len(written)} intermediate file(s); metrics -> {METRICS_PATH}")


if __name__ == "__main__":
    main()
