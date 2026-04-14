"""Track which intermediate source hashes are reflected in the latest profile (incremental updates)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from config import AURA_STATE_HOME, INTERMEDIATE_DIR, PROFILE_MERGE_STATE_PATH

_SHA_RE = re.compile(
    r"<!--\s*source_file:\s*[^>]*?\bsha256:\s*([a-f0-9]{64})\b",
    re.IGNORECASE | re.DOTALL,
)


def extract_intermediate_sha256(markdown_text: str) -> str | None:
    """Parse sha256 from vision_parser HTML comment at start of intermediate file."""
    head = markdown_text[:800]
    m = _SHA_RE.search(head)
    return m.group(1).lower() if m else None


def all_intermediate_sha256s() -> dict[str, Path]:
    """Map sha256 -> path for each intermediate that declares a sha."""
    out: dict[str, Path] = {}
    for p in sorted(INTERMEDIATE_DIR.glob("*.md")):
        sha = extract_intermediate_sha256(p.read_text(encoding="utf-8"))
        if sha:
            out.setdefault(sha, p)
    return out


def load_merge_state() -> dict | None:
    if not PROFILE_MERGE_STATE_PATH.is_file():
        return None
    try:
        data = json.loads(PROFILE_MERGE_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("merged_source_sha256"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_merge_state(
    *,
    last_profile_path: Path,
    last_profile_ymd: str,
    merged_source_sha256: set[str],
) -> None:
    AURA_STATE_HOME.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": 1,
        "last_profile_path": str(last_profile_path.resolve()),
        "last_profile_ymd": last_profile_ymd,
        "merged_source_sha256": sorted(merged_source_sha256),
    }
    PROFILE_MERGE_STATE_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def merged_shas_after_success() -> set[str]:
    """All source shas currently on disk under intermediate/ (post-build/update)."""
    return set(all_intermediate_sha256s().keys())


def merged_shas_from_paths(paths: list[Path]) -> set[str]:
    """Source image sha256 values for the given intermediate files (for merge state after QC)."""
    out: set[str] = set()
    for p in paths:
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            continue
        sha = extract_intermediate_sha256(body)
        if sha:
            out.add(sha)
    return out


def list_new_intermediate_paths(
    *,
    known_shas: set[str],
    profile_mtime: float,
    full: bool,
) -> list[Path]:
    """
    Paths to feed the model as *new* chunks.
    If full=True, return all intermediates. Otherwise sha not in known_shas, or legacy mtime rule.
    """
    paths = sorted(INTERMEDIATE_DIR.glob("*.md"))
    if full:
        return paths
    new: list[Path] = []
    for p in paths:
        body = p.read_text(encoding="utf-8")
        sha = extract_intermediate_sha256(body)
        if sha:
            if sha not in known_shas:
                new.append(p)
        else:
            if p.stat().st_mtime > profile_mtime:
                new.append(p)
    return new
