from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import uuid
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from export_ai_report_docx import build_docx  # noqa: E402

PAGE_SIZE = letter
LEFT_MARGIN = 0.72 * inch
RIGHT_MARGIN = 0.72 * inch
TOP_MARGIN = 0.7 * inch
BOTTOM_MARGIN = 0.65 * inch
AVAILABLE_WIDTH = PAGE_SIZE[0] - LEFT_MARGIN - RIGHT_MARGIN


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "CW2Body",
        parent=base["BodyText"],
        fontName="Helvetica",
        fontSize=10.0,
        leading=13.0,
        textColor=colors.HexColor("#222222"),
        spaceAfter=6,
        alignment=TA_LEFT,
    )
    return {
        "Title": ParagraphStyle(
            "CW2Title",
            parent=body,
            fontName="Helvetica",
            fontSize=24,
            leading=29,
            textColor=colors.HexColor("#17365D"),
            alignment=TA_CENTER,
            spaceAfter=16,
        ),
        "Heading 1": ParagraphStyle(
            "CW2Heading1",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#17365D"),
            spaceBefore=14,
            spaceAfter=8,
        ),
        "Heading 2": ParagraphStyle(
            "CW2Heading2",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            textColor=colors.HexColor("#4472C4"),
            spaceBefore=10,
            spaceAfter=5,
        ),
        "Heading 3": ParagraphStyle(
            "CW2Heading3",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#1F4E79"),
            spaceBefore=7,
            spaceAfter=4,
        ),
        "Body": body,
        "Bullet": ParagraphStyle(
            "CW2Bullet",
            parent=body,
            leftIndent=12,
            firstLineIndent=-8,
            spaceAfter=4,
        ),
        "Caption": ParagraphStyle(
            "CW2Caption",
            parent=body,
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#444444"),
            spaceBefore=2,
            spaceAfter=7,
        ),
        "TableCell": ParagraphStyle(
            "CW2TableCell",
            parent=body,
            fontSize=7.5,
            leading=9.2,
            spaceAfter=0,
        ),
        "TableHeader": ParagraphStyle(
            "CW2TableHeader",
            parent=body,
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9.2,
            textColor=colors.white,
            spaceAfter=0,
        ),
    }


