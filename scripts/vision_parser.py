#!/usr/bin/env python3
"""Scan a directory of medical images; call Qwen; write intermediate MD + metrics + processed hashes.

Processes images sequentially, saves state every ``--batch-size`` file(s) so rate limits / timeouts
lose at most one batch. Progress (total / done / ETA) is printed to stderr; parsed paths stay on stdout.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import mimetypes
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import (
    DEFAULT_VISION_MODEL,
    INTERMEDIATE_DIR,
    METRICS_PATH,
    PROCESSED_PATH,
    chat_completions,
    ensure_state_dirs,
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_SOURCE_SHA_RE = re.compile(
    r"<!--\s*source_file:\s*[^>]*?\bsha256:\s*([a-f0-9]{64})\b",
    re.IGNORECASE | re.DOTALL,
)
VISION_SYSTEM = """You are a medical document digitization assistant. Extract text and structure from images accurately. Output Markdown only. Do not diagnose or give treatment advice."""

VISION_USER = """Analyze this medical document image.

Output Markdown with exactly these sections in order:

## Document metadata
- **Document date:** YYYY-MM-DD, or `Unknown` if not legible
- **Document type:** one word from: lab, visit, prescription, imaging, pathology, inpatient, surgery, other

## Extracted content
Faithful transcription and structure (tables as Markdown tables when appropriate).

## Numeric metrics
After the above, include a fenced JSON code block labeled exactly:
```json
```
containing an array of objects with keys: name (English), value (number or null), unit (string), observed_date (YYYY-MM-DD or null).
Use [] if there are no numeric lab values.

This is for the patient's personal health record only."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_data_url(path: Path) -> tuple[str, str]:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return mime, f"data:{mime};base64,{b64}"


def _parse_metadata(md: str) -> tuple[str, str]:
    date_m = re.search(
        r"\*\*Document date:\*\*\s*`?([^`\n]+)`?", md, re.IGNORECASE
    )
    type_m = re.search(
        r"\*\*Document type:\*\*\s*([a-zA-Z_]+)", md, re.IGNORECASE
    )
    raw_date = (date_m.group(1).strip() if date_m else "").strip()
    doc_type = (type_m.group(1).strip().lower() if type_m else "other")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
        raw_date = ""
    # Legacy aliases from older prompts (normalize to short tokens)
    _legacy_doc_type = {
        "imaging_report": "imaging",
        "pathology_report": "pathology",
        "hospitalization_record": "inpatient",
        "surgery_record": "surgery",
    }
    doc_type = _legacy_doc_type.get(doc_type, doc_type)
    if doc_type not in {
        "lab",
        "visit",
        "prescription",
        "imaging",
        "pathology",
        "inpatient",
        "surgery",
        "other",
    }:
        doc_type = "other"
    return raw_date, doc_type


def _parse_metrics_json(md: str) -> list[dict]:
    fence = re.search(r"## Numeric metrics\s*```(?:json)?\s*([\s\S]*?)```", md)
    if not fence:
        return []
    raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        entry: dict = {
            "name": name.strip(),
            "value": item.get("value"),
            "unit": item.get("unit") if isinstance(item.get("unit"), str) else "",
            "observed_date": item.get("observed_date"),
        }
        out.append(entry)
    return out


def _load_processed() -> set[str]:
    if not PROCESSED_PATH.is_file():
        return set()
    try:
        data = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
        hashes = data.get("hashes")
        if isinstance(hashes, list):
            return {str(x).strip().lower() for x in hashes if isinstance(x, str)}
    except (json.JSONDecodeError, OSError):
        pass
    return set()


