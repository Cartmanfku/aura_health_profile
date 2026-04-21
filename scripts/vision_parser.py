#!/usr/bin/env python3
"""Scan a directory of medical raster images; call Qwen vision; write intermediate MD + metrics + hashes.

Each image yields one intermediate Markdown under ``~/.aura-health/intermediate/``. PDFs are handled by
``pdf_vision_parser.py`` (per-page rasterization + shared vision prompts).

State is flushed every ``--batch-size`` file(s). Successful intermediate files are written to disk **before**
the next flush; if a later image fails, earlier ``*.md`` files remain. If the process dies after writing an
``.md`` but before ``processed.json`` catches up, the next run still skips those sources because
``vision_parse_common.load_existing_intermediate_hashes()`` rescans headers.

Progress prints to stderr; new intermediate paths print to stdout.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import (
    DEFAULT_VISION_MODEL,
    INTERMEDIATE_DIR,
    METRICS_PATH,
    ensure_state_dirs,
)

from vision_parse_common import (
    flush_state,
    format_eta,
    load_existing_intermediate_hashes,
    load_metrics_doc,
    load_processed,
    progress_print,
    write_intermediate_from_vision,
    _call_vision,
    _image_data_url,
    _sha256_file,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def process_image(
    path: Path,
    *,
    model: str,
    force: bool,
    processed: set[str],
    attempted: set[str],
    metrics_doc: dict,
    used_basenames: set[str],
) -> Path | None:
    digest = _sha256_file(path)
    if digest in attempted:
        return None
    attempted.add(digest)
    if not force and digest in processed:
        return None

    _, url = _image_data_url(path)
    text = _call_vision(url, path.name, model=model)
    return write_intermediate_from_vision(
        text,
        content_digest=digest,
        source_comment=f"{path.name} sha256: {digest}",
        path_for_mtime=path,
        metrics_source_file=path.name,
        processed=processed,
        metrics_doc=metrics_doc,
        used_basenames=used_basenames,
    )


def _list_image_paths(root: Path, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(
            p
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )
    return sorted(
        p
        for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse medical images (JPEG/PNG/WebP) via DashScope vision model. "
        "For PDF reports use pdf_vision_parser.py."
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing .jpg / .jpeg / .png / .webp",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include subdirectories",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-parse even if file hash is already in processed.json",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_VISION_MODEL,
        help=f"Vision model (default: {DEFAULT_VISION_MODEL})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        metavar="N",
        help=(
            "Save processed.json + metrics.json after every N image(s) (default: 5). "
            "Each successful image writes its .md immediately; use 1 to flush state after every file."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print per-file progress / ETA lines",
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")

    ensure_state_dirs()
    root = args.input_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    files = _list_image_paths(root, args.recursive)
    if not files:
        print("No image files found.")
        return

    processed = load_processed()
    if not args.force:
        processed.update(load_existing_intermediate_hashes())

    metrics_doc = load_metrics_doc()
    used_basenames = {p.stem for p in INTERMEDIATE_DIR.glob("*.md")}
    attempted: set[str] = set()

    written: list[Path] = []
    total = len(files)
    tty = sys.stderr.isatty()
    t0 = time.perf_counter()
    pending_flush = 0
    interrupted = False

    try:
        for i, path in enumerate(files):
            try:
                out = process_image(
                    path,
                    model=args.model,
                    force=args.force,
                    processed=processed,
                    attempted=attempted,
                    metrics_doc=metrics_doc,
                    used_basenames=used_basenames,
                )
            except SystemExit:
                raise
            except Exception as e:
                print(f"FAIL {path}: {e}")
                out = None

            if out:
                print(out)
                written.append(out)

            completed = i + 1
            elapsed = time.perf_counter() - t0
            rate = completed / elapsed if elapsed > 0 else 0.0
            remaining = total - completed
            eta_sec = (remaining / rate) if rate > 0 else None

            if not args.quiet:
                show_progress = tty or (
                    completed == 1
                    or completed == total
                    or completed % args.batch_size == 0
                )
                if show_progress:
                    line = (
                        f"进度: {completed}/{total}  新写入 {len(written)}  "
                        f"预计剩余约 {format_eta(eta_sec)}"
                    )
                    progress_print(line, tty=tty, newline=not tty)

            pending_flush += 1
            if pending_flush >= args.batch_size:
                flush_state(processed, metrics_doc)
                pending_flush = 0

        if pending_flush:
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