def _iter_blocks(document: Document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield DocxParagraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield DocxTable(child, document)


def _paragraph_markup(paragraph: DocxParagraph) -> str:
    parts: list[str] = []
    for run in paragraph.runs:
        text = html.escape(run.text or "").replace("\n", "<br/>")
        if not text:
            continue
        if run.bold:
            text = f"<b>{text}</b>"
        if run.italic:
            text = f"<i>{text}</i>"
        parts.append(text)
    return "".join(parts).strip()


def _paragraph_style_name(paragraph: DocxParagraph) -> str:
    style_name = getattr(paragraph.style, "name", "") or ""
    if style_name in {"Title", "Heading 1", "Heading 2", "Heading 3"}:
        return style_name
    if "bullet" in style_name.lower():
        return "Bullet"
    return "Body"


def _paragraph_images(paragraph: DocxParagraph) -> list[bytes]:
    blobs: list[bytes] = []
    for rel_id in paragraph._p.xpath(".//a:blip/@r:embed"):
        part = paragraph.part.related_parts.get(rel_id)
        if part is not None and getattr(part, "blob", None):
            blobs.append(part.blob)
    return blobs


def _image_flowable(blob: bytes) -> Image:
    with PILImage.open(BytesIO(blob)) as image:
        width_px, height_px = image.size
    if not width_px or not height_px:
        raise RuntimeError("Embedded image has invalid dimensions.")
    max_width = AVAILABLE_WIDTH
    max_height = 3.45 * inch
    ratio = min(max_width / float(width_px), max_height / float(height_px), 1.0)
    return Image(BytesIO(blob), width=width_px * ratio, height=height_px * ratio)


def _table_flowable(table: DocxTable, styles: dict[str, ParagraphStyle]) -> LongTable | None:
    rows: list[list[Paragraph]] = []
    max_cols = 0
    for row in table.rows:
        cells = []
        for cell in row.cells:
            text = html.escape("\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip()))
            text = text.replace("\n", "<br/>") or " "
            style = styles["TableHeader"] if not rows else styles["TableCell"]
            cells.append(Paragraph(text, style))
        max_cols = max(max_cols, len(cells))
        rows.append(cells)
    if not rows or not max_cols:
        return None
    for row in rows:
        row.extend([Paragraph(" ", styles["TableCell"])] * (max_cols - len(row)))
    col_width = AVAILABLE_WIDTH / max_cols
    pdf_table = LongTable(rows, colWidths=[col_width] * max_cols, repeatRows=1, hAlign="LEFT")
    pdf_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B7B7B7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return pdf_table


def _docx_to_flowables(source_docx: Path) -> list:
    document = Document(str(source_docx))
    styles = _styles()
    story: list = []
    heading1_seen = 0
    for block in _iter_blocks(document):
        if isinstance(block, DocxParagraph):
            markup = _paragraph_markup(block)
            style_name = _paragraph_style_name(block)
            images = _paragraph_images(block)
            if markup:
                if style_name == "Heading 1":
                    heading1_seen += 1
                    if heading1_seen > 1:
                        story.append(PageBreak())
                paragraph = Paragraph(markup, styles[style_name])
                if style_name == "Bullet":
                    story.append(Paragraph(f"- {markup}", styles["Bullet"]))
                elif markup.lower().startswith(("fig. ", "tbl. ")):
                    story.append(Paragraph(markup, styles["Caption"]))
                else:
                    story.append(paragraph)
            for blob in images:
                story.append(Spacer(1, 4))
                story.append(_image_flowable(blob))
                story.append(Spacer(1, 4))
        elif isinstance(block, DocxTable):
            pdf_table = _table_flowable(block, styles)
            if pdf_table is not None:
                story.append(Spacer(1, 4))
                story.append(pdf_table)
                story.append(Spacer(1, 6))
    return story


def _page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawRightString(PAGE_SIZE[0] - RIGHT_MARGIN, 0.36 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _write_text_pdf(source_docx: Path, output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output_pdf),
        pagesize=PAGE_SIZE,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title="Investment Portfolio Analysis Report",
        author="CW2 AI Report Generator",
        pageCompression=1,
    )
    story = _docx_to_flowables(source_docx)
    if not story:
        raise RuntimeError("PDF export found no report content to render.")
    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    if not output_pdf.exists() or output_pdf.stat().st_size <= 0:
        raise RuntimeError("PDF export did not produce an output file.")


def export_pdf(payload: dict, output_pdf: Path, debug_render_dir: Path | None = None) -> None:
    base_dir = Path(str(payload.get("base_dir") or output_pdf.parent))
    tmp_root = base_dir / "_tmp_pdf"
    tmp_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = tmp_root / f"p_{uuid.uuid4().hex[:8]}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        source_docx = tmp_dir / "source.docx"
        build_docx(payload, source_docx)
        if debug_render_dir is not None:
            debug_render_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_docx, debug_render_dir / "source.docx")
        _write_text_pdf(source_docx, output_pdf)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the CW2 AI report as a selectable-text PDF."
    )
    parser.add_argument("--input-json", required=True, help="Path to the AI report payload JSON.")
    parser.add_argument("--output-pdf", required=True, help="Path to the PDF report to create.")
    parser.add_argument(
        "--debug-render-dir",
        default=None,
        help="Optional directory that receives the intermediate source DOCX for debugging.",
    )
    args = parser.parse_args()
    input_json = Path(args.input_json)
    output_pdf = Path(args.output_pdf)
    debug_render_dir = Path(args.debug_render_dir) if args.debug_render_dir else None
    export_pdf(_read_json(input_json), output_pdf, debug_render_dir=debug_render_dir)
    print(str(output_pdf))


if __name__ == "__main__":
    main()