def _save_processed(hashes: set[str]) -> None:
    PROCESSED_PATH.write_text(
        json.dumps({"hashes": sorted(hashes)}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _load_existing_intermediate_hashes() -> set[str]:
    """
    Recover source image hashes from existing intermediate markdown files.
    This prevents re-parsing if a prior run wrote .md files but crashed before
    processed.json was flushed.
    """
    out: set[str] = set()
    for p in INTERMEDIATE_DIR.glob("*.md"):
        try:
            head = p.read_text(encoding="utf-8")[:800]
        except OSError:
            continue
        m = _SOURCE_SHA_RE.search(head)
        if m:
            out.add(m.group(1).lower())
    return out


def _load_metrics_doc() -> dict:
    if not METRICS_PATH.is_file():
        return {"version": 1, "entries": []}
    try:
        data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            data.setdefault("version", 1)
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"version": 1, "entries": []}


def _save_metrics_doc(doc: dict) -> None:
    METRICS_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _flush_state(processed: set[str], metrics_doc: dict) -> None:
    """Persist incremental state (hashes + metrics) to disk."""
    _save_processed(processed)
    _save_metrics_doc(metrics_doc)


def _format_eta(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "计算中"
    if seconds < 60:
        return f"{max(0, int(seconds))} 秒"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m} 分 {s:02d} 秒"
    h, m = divmod(m, 60)
    return f"{h} 小时 {m:02d} 分"


def _progress_print(
    msg: str,
    *,
    tty: bool,
    newline: bool = False,
) -> None:
    """Progress goes to stderr so stdout stays clean for `print(out)` paths."""
    if newline:
        print(msg, file=sys.stderr, flush=True)
        return
    if tty:
        print(f"\r{msg}", end="", file=sys.stderr, flush=True)
    else:
        print(msg, file=sys.stderr, flush=True)


def _intermediate_basename(
    doc_date: str, doc_type: str, hash8: str, used: set[str]
) -> str:
    base = f"{doc_date}_{doc_type}_{hash8}"
    if base not in used:
        used.add(base)
        return base
    n = 2
    while True:
        cand = f"{doc_date}_{doc_type}_{hash8}_{n}"
        if cand not in used:
            used.add(cand)
            return cand
        n += 1


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

    mime, url = _image_data_url(path)
    messages = [
        {"role": "system", "content": VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": url}},
                {"type": "text", "text": VISION_USER + f"\n\nFilename: {path.name}"},
            ],
        },
    ]
    text = chat_completions(messages, model=model, max_tokens=8192)
    doc_date, doc_type = _parse_metadata(text)
    if not doc_date:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        doc_date = mtime.strftime("%Y-%m-%d")
    hash8 = digest[:8]
    base = _intermediate_basename(doc_date, doc_type, hash8, used_basenames)
    out_path = INTERMEDIATE_DIR / f"{base}.md"
    header = f"<!-- source_file: {path.name} sha256: {digest} parsed_at: {datetime.now(timezone.utc).isoformat()} -->\n\n"
    out_path.write_text(header + text, encoding="utf-8")

    metrics = _parse_metrics_json(text)
    if metrics:
        metrics_doc["entries"].append(
            {
                "source_sha256": digest,
                "source_file": path.name,
                "document_date": doc_date,
                "document_type": doc_type,
                "metrics": metrics,
            }
        )

    processed.add(digest)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse medical images via DashScope vision model.")
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
        help="Save progress to disk after every N image(s) (default: 5). Use 1 for maximum safety.",
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

    if args.recursive:
        files = sorted(
            p
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )
    else:
        files = sorted(
            p
            for p in root.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )

    if not files:
        print("No image files found.")
        return

    processed = _load_processed()
    if not args.force:
        # Defensive de-dupe across runs: trust existing intermediate headers too.
        processed.update(_load_existing_intermediate_hashes())
    metrics_doc = _load_metrics_doc()
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
                        f"预计剩余约 {_format_eta(eta_sec)}"
                    )
                    _progress_print(line, tty=tty, newline=not tty)

            pending_flush += 1
            if pending_flush >= args.batch_size:
                _flush_state(processed, metrics_doc)
                pending_flush = 0

        if pending_flush:
            _flush_state(processed, metrics_doc)

    except KeyboardInterrupt:
        interrupted = True
        _flush_state(processed, metrics_doc)
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
