#!/usr/bin/env python3
"""Convert Markdown to PDF (pandoc if available, else xhtml2pdf)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

import markdown


def _md_to_html(md_text: str) -> str:
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
           font-size: 11pt; line-height: 1.45; margin: 2cm; }}
    h1, h2, h3 {{ margin-top: 1.2em; }}
    table {{ border-collapse: collapse; width: 100%; margin: 0.8em 0; }}
    th, td {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
    code, pre {{ font-family: Menlo, Consolas, monospace; font-size: 0.9em; }}
    pre {{ background: #f6f8fa; padding: 8px; overflow-x: auto; }}
    blockquote {{ border-left: 4px solid #ddd; margin-left: 0; padding-left: 1em; color: #555; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _md_to_pdf_fpdf2(md_text: str, pdf_path: Path) -> None:
    """Fallback when pandoc is missing: HTML → PDF via fpdf2 (best effort; use pandoc for CJK)."""
    from fpdf import FPDF

    html = _md_to_html(md_text)
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.write_html(html)
    pdf.output(str(pdf_path))


def md_to_pdf(md_path: Path, pdf_path: Path) -> None:
    md_text = md_path.read_text(encoding="utf-8")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    pandoc = shutil.which("pandoc")
    if pandoc:
        subprocess.run(
            [pandoc, str(md_path), "-o", str(pdf_path)],
            check=True,
        )
        return

    try:
        _md_to_pdf_fpdf2(md_text, pdf_path)
    except ImportError as e:
        raise SystemExit(
            "pandoc not found in PATH and fpdf2 is not installed. "
            "Install pandoc (https://pandoc.org) or run: pip install fpdf2"
        ) from e
    except Exception as e:
        raise RuntimeError(
            "PDF fallback (fpdf2) failed. Install pandoc for reliable output, "
            "especially for non-Latin text."
        ) from e


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert Markdown file to PDF.")
    parser.add_argument("markdown", type=Path, help="Input .md path")
    parser.add_argument(
        "pdf",
        type=Path,
        nargs="?",
        help="Output .pdf path (default: same basename as input)",
    )
    args = parser.parse_args()
    md_path = args.markdown.resolve()
    if not md_path.is_file():
        raise SystemExit(f"Not a file: {md_path}")
    pdf_path = args.pdf.resolve() if args.pdf else md_path.with_suffix(".pdf")
    md_to_pdf(md_path, pdf_path)
    print(pdf_path)


if __name__ == "__main__":
    main()
