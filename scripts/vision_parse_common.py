"""Shared vision parsing helpers for image and PDF pipelines (UTF-8 Markdown + metrics)."""

from __future__ import annotations

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

from config import (
    INTERMEDIATE_DIR,
    METRICS_PATH,
    PROCESSED_PATH,
    chat_completions,
)

SOURCE_SHA_RE = re.compile(
    r"<!--\s*source_file:\s*[^>]*?\bsha256:\s*([a-f0-9]{64})\b",
    re.IGNORECASE | re.DOTALL,
)

VISION_SYSTEM = """You are a medical document digitization assistant. Extract text and structure from images accurately. Output Markdown only. Do not diagnose or give treatment advice.

Use UTF-8. Preserve Chinese (简体中文 / 繁体), Japanese, Korean, and Latin text exactly as printed—do not garble, substitute homophones, or unnecessary pinyin."""

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


def _data_url_from_bytes(mime: str, raw: bytes) -> str:
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _call_vision(
    image_url: str,
    filename_for_prompt: str,
    *,
    model: str,
    user_suffix: str = "",
) -> str:
    """Call vision model. Optional ``user_suffix`` is appended after the main instructions (before Filename)."""
    extra = f"\n\n{user_suffix.strip()}" if user_suffix.strip() else ""
    user_text = VISION_USER + extra + f"\n\nFilename: {filename_for_prompt}"
    messages = [
        {"role": "system", "content": VISION_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": user_text},
            ],
        },
    ]
    return chat_completions(messages, model=model, max_tokens=8192)


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


def write_intermediate_from_vision(
    text: str,
    *,
    content_digest: str,
    source_comment: str,
    path_for_mtime: Path,
    metrics_source_file: str,
    processed: set[str],
    metrics_doc: dict,
    used_basenames: set[str],
) -> Path:
    doc_date, doc_type = _parse_metadata(text)
    if not doc_date:
        # Keep unknown report dates explicit; do not infer from file mtime.
        doc_date = "Unknown"
    hash8 = content_digest[:8]
    base = _intermediate_basename(doc_date, doc_type, hash8, used_basenames)
    out_path = INTERMEDIATE_DIR / f"{base}.md"
    header = (
        f"<!-- source_file: {source_comment} parsed_at: "
        f"{datetime.now(timezone.utc).isoformat()} -->\n\n"
    )
    out_path.write_text(header + text, encoding="utf-8")

    metrics = _parse_metrics_json(text)
    if metrics:
        metrics_doc["entries"].append(
            {
                "source_sha256": content_digest,
                "source_file": metrics_source_file,
                "document_date": doc_date,
                "document_type": doc_type,
                "metrics": metrics,
            }
        )

    processed.add(content_digest)
    return out_path


def write_intermediate_from_vision_with_doc_fields(
    text: str,
    *,
    content_digest: str,
    source_comment: str,
    path_for_mtime: Path,
    metrics_source_file: str,
    document_date: str,
    document_type: str,
    processed: set[str],
    metrics_doc: dict,
    used_basenames: set[str],
) -> Path:
    """Write intermediate using explicit document_date / document_type (e.g. PDF from page 1)."""
    hash8 = content_digest[:8]
    base = _intermediate_basename(document_date, document_type, hash8, used_basenames)
    out_path = INTERMEDIATE_DIR / f"{base}.md"
    header = (
        f"<!-- source_file: {source_comment} parsed_at: "
        f"{datetime.now(timezone.utc).isoformat()} -->\n\n"
    )
    out_path.write_text(header + text, encoding="utf-8")

    metrics = _parse_metrics_json(text)
    if metrics:
        metrics_doc["entries"].append(
            {
                "source_sha256": content_digest,
                "source_file": metrics_source_file,
                "document_date": document_date,
                "document_type": document_type,
                "metrics": metrics,
            }
        )

    processed.add(content_digest)
    return out_path


def load_processed() -> set[str]:
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


def save_processed(hashes: set[str]) -> None:
    PROCESSED_PATH.write_text(
        json.dumps({"hashes": sorted(hashes)}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def load_existing_intermediate_hashes() -> set[str]:
    out: set[str] = set()
    for p in INTERMEDIATE_DIR.glob("*.md"):
        try:
            head = p.read_text(encoding="utf-8")[:800]
        except OSError:
            continue
        m = SOURCE_SHA_RE.search(head)
        if m:
            out.add(m.group(1).lower())
    return out


def load_metrics_doc() -> dict:
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


def save_metrics_doc(doc: dict) -> None:
    METRICS_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def flush_state(processed: set[str], metrics_doc: dict) -> None:
    save_processed(processed)
    save_metrics_doc(metrics_doc)


def format_eta(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "计算中"
    if seconds < 60:
        return f"{max(0, int(seconds))} 秒"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m} 分 {s:02d} 秒"
    h, m = divmod(m, 60)
    return f"{h} 小时 {m:02d} 分"


def progress_print(
    msg: str,
    *,
    tty: bool,
    newline: bool = False,
) -> None:
    if newline:
        print(msg, file=sys.stderr, flush=True)
        return
    if tty:
        print(f"\r{msg}", end="", file=sys.stderr, flush=True)
    else:
        print(msg, file=sys.stderr, flush=True)
