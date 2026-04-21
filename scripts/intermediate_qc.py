"""Classify intermediate Markdown from vision_parser / pdf_vision_parser: usable vs duplicate vs abnormal."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from profile_merge_state import extract_intermediate_sha256

# Minimum body length (after HTML comment) for a plausible parse
_MIN_BODY_LEN = 120

# Required sections from vision_parser prompt (case-insensitive match on heading line)
_REQUIRED_SUBSTR = (
    "## document metadata",
    "## extracted content",
)


def _strip_html_comment_header(text: str) -> str:
    t = text.lstrip()
    if t.startswith("<!--"):
        end = t.find("-->")
        if end != -1:
            return t[end + 3 :].lstrip()
    return text


def _normalize_for_fingerprint(body: str) -> str:
    return re.sub(r"\s+", " ", body.strip().lower())


def content_fingerprint(body: str) -> str:
    return hashlib.sha256(_normalize_for_fingerprint(body).encode("utf-8")).hexdigest()


def _abnormal_reasons(body: str, sha: str | None) -> list[str]:
    reasons: list[str] = []
    if sha is None:
        reasons.append("missing_source_sha256")
    low = body.lower()
    for sec in _REQUIRED_SUBSTR:
        if sec not in low:
            reasons.append(f"missing_section:{sec.replace('#', '').strip()}")
    stripped = body.strip()
    if len(stripped) < _MIN_BODY_LEN:
        reasons.append("body_too_short")
    n = len(body)
    if n > 0:
        repl = body.count("\ufffd")
        if repl >= 8 or (repl / n) >= 0.003:
            reasons.append("replacement_characters")
    if len(stripped) >= 200:
        words = stripped.lower().split()
        if len(words) >= 20 and len(set(words)) < 10:
            reasons.append("low_lexical_diversity")
    return reasons


@dataclass
class QcExcluded:
    file: str
    reason: str
    detail: str


def partition_intermediates(paths: list[Path]) -> tuple[list[Path], list[QcExcluded]]:
    """
    Return (included_paths, excluded) in sorted filename order.
    First occurrence wins for duplicate source sha256 or duplicate normalized body.
    """
    sorted_paths = sorted(paths, key=lambda p: p.name)
    first_sha: dict[str, Path] = {}
    first_fp: dict[str, Path] = {}
    included: list[Path] = []
    excluded: list[QcExcluded] = []

    for p in sorted_paths:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            excluded.append(
                QcExcluded(file=p.name, reason="abnormal", detail=f"read_error:{e}")
            )
            continue

        sha = extract_intermediate_sha256(text)
        body = _strip_html_comment_header(text)
        fp = content_fingerprint(body)

        if sha and sha in first_sha:
            excluded.append(
                QcExcluded(
                    file=p.name,
                    reason="duplicate",
                    detail=f"same_sha256_as:{first_sha[sha].name}",
                )
            )
            continue
        if fp in first_fp:
            excluded.append(
                QcExcluded(
                    file=p.name,
                    reason="duplicate",
                    detail=f"same_content_as:{first_fp[fp].name}",
                )
            )
            continue

        if sha:
            first_sha[sha] = p
        first_fp[fp] = p

        bad = _abnormal_reasons(body, sha)
        if bad:
            excluded.append(
                QcExcluded(file=p.name, reason="abnormal", detail=";".join(bad))
            )
            continue

        included.append(p)

    return included, excluded


def write_qc_artifact(
    *,
    path: Path,
    included: list[Path],
    excluded: list[QcExcluded],
    label: str = "build",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "version": 1,
        "label": label,
        "included": [p.name for p in included],
        "excluded": [asdict(x) for x in excluded],
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def format_qc_markdown_section(excluded: list[QcExcluded]) -> str:
    if not excluded:
        return ""
    lines = [
        "",
        "---",
        "",
        "## Build QC (automated)",
        "",
        "The following intermediate files were **not** used when generating this profile:",
        "",
        "| File | Reason | Detail |",
        "|------|--------|--------|",
    ]
    for x in excluded:
        det = x.detail.replace("|", "\\|")
        lines.append(f"| `{x.file}` | {x.reason} | {det} |")
    lines.append("")
    return "\n".join(lines)
