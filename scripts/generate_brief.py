#!/usr/bin/env python3
"""Generate revisit brief markdown, PDF, and styled image from profile."""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from config import (
    DEFAULT_TEXT_MODEL,
    OUTPUT_ROOT,
    chat_completions,
    ensure_state_dirs,
    load_api_key,
    preferred_language,
    skill_dir,
)
from md_to_pdf import md_to_pdf

IMAGE_GEN_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation"
)
TASK_STATUS_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
DEFAULT_IMAGE_MODEL = os.environ.get("AURA_IMAGE_MODEL", "wan2.7-image-pro")


def _find_latest_profile(root: Path) -> Path | None:
    best: Path | None = None
    best_ymd = ""
    for p in root.glob("health_profile_*.md"):
        stem = p.stem
        ymd = stem.rsplit("_", 1)[-1]
        if len(ymd) != 8 or not ymd.isdigit():
            continue
        if best is None or ymd > best_ymd or (
            ymd == best_ymd and p.stat().st_mtime > best.stat().st_mtime
        ):
            best = p
            best_ymd = ymd
    return best


def _extract_url_from_payload(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    output = data.get("output")
    if isinstance(output, dict):
        results = output.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    url = item.get("url")
                    if isinstance(url, str) and url:
                        return url
        url = output.get("url")
        if isinstance(url, str) and url:
            return url
        # Wan 2.7 multimodal-generation format: output.choices[0].message.content[0].image
        choices = output.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                img_url = block.get("image")
                                if isinstance(img_url, str) and img_url:
                                    return img_url
    results = data.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                url = item.get("url")
                if isinstance(url, str) and url:
                    return url
    return None


def _extract_b64_from_payload(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    output = data.get("output")
    if isinstance(output, dict):
        results = output.get("results")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    b64 = item.get("b64_image") or item.get("base64_image")
                    if isinstance(b64, str) and b64:
                        return b64
    return None


def _task_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    output = data.get("output")
    if isinstance(output, dict):
        v = output.get("task_id") or output.get("taskId")
        if isinstance(v, str) and v:
            return v
    v = data.get("task_id") or data.get("taskId")
    if isinstance(v, str) and v:
        return v
    return None


def _task_state(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    output = data.get("output")
    if isinstance(output, dict):
        v = output.get("task_status") or output.get("taskStatus")
        if isinstance(v, str):
            return v.upper()
    v = data.get("task_status") or data.get("taskStatus")
    if isinstance(v, str):
        return v.upper()
    return ""


def _render_image(
    *,
    prompt: str,
    output_path: Path,
    model: str,
    size: str,
    timeout_seconds: int,
    poll_interval: float,
) -> None:
    api_key = load_api_key()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async_headers = {**base_headers, "X-DashScope-Async": "enable"}

    def _request_with_payloads(headers: dict[str, str]) -> tuple[requests.Response | None, str]:
        r_local: requests.Response | None = None
        err = ""
        for payload in payloads:
            r_local = requests.post(
                IMAGE_GEN_URL,
                headers=headers,
                json=payload,
                timeout=120,
            )
            if r_local.ok:
                return r_local, ""
            err = f"Wan HTTP {r_local.status_code}: {r_local.text[:2000]}"
        return r_local, err

    payloads = [
        # Official Wan image-generation shape (messages + extended parameters).
        {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ]
            },
            "parameters": {
                "size": size,
                "n": 1,
                "watermark": False,
                "thinking_mode": True,
            },
        },
        # Compatibility shape if some tenants reject extended parameters.
        {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ]
            },
            "parameters": {"size": size, "n": 1},
        },
        # Older prompt-only shape.
        {
            "model": model,
            "input": {"prompt": prompt},
            "parameters": {"size": size, "n": 1},
        },
    ]

    # Try async first; fallback to sync when account lacks async permission.
    r, last_err = _request_with_payloads(async_headers)
    if (
        r is not None
        and r.status_code == 403
        and "does not support asynchronous calls" in (r.text or "")
    ):
        r, last_err = _request_with_payloads(base_headers)

    if r is None or not r.ok:
        raise RuntimeError(last_err or "Wan request failed with unknown error")
    data = r.json()

    url = _extract_url_from_payload(data)
    if url:
        content = requests.get(url, timeout=180)
        content.raise_for_status()
        output_path.write_bytes(content.content)
        return

    b64 = _extract_b64_from_payload(data)
    if b64:
        output_path.write_bytes(base64.b64decode(b64))
        return

    task_id = _task_id(data)
    if not task_id:
        raise RuntimeError(f"Cannot parse image generation response: {data!r}")

    deadline = time.monotonic() + max(30, timeout_seconds)
    status_headers = base_headers
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(f"Wan task timeout: {task_id}")
        rs = requests.get(
            TASK_STATUS_URL.format(task_id=task_id),
            headers=status_headers,
            timeout=60,
        )
        if not rs.ok:
            raise RuntimeError(f"Wan task HTTP {rs.status_code}: {rs.text[:2000]}")
        s_data = rs.json()
        state = _task_state(s_data)
        if state in {"SUCCEEDED", "SUCCESS"}:
            url = _extract_url_from_payload(s_data)
            if url:
                content = requests.get(url, timeout=180)
                content.raise_for_status()
                output_path.write_bytes(content.content)
                return
            b64 = _extract_b64_from_payload(s_data)
            if b64:
                output_path.write_bytes(base64.b64decode(b64))
                return
            raise RuntimeError(f"Wan task finished but no image found: {s_data!r}")
        if state in {"FAILED", "CANCELED", "CANCELLED"}:
            raise RuntimeError(f"Wan task failed: {s_data!r}")
        time.sleep(max(0.5, poll_interval))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate revisit brief markdown, PDF, and image."
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Input health profile markdown (default: latest health_profile_*.md)",
    )
    parser.add_argument(
        "--date",
        help="YYYYMMDD for output filename suffix (default: today local)",
    )
    parser.add_argument(
        "--text-model",
        default=DEFAULT_TEXT_MODEL,
        help=f"Text model (default: {DEFAULT_TEXT_MODEL})",
    )
    parser.add_argument(
        "--image-model",
        default=DEFAULT_IMAGE_MODEL,
        help=f"Image model (default: {DEFAULT_IMAGE_MODEL})",
    )
    parser.add_argument(
        "--size",
        default="1024*1792",
        help="Output image size for Wan API (default: 1024*1792, portrait 9:16)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Wan task polling interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout seconds for each image generation task (default: 300)",
    )
    args = parser.parse_args()

    ensure_state_dirs()
    ymd = args.date or datetime.now().strftime("%Y%m%d")
    if not (ymd.isdigit() and len(ymd) == 8):
        raise SystemExit("--date must be YYYYMMDD")

    profile_path = args.profile.resolve() if args.profile else _find_latest_profile(OUTPUT_ROOT)
    if profile_path is None or not profile_path.is_file():
        raise SystemExit(
            f"No profile found under {OUTPUT_ROOT} (health_profile_*.md). "
            "Run build_profile.py first or pass --profile."
        )

    base = skill_dir()
    use_chinese = preferred_language() == "zh-CN"
    template_path = (
        base / "assets" / "brief_template_cn.md"
        if use_chinese
        else base / "assets" / "brief_template.md"
    )
    if not template_path.is_file():
        template_path = base / "assets" / "brief_template.md"
    if not template_path.is_file():
        raise SystemExit(f"Missing template: {template_path}")

    profile_text = profile_path.read_text(encoding="utf-8")
    template_text = template_path.read_text(encoding="utf-8")
    language_rule = (
        "Output in Simplified Chinese."
        if use_chinese
        else "Output in concise English."
    )

    summary_user = f"""Create a short revisit brief card from this chronic-care profile.
Follow the template exactly and keep it concise. {language_rule}

Template:
{template_text}

Profile markdown:
{profile_text}
"""
    summary_md = chat_completions(
        [
            {
                "role": "system",
                "content": (
                    "You produce brief, factual medical visit prep summaries. "
                    "No diagnosis or treatment advice."
                ),
            },
            {"role": "user", "content": summary_user},
        ],
        model=args.text_model,
        max_tokens=4096,
    ).strip()

    out_md = OUTPUT_ROOT / f"revisit_brief_{ymd}.md"
    disclaimer = (
        "> **免责声明：** 本简报仅用于就诊材料整理，不构成医疗建议。\n\n"
        if use_chinese
        else "> **Disclaimer:** This brief is for visit preparation only, not medical advice.\n\n"
    )
    out_md.write_text(disclaimer + summary_md.lstrip() + "\n", encoding="utf-8")

    brief_prompt = (
        "Design a polished one-page medical revisit brief image for doctor consultation. "
        "Use portrait 9:16 composition suitable for mobile viewing and quick doctor scanning. "
        "Use a clear, professional clinical style that is easy to read on phone and print. "
        "White background, blue/teal accents, high contrast text, no logos, no watermark. "
        "Use visible section blocks/cards with clear separators and hierarchy. "
        "Highlight key risks and important abnormal values with color tags or badges. "
        "Include compact data visualization (mini trend lines or bar indicators) for key metrics mentioned in the content. "
        "Add small, consistent medical icons/pictograms for EACH section (for example: profile, symptoms, meds, labs, questions, warning, safety), "
        "and simple inline diagram cues where helpful. Keep icons minimal and unobtrusive so text remains dominant and readable. "
        "Keep typography clean and readable for Chinese and English text. "
        "Avoid decorative clutter. Prioritize medical readability.\n\n"
        "Required layout zones:\n"
        "1) Header: revisit brief title + date\n"
        "2) Condition overview\n"
        "3) Recent changes / warning signs\n"
        "4) Current medications\n"
        "5) Key indicators with visual cues\n"
        "6) Questions for doctor\n"
        "7) Safety disclaimer footer\n\n"
        "Render concise, legible text directly from this markdown content:\n\n"
        f"{summary_md}\n"
    )

    brief_png = OUTPUT_ROOT / f"brief_{ymd}.png"
    out_pdf = OUTPUT_ROOT / f"revisit_brief_{ymd}.pdf"

    _render_image(
        prompt=brief_prompt,
        output_path=brief_png,
        model=args.image_model,
        size=args.size,
        timeout_seconds=args.timeout,
        poll_interval=args.poll_interval,
    )
    # Try CJK-aware PDF generator first, fall back to md_to_pdf
    scripts_dir = Path(__file__).resolve().parent
    gen_cjk = scripts_dir / "gen_cjk_pdf.py"
    if gen_cjk.exists():
        import subprocess
        result = subprocess.run(
            [sys.executable, str(gen_cjk), str(out_md), str(out_pdf)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            md_to_pdf(out_md, out_pdf)
    else:
        md_to_pdf(out_md, out_pdf)

    print(out_md)
    print(brief_png)
    print(out_pdf)


if __name__ == "__main__":
    main()
