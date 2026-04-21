#!/usr/bin/env python3
"""Convert Markdown to PDF: pandoc if available, else mistune AST → ReportLab (CJK-capable)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import xml.sax.saxutils as xml_esc
from pathlib import Path
from typing import Any, Iterable

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))


def _find_cjk_font_path() -> Path | None:
    """Locate a TTF/TTC usable for Chinese; override with AURA_PDF_FONT."""
    env = os.environ.get("AURA_PDF_FONT", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    candidates: list[Path] = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        fonts = Path(windir) / "Fonts"
        candidates.extend(
            [
                fonts / "msyh.ttc",
                fonts / "msyhbd.ttc",
                fonts / "simsun.ttc",
                fonts / "simhei.ttf",
                fonts / "msyh.ttf",
            ]
        )
    elif sys.platform == "darwin":
        candidates.extend(
            [
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/STHeiti Light.ttc"),
                Path("/Library/Fonts/Arial Unicode.ttf"),
            ]
        )
    else:
        for base in (
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".local/share/fonts",
        ):
            candidates.extend(
                [
                    base / "truetype/noto/NotoSansCJK-Regular.ttc",
                    base / "opentype/noto/NotoSansCJK-Regular.ttc",
                    base / "truetype/wqy/wqy-microhei.ttc",
                    base / "truetype/arphic/uming.ttc",
                ]
            )
    for c in candidates:
        if c.is_file():
            return c
    return None


def _esc_xml(s: str) -> str:
    return xml_esc.escape(s, entities={'"': "&quot;", "'": "&apos;"})


def _esc_attr(s: str) -> str:
    return xml_esc.escape(s, entities={'"': "&quot;"})


class _MdToReportLab:
    """Build ReportLab flowables from mistune AST (no HTML intermediate)."""

    def __init__(self, md_text: str, font_path: Path | None) -> None:
        import mistune
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        self._colors = colors
        self._A4 = A4
        self._cm = cm
        self._TA_LEFT = TA_LEFT

        md = mistune.create_markdown(
            renderer="ast",
            plugins=["table", "strikethrough"],
        )
        self.tokens: list[dict[str, Any]] = md(md_text)

        self.body_font = "AuraBody"
        self.mono_font = "AuraBody"
        self.font_ok = False
        if font_path is not None:
            suffix = font_path.suffix.lower()
            try:
                if suffix == ".ttc":
                    pdfmetrics.registerFont(
                        TTFont(self.body_font, str(font_path), subfontIndex=0)
                    )
                else:
                    pdfmetrics.registerFont(TTFont(self.body_font, str(font_path)))
                pdfmetrics.registerFontFamily(
                    self.body_font,
                    normal=self.body_font,
                    bold=self.body_font,
                    italic=self.body_font,
                    boldItalic=self.body_font,
                )
                self.mono_font = self.body_font
                self.font_ok = True
            except Exception:
                self.body_font = "Helvetica"
                self.mono_font = "Courier"
        else:
            self.body_font = "Helvetica"
            self.mono_font = "Courier"

        base = getSampleStyleSheet()
        self.styles: dict[str, ParagraphStyle] = {}
        self.styles["Normal"] = ParagraphStyle(
            name="AuraNormal",
            parent=base["Normal"],
            fontName=self.body_font,
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            spaceAfter=6,
            wordWrap="CJK",
        )
        for level, (fs, sp) in enumerate(
            [(22, 10), (18, 8), (15, 8), (13, 6), (12, 6), (11, 4)], start=1
        ):
            self.styles[f"H{level}"] = ParagraphStyle(
                name=f"AuraH{level}",
                parent=self.styles["Normal"],
                fontSize=fs,
                leading=fs + 4,
                spaceBefore=sp,
                spaceAfter=6,
                textColor=colors.HexColor("#111111"),
            )
        self.styles["Bullet"] = ParagraphStyle(
            name="AuraBullet",
            parent=self.styles["Normal"],
            leftIndent=18,
            firstLineIndent=0,
            bulletIndent=0,
            spaceAfter=4,
        )
        self.styles["Quote"] = ParagraphStyle(
            name="AuraQuote",
            parent=self.styles["Normal"],
            leftIndent=14,
            borderColor=colors.HexColor("#cccccc"),
            borderWidth=0,
            textColor=colors.HexColor("#444444"),
        )
        self.styles["Code"] = ParagraphStyle(
            name="AuraCode",
            parent=self.styles["Normal"],
            fontName=self.mono_font,
            fontSize=9,
            leading=11,
            backColor=colors.HexColor("#f6f8fa"),
            leftIndent=8,
            rightIndent=8,
            spaceBefore=4,
            spaceAfter=8,
        )
        self.styles["TableCell"] = ParagraphStyle(
            name="AuraTableCell",
            parent=self.styles["Normal"],
            fontSize=10,
            leading=12,
            wordWrap="CJK",
        )

    def _inline_markup(self, children: Iterable[dict[str, Any]] | None) -> str:
        if not children:
            return ""
        parts: list[str] = []
        for ch in children:
            t = ch.get("type")
            if t == "text":
                parts.append(_esc_xml(str(ch.get("raw", ""))))
            elif t == "strong":
                inner = self._inline_markup(ch.get("children"))
                parts.append(f"<b>{inner}</b>")
            elif t == "emphasis":
                inner = self._inline_markup(ch.get("children"))
                parts.append(f"<i>{inner}</i>")
            elif t == "codespan":
                raw = _esc_xml(str(ch.get("raw", "")))
                parts.append(
                    f'<font name="{self.mono_font}" size="9">{raw}</font>'
                )
            elif t == "link":
                inner = self._inline_markup(ch.get("children"))
                url = ch.get("attrs", {}).get("url", "") or ""
                parts.append(
                    f'<a color="blue" href="{_esc_attr(str(url))}">{inner or _esc_xml(url)}</a>'
                )
            elif t == "image":
                inner = self._inline_markup(ch.get("children"))
                url = ch.get("attrs", {}).get("url", "") or ""
                label = inner or "image"
                parts.append(_esc_xml(f"[{label}]({url})"))
            elif t == "linebreak":
                parts.append("<br/>")
            elif t == "softbreak":
                parts.append(" ")
            elif t == "strikethrough":
                inner = self._inline_markup(ch.get("children"))
                parts.append(f"<strike>{inner}</strike>")
            else:
                raw = ch.get("raw")
                if isinstance(raw, str):
                    parts.append(_esc_xml(raw))
        return "".join(parts)

    def _list_bullet_text(self, ordered: bool, number: int, bullet: str) -> str:
        if ordered:
            return f"{number}. "
        return "• "

    def _list_item_flowables(
        self,
        item: dict[str, Any],
        bullet_text: str,
        depth: int,
        indent_extra: float,
        quote_depth: int,
    ) -> list[Any]:
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph, Spacer

        flows: list[Any] = []
        first = True
        st = ParagraphStyle(
            name=f"BulletDepth{depth}_{id(item) % 100000}",
            parent=self.styles["Bullet"],
            leftIndent=18 + depth * 12 + indent_extra,
            bulletIndent=0,
            firstLineIndent=-10,
        )
        for child in item.get("children") or []:
            ct = child.get("type")
            if ct == "blank_line":
                flows.append(Spacer(1, 4))
                continue
            if ct in ("block_text", "paragraph"):
                kids = child.get("children")
                prefix = bullet_text if first else ""
                text = prefix + self._inline_markup(kids)
                flows.append(Paragraph(text, st))
                first = False
            elif ct == "list":
                flows.extend(
                    self._list_flowables(
                        child,
                        depth + 1,
                        indent_extra=indent_extra,
                        quote_depth=quote_depth,
                    )
                )
            elif ct == "block_quote":
                flows.extend(self._block_quote_flowables(child, quote_depth + 1))
            else:
                raw = child.get("raw")
                if isinstance(raw, str):
                    prefix = bullet_text if first else ""
                    flows.append(Paragraph(prefix + _esc_xml(raw), st))
                    first = False
        return flows

    def _list_flowables(
        self,
        token: dict[str, Any],
        depth: int,
        *,
        indent_extra: float = 0,
        quote_depth: int = 0,
    ) -> list[Any]:
        attrs = token.get("attrs") or {}
        ordered = bool(attrs.get("ordered"))
        n = 1
        out: list[Any] = []
        bullet_char = str(token.get("bullet") or "-")
        for item in token.get("children") or []:
            if item.get("type") != "list_item":
                continue
            bt = self._list_bullet_text(ordered, n, bullet_char)
            out.extend(
                self._list_item_flowables(
                    item, bt, depth, indent_extra, quote_depth=quote_depth
                )
            )
            if ordered:
                n += 1
        return out

    def _block_quote_flowables(
        self, token: dict[str, Any], quote_depth: int
    ) -> list[Any]:
        out: list[Any] = []
        for child in token.get("children") or []:
            out.extend(self._block_flowables(child, quote_depth=quote_depth))
        return out

    def _table_flowable(self, token: dict[str, Any], content_width: float) -> Any:
        from reportlab.lib import colors
        from reportlab.platypus import Paragraph, Table, TableStyle

        header_cells: list[Any] = []
        body_rows: list[list[Any]] = []
        ncols = 0

        for sec in token.get("children") or []:
            st = sec.get("type")
            if st == "table_head":
                row: list[Any] = []
                for cell in sec.get("children") or []:
                    if cell.get("type") == "table_cell":
                        row.append(
                            Paragraph(
                                self._inline_markup(cell.get("children")),
                                self.styles["TableCell"],
                            )
                        )
                if row:
                    ncols = max(ncols, len(row))
                    header_cells = row
            elif st == "table_body":
                for row_tok in sec.get("children") or []:
                    if row_tok.get("type") != "table_row":
                        continue
                    rowp: list[Any] = []
                    for cell in row_tok.get("children") or []:
                        if cell.get("type") == "table_cell":
                            rowp.append(
                                Paragraph(
                                    self._inline_markup(cell.get("children")),
                                    self.styles["TableCell"],
                                )
                            )
                    if rowp:
                        ncols = max(ncols, len(rowp))
                        body_rows.append(rowp)

        data: list[list[Any]] = []
        if header_cells:
            if ncols and len(header_cells) < ncols:
                header_cells.extend(
                    [Paragraph("", self.styles["TableCell"])]
                    * (ncols - len(header_cells))
                )
            data.append(header_cells)
        for br in body_rows:
            if ncols and len(br) < ncols:
                br.extend(
                    [Paragraph("", self.styles["TableCell"])]
                    * (ncols - len(br))
                )
            data.append(br)

        if not data or ncols == 0:
            from reportlab.platypus import Spacer

            return Spacer(1, 1)

        col_w = content_width / ncols
        tbl = Table(data, colWidths=[col_w] * ncols, repeatRows=1 if header_cells else 0)
        tbl.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return tbl

    def _block_flowables(
        self, token: dict[str, Any], quote_depth: int = 0
    ) -> list[Any]:
        from reportlab.platypus import HRFlowable, Paragraph, Preformatted, Spacer

        t = token.get("type")
        out: list[Any] = []

        if t == "blank_line":
            out.append(Spacer(1, 6))
            return out

        if t == "thematic_break":
            out.append(Spacer(1, 8))
            out.append(HRFlowable(width="100%", thickness=0.5, color=self._colors.grey))
            out.append(Spacer(1, 8))
            return out

        if t == "block_html":
            raw = str(token.get("raw", "")).strip()
            if raw:
                out.append(Preformatted(raw[:8000], self.styles["Code"]))
            return out

        if t == "block_code":
            raw = str(token.get("raw", ""))
            out.append(Preformatted(raw.rstrip("\n") + "\n", self.styles["Code"]))
            return out

        if t == "heading":
            level = int((token.get("attrs") or {}).get("level") or 1)
            level = max(1, min(level, 6))
            text = self._inline_markup(token.get("children"))
            out.append(Paragraph(text, self.styles[f"H{level}"]))
            return out

        if t == "paragraph":
            from reportlab.lib.styles import ParagraphStyle

            if quote_depth:
                st = ParagraphStyle(
                    name=f"Quote{quote_depth}_{id(token) % 100000}",
                    parent=self.styles["Normal"],
                    leftIndent=10 + quote_depth * 12,
                    textColor=self._colors.HexColor("#333333"),
                    wordWrap="CJK",
                )
            else:
                st = self.styles["Normal"]
            out.append(Paragraph(self._inline_markup(token.get("children")), st))
            return out

        if t == "list":
            out.extend(self._list_flowables(token, depth=0, quote_depth=quote_depth))
            return out

        if t == "block_quote":
            out.extend(self._block_quote_flowables(token, quote_depth + 1))
            return out

        if t == "table":
            from reportlab.lib.pagesizes import A4

            usable = A4[0] - 4 * self._cm
            out.append(Spacer(1, 4))
            out.append(self._table_flowable(token, usable))
            out.append(Spacer(1, 8))
            return out

        raw = token.get("raw")
        if isinstance(raw, str) and raw.strip():
            out.append(Paragraph(_esc_xml(raw.strip()), self.styles["Normal"]))
        return out

    def build_story(self) -> list[Any]:
        story: list[Any] = []
        for tok in self.tokens:
            story.extend(self._block_flowables(tok))
        return story

    def write_pdf(self, pdf_path: Path) -> None:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=2 * self._cm,
            rightMargin=2 * self._cm,
            topMargin=2 * self._cm,
            bottomMargin=2 * self._cm,
        )
        doc.build(self.build_story())


def _md_to_pdf_reportlab(md_text: str, pdf_path: Path) -> None:
    font_path = _find_cjk_font_path()
    conv = _MdToReportLab(md_text, font_path)
    if not conv.font_ok:
        print(
            "Warning: no CJK font found; Chinese may not render correctly. "
            "Set AURA_PDF_FONT to a .ttf/.ttc path (e.g. Noto Sans CJK).",
            file=sys.stderr,
        )
    conv.write_pdf(pdf_path)


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
        _md_to_pdf_reportlab(md_text, pdf_path)
    except ImportError as e:
        raise SystemExit(
            "pandoc not found in PATH and ReportLab/mistune are not installed. "
            "Install pandoc (https://pandoc.org) or run: pip install -r requirements.txt"
        ) from e
    except Exception as e:
        raise RuntimeError(
            "PDF fallback (ReportLab) failed. Install pandoc for best layout, "
            "or set AURA_PDF_FONT to a Chinese-capable .ttf/.ttc."
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
