"""
layout_detector.py — Phân loại layout trang và phân đoạn block.

Trách nhiệm:
  1. Phân loại layout trang: 1 cột hoặc 2 cột.
  2. Thu thập tất cả block (text, table, image) từ PyMuPDF.
  3. Sắp xếp theo Reading Order chính xác.
  4. Gán block_id bất biến từ 0..N-1.
  5. Crop ảnh PNG bytes cho các block IMAGE/MATH.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import fitz  # PyMuPDF

from .config import (
    FOOTER_ZONE_PT,
    HEADER_ZONE_PT,
    MATH_CHAR_RATIO_THRESHOLD,
    MATH_UNICODE_CHARS,
    OCR_MIN_CROP_AREA,
    RENDER_DPI,
    TWO_COLUMN_GUTTER_PX,
    TWO_COLUMN_MIN_BLOCKS_PER_COL,
)
from .models import BlockType, DocumentBlock

log = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_header_or_footer(bbox: tuple, page_height: float) -> bool:
    """Trả về True nếu block nằm trong vùng header hoặc footer."""
    y0, y1 = bbox[1], bbox[3]
    return y1 < HEADER_ZONE_PT or y0 > (page_height - FOOTER_ZONE_PT)


def _classify_text_block(text: str) -> BlockType:
    """
    Phân loại một block text thô thành TEXT hoặc MATH.

    Chiến lược:
    - Tính tỉ lệ ký tự Unicode toán học trên tổng ký tự.
    - Nếu vượt ngưỡng MATH_CHAR_RATIO_THRESHOLD → BlockType.MATH.
    - Kiểm tra thêm chuỗi LaTeX-like (\\frac, \\sum, ...).
    """
    if not text:
        return BlockType.UNKNOWN

    total_chars = len(text)
    math_chars  = sum(1 for c in text if c in MATH_UNICODE_CHARS)

    has_latex = "\\" in text and any(kw in text for kw in (
        "\\frac", "\\sum", "\\int", "\\prod", "\\alpha", "\\beta",
        "\\theta", "\\sigma", "\\mu", "\\lambda", "\\nabla", "\\partial",
    ))

    if has_latex or (total_chars > 0 and math_chars / total_chars > MATH_CHAR_RATIO_THRESHOLD):
        return BlockType.MATH

    return BlockType.TEXT


# ─── Layout classification ────────────────────────────────────────────────────

def classify_page_layout(page: fitz.Page) -> str:
    """
    Phân loại layout của trang: "1-column" hoặc "2-column".

    Thuật toán: đếm số block nằm thuần trong cột trái và cột phải.
    Nếu cả hai cột có >= TWO_COLUMN_MIN_BLOCKS_PER_COL block → 2 cột.
    """
    width  = page.rect.width
    x_mid  = width / 2.0
    blocks = [b for b in page.get_text("blocks") if b[4].strip()]

    left_count  = sum(1 for b in blocks if b[2] <= x_mid - TWO_COLUMN_GUTTER_PX)
    right_count = sum(1 for b in blocks if b[0] >= x_mid + TWO_COLUMN_GUTTER_PX)

    if (left_count  >= TWO_COLUMN_MIN_BLOCKS_PER_COL and
            right_count >= TWO_COLUMN_MIN_BLOCKS_PER_COL):
        return "2-column"
    return "1-column"


def classify_document_layout(doc: fitz.Document) -> str:
    """
    Phân loại layout cả tài liệu bằng cách vote trên 3 trang đầu.
    Trả về layout chiếm đa số.
    """
    sample = sorted({0, min(1, len(doc) - 1), min(2, len(doc) - 1)})
    votes  = [classify_page_layout(doc[i]) for i in sample]
    return "2-column" if votes.count("2-column") >= 2 else "1-column"


# ─── Reading Order sort ───────────────────────────────────────────────────────

def _sort_reading_order(
    raw_blocks: list[dict[str, Any]],
    layout: str,
    page_width: float,
) -> list[dict[str, Any]]:
    """
    Sắp xếp danh sách block thô theo thứ tự đọc tự nhiên.

    Layout 1 cột: sort (y0, x0) — từ trên xuống, trái sang phải.
    Layout 2 cột:
      - Tách thành cột trái / phải / full-width bằng x_mid.
      - Sort mỗi nhóm theo y0.
      - Full-width blocks xen vào đúng vị trí y0 trong dòng đọc.
    """
    if layout == "1-column":
        return sorted(raw_blocks, key=lambda b: (round(b["bbox"][1] / 5) * 5, b["bbox"][0]))

    # 2-column
    x_mid = page_width / 2.0
    gap   = TWO_COLUMN_GUTTER_PX

    left_col, right_col, full_width = [], [], []
    for b in raw_blocks:
        x0, y0, x1, y1 = b["bbox"]
        span_width = x1 - x0
        # Block trải dài > 70% chiều rộng trang → full-width (tiêu đề section, v.v.)
        if span_width > page_width * 0.7:
            full_width.append(b)
        elif x1 <= x_mid + gap:
            left_col.append(b)
        elif x0 >= x_mid - gap:
            right_col.append(b)
        else:
            full_width.append(b)

    left_col.sort(key=lambda b: b["bbox"][1])
    right_col.sort(key=lambda b: b["bbox"][1])
    full_width.sort(key=lambda b: b["bbox"][1])

    # Interleave full-width blocks vào đúng vị trí y0
    result: list[dict] = []
    l_idx = r_idx = f_idx = 0

    while l_idx < len(left_col) or r_idx < len(right_col) or f_idx < len(full_width):
        next_full_y = full_width[f_idx]["bbox"][1] if f_idx < len(full_width) else float("inf")
        next_left_y = left_col[l_idx]["bbox"][1]   if l_idx < len(left_col)   else float("inf")

        if next_full_y <= next_left_y:
            result.append(full_width[f_idx])
            f_idx += 1
        else:
            if l_idx < len(left_col):
                result.append(left_col[l_idx])
                l_idx += 1
            elif r_idx < len(right_col):
                result.append(right_col[r_idx])
                r_idx += 1
            elif f_idx < len(full_width):
                result.append(full_width[f_idx])
                f_idx += 1

    # Append phần right_col chưa xử lý
    result.extend(right_col[r_idx:])
    result.extend(full_width[f_idx:])

    return result


# ─── Block crop helper ────────────────────────────────────────────────────────

def _crop_block_to_png(page: fitz.Page, bbox: tuple, dpi: int = RENDER_DPI) -> bytes | None:
    """
    Crop vùng bbox trên trang và trả về bytes của ảnh PNG.

    Sử dụng clip rect của PyMuPDF để render chỉ phần cần thiết,
    tránh render toàn trang (tiết kiệm RAM).
    """
    try:
        rect  = fitz.Rect(bbox)
        scale = dpi / 72.0
        mat   = fitz.Matrix(scale, scale)
        pix   = page.get_pixmap(matrix=mat, clip=rect, colorspace=fitz.csRGB, alpha=False)

        if pix.width * pix.height < OCR_MIN_CROP_AREA:
            log.debug("Bỏ qua crop quá nhỏ: %dx%d px", pix.width, pix.height)
            return None

        buf = io.BytesIO()
        buf.write(pix.tobytes("png"))
        return buf.getvalue()

    except Exception as exc:
        log.warning("Không thể crop block %s: %s", bbox, exc)
        return None


# ─── Main segmentation function ───────────────────────────────────────────────

def segment_page(page: fitz.Page, page_num: int, layout: str) -> list[DocumentBlock]:
    """
    Phân đoạn một trang PDF thành danh sách DocumentBlock có thứ tự đọc chuẩn.

    Quy trình:
      1. Phát hiện tất cả bảng biểu (find_tables) → BlockType.TABLE
      2. Phát hiện tất cả block text → BlockType.TEXT hoặc MATH
      3. Phát hiện tất cả hình ảnh nhúng → BlockType.IMAGE
      4. Lọc bỏ header/footer
      5. Sắp xếp theo Reading Order
      6. Gán block_id bất biến
      7. Crop ảnh PNG cho IMAGE và MATH blocks
    """
    page_height = page.rect.height
    page_width  = page.rect.width
    raw_blocks: list[dict[str, Any]] = []

    # ── 1. Bảng biểu ──────────────────────────────────────────────────────────
    table_bboxes: list[fitz.Rect] = []
    try:
        tab_finder = page.find_tables()
        for table in getattr(tab_finder, "tables", []):
            try:
                data = table.extract()
            except Exception:
                continue
            if not data or not data[0]:
                continue

            table_bboxes.append(fitz.Rect(table.bbox))

            # Render bảng thành Markdown ngay tại đây (CPU, không cần GPU)
            header  = data[0]
            md_rows = ["| " + " | ".join(str(c or "").replace("|", "\\|").strip() for c in header) + " |"]
            md_rows.append("| " + " | ".join(["---"] * len(header)) + " |")
            for row in data[1:]:
                md_rows.append("| " + " | ".join(str(c or "").replace("|", "\\|").strip() for c in row) + " |")

            raw_blocks.append({
                "bbox":    tuple(table.bbox),
                "type":    BlockType.TABLE,
                "content": "\n".join(md_rows),
            })

    except Exception as exc:
        log.debug("find_tables() lỗi trang %d: %s", page_num, exc)

    # ── 2. Text blocks ────────────────────────────────────────────────────────
    for b in page.get_text("blocks"):
        # b = (x0, y0, x1, y1, text, block_no, block_type)
        # block_type: 0=text, 1=image
        if b[6] != 0:
            continue  # image block xử lý ở bước 3

        text = b[4].strip()
        if not text:
            continue

        bbox = b[:4]
        if _is_header_or_footer(bbox, page_height):
            continue

        # Bỏ qua block nằm trong vùng bảng
        block_rect = fitz.Rect(bbox)
        if any(block_rect.intersects(tb) for tb in table_bboxes):
            continue

        block_type = _classify_text_block(text)
        raw_blocks.append({
            "bbox":    bbox,
            "type":    block_type,
            "content": text,
        })

    # ── 3. Image blocks ───────────────────────────────────────────────────────
    for img_info in page.get_images(full=True):
        xref = img_info[0]
        try:
            img_rects = page.get_image_rects(xref)
        except Exception:
            continue

        for rect in img_rects:
            if rect.is_empty or rect.is_infinite:
                continue
            bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
            if _is_header_or_footer(bbox, page_height):
                continue

            raw_blocks.append({
                "bbox":    bbox,
                "type":    BlockType.IMAGE,
                "content": "",
            })

    # ── 4. Sắp xếp Reading Order ──────────────────────────────────────────────
    ordered = _sort_reading_order(raw_blocks, layout, page_width)

    # ── 5. Gán block_id & crop ảnh ────────────────────────────────────────────
    document_blocks: list[DocumentBlock] = []
    for idx, item in enumerate(ordered):
        btype    = item["type"]
        content  = item.get("content", "")
        crop_png = None

        if btype in (BlockType.IMAGE, BlockType.MATH):
            crop_png = _crop_block_to_png(page, item["bbox"])
            if crop_png is None:
                # Không crop được → fallback sang text
                btype   = BlockType.TEXT
                content = content or "[Image could not be extracted]"

        block = DocumentBlock(
            block_id    = idx,
            page_num    = page_num,
            bbox        = item["bbox"],
            block_type  = btype,
            raw_content = content,
            crop_bytes  = crop_png,
        )

        # CPU blocks (TEXT/TABLE) đã có kết quả ngay — set is_done
        if not block.needs_ocr:
            block.markdown_result = content
            block.is_done         = True

        document_blocks.append(block)

    log.debug(
        "Page %d: %d blocks (%d text, %d table, %d image, %d math)",
        page_num,
        len(document_blocks),
        sum(1 for b in document_blocks if b.block_type == BlockType.TEXT),
        sum(1 for b in document_blocks if b.block_type == BlockType.TABLE),
        sum(1 for b in document_blocks if b.block_type == BlockType.IMAGE),
        sum(1 for b in document_blocks if b.block_type == BlockType.MATH),
    )

    return document_blocks
