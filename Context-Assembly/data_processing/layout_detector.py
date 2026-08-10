"""
layout_detector.py — Phân loại layout trang và phân đoạn block.

Hybrid Markdown-LaTeX v3:
  1. Math Span Group Merging: gộp các span toán liền kề trên cùng 1 dòng thành 1 cặp $...$
     (sửa lỗi $p$$g$, $D$$($$x$$)$ kiểu cũ).
  2. Vertical Math Block Merging: gộp các block MATH đứng liên tiếp (gap < 14pt) thành
     1 block MATH lớn duy nhất → crop 1 lần → 1 lần OCR.
  3. Algorithm Detection: nhận diện block monospace font → BlockType.ALGORITHM.
  4. Figure vs Image: phân biệt đồ thị/biểu đồ (có caption bên dưới) vs ảnh thuần.
  5. Smart Table: đánh dấu bảng phức tạp (nhiều cột) để gửi OCR LaTeX tabular.
  6. Gutter Analysis: phát hiện 2-column bằng vertical whitespace mask.
  7. Font-based Heading Detection: H1/H2/H3 từ font size so với body size.
  8. Per-page layout: mỗi trang có gutter_x riêng.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any

import fitz  # PyMuPDF

from .config import (
    ALGORITHM_MONO_RATIO,
    FOOTER_ZONE_PT,
    FULL_WIDTH_RATIO,
    GUTTER_CENTER_ZONE,
    GUTTER_MIN_HEIGHT_RATIO,
    GUTTER_MIN_WIDTH_PT,
    HEADER_ZONE_PT,
    HEADING_FONT_RATIOS,
    HEADING_MAX_CHARS,
    HEADING_MIN_CHARS,
    MATH_BLOCK_MERGE_GAP_PT,
    MATH_BLOCK_RATIO,
    MATH_CHAR_RATIO_THRESHOLD,
    MATH_CROP_DPI,
    MATH_FONT_SUBSTRINGS,
    MATH_PUNCT_CHARS,
    MATH_UNICODE_CHARS,
    MONO_FONT_SUBSTRINGS,
    OCR_MIN_CROP_AREA,
    RENDER_DPI,
    TABLE_LATEX_MIN_COLS,
    TWO_COLUMN_GUTTER_PX,
    TWO_COLUMN_MIN_BLOCKS_PER_COL,
)
from .models import BlockType, DocumentBlock

log = logging.getLogger(__name__)

# Regex: nhận diện số thứ tự phương trình ở cuối dòng: "(1)", "(12)", "(A.3)"
_EQ_NUM_RE = re.compile(r"\(\s*[A-Za-z]?\d+(?:\.\d+)?\s*\)\s*$")

# Regex: caption hình ảnh/bảng điển hình (Figure 1:, Table 2., Hình 3:...)
_CAPTION_RE = re.compile(
    r"^(Figure|Fig\.|Table|Tbl\.|Hình|Bảng|Algorithm|Alg\.)\s*\d+",
    re.IGNORECASE,
)


# ─── Font helpers ─────────────────────────────────────────────────────────────

def _is_math_font(font_name: str) -> bool:
    """Kiểm tra tên font có phải là math font (LaTeX/TeX) không."""
    fn_upper = font_name.upper()
    return any(sub.upper() in fn_upper for sub in MATH_FONT_SUBSTRINGS)


def _is_mono_font(font_name: str) -> bool:
    """Kiểm tra tên font có phải là monospace (code/algorithm) không."""
    fn_upper = font_name.upper()
    return any(sub.upper() in fn_upper for sub in MONO_FONT_SUBSTRINGS)


def _span_is_math(span: dict) -> bool:
    """Trả về True nếu span này có khả năng cao là toán học."""
    font_name = span.get("font", "")
    if _is_math_font(font_name):
        return True
    text = span.get("text", "")
    if not text.strip():
        return False
    math_chars = sum(1 for c in text if c in MATH_UNICODE_CHARS)
    return math_chars / len(text) > MATH_CHAR_RATIO_THRESHOLD


# ─── Header/footer filter ─────────────────────────────────────────────────────

def _is_header_or_footer(bbox: tuple, page_height: float) -> bool:
    """Trả về True nếu block nằm trong vùng header hoặc footer."""
    y0, y1 = bbox[1], bbox[3]
    return y1 < HEADER_ZONE_PT or y0 > (page_height - FOOTER_ZONE_PT)


# ─── Font Hierarchy Analysis ──────────────────────────────────────────────────

def analyze_font_hierarchy(page: fitz.Page) -> dict:
    """
    Phân tích tất cả span trong trang để xác định body_size và ngưỡng heading.

    Returns: {"body_size": float, "thresholds": {1: float, 2: float, 3: float}}
    """
    size_char_count: dict[float, int] = {}
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    except Exception:
        return {"body_size": 10.0, "thresholds": {1: 16.0, 2: 13.5, 3: 11.5}}

    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = round(span.get("size", 0), 1)
                text = span.get("text", "")
                char_count = len(text.strip())
                if size > 0 and char_count > 0 and not _is_math_font(span.get("font", "")):
                    size_char_count[size] = size_char_count.get(size, 0) + char_count

    if not size_char_count:
        return {"body_size": 10.0, "thresholds": {1: 16.0, 2: 13.5, 3: 11.5}}

    body_size = max(size_char_count, key=lambda s: size_char_count[s])
    body_size = max(body_size, 6.0)

    thresholds = {
        level: round(body_size * ratio, 2)
        for level, ratio in HEADING_FONT_RATIOS.items()
    }
    log.debug(
        "Font hierarchy — body: %.1fpt | H1≥%.1f | H2≥%.1f | H3≥%.1f",
        body_size, thresholds.get(1, 0), thresholds.get(2, 0), thresholds.get(3, 0),
    )
    return {"body_size": body_size, "thresholds": thresholds}


def _detect_heading_level(block_dict: dict, font_hierarchy: dict) -> int | None:
    """Xác định heading level (1/2/3) hoặc None cho một text block."""
    thresholds = font_hierarchy.get("thresholds", {})
    body_size  = font_hierarchy.get("body_size", 10.0)
    lines      = block_dict.get("lines", [])
    if not lines or len(lines) > 3:
        return None

    all_text = ""
    max_size = 0.0
    is_bold  = False
    for line in lines:
        for span in line.get("spans", []):
            font_name = span.get("font", "")
            if _is_math_font(font_name) or _is_mono_font(font_name):
                continue
            all_text += span.get("text", "")
            sz = span.get("size", 0.0)
            if sz > max_size:
                max_size = sz
            flags = span.get("flags", 0)
            if (flags & 16) or "Bold" in font_name or "bold" in font_name:
                is_bold = True

    text_stripped = all_text.strip()
    n_chars = len(text_stripped)
    if n_chars < HEADING_MIN_CHARS or n_chars > HEADING_MAX_CHARS:
        return None
    if text_stripped.isdigit():
        return None

    for level in sorted(thresholds.keys()):
        if max_size >= thresholds[level]:
            return level

    if is_bold and max_size >= body_size and n_chars <= 100:
        return 3
    return None


# ─── Gutter Analysis ──────────────────────────────────────────────────────────

def _find_column_gutter(
    text_bboxes: list[tuple],
    page_width: float,
    page_height: float,
) -> float | None:
    if not text_bboxes or page_width <= 0 or page_height <= 0:
        return None

    resolution = 2.0
    n_slots = int(page_width / resolution) + 1
    y_coverage = [0.0] * n_slots

    for x0, y0, x1, y1 in text_bboxes:
        slot0 = max(0, int(x0 / resolution))
        slot1 = min(n_slots - 1, int(x1 / resolution))
        block_height = max(0.0, y1 - y0)
        for s in range(slot0, slot1 + 1):
            y_coverage[s] += block_height

    min_coverage_threshold = page_height * GUTTER_MIN_HEIGHT_RATIO
    center_lo = page_width * GUTTER_CENTER_ZONE[0]
    center_hi = page_width * GUTTER_CENTER_ZONE[1]

    gutter_start = None
    best_gutter_x = None
    best_gutter_width = 0.0

    for s in range(n_slots):
        x = s * resolution
        is_empty = y_coverage[s] < min_coverage_threshold

        if is_empty and center_lo <= x <= center_hi:
            if gutter_start is None:
                gutter_start = x
        else:
            if gutter_start is not None:
                gutter_width = x - gutter_start
                if gutter_width >= GUTTER_MIN_WIDTH_PT and gutter_width > best_gutter_width:
                    best_gutter_width = gutter_width
                    best_gutter_x = gutter_start + gutter_width / 2.0
                gutter_start = None

    if gutter_start is not None:
        gutter_width = page_width * GUTTER_CENTER_ZONE[1] - gutter_start
        if gutter_width >= GUTTER_MIN_WIDTH_PT and gutter_width > best_gutter_width:
            best_gutter_x = gutter_start + gutter_width / 2.0

    return best_gutter_x


def classify_page_layout(page: fitz.Page) -> tuple[str, float | None]:
    """Phân loại layout: "1-column" hoặc "2-column" với gutter_x."""
    page_width  = page.rect.width
    page_height = page.rect.height

    raw_blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not raw_blocks:
        return "1-column", None

    body_bboxes = [
        (b[0], b[1], b[2], b[3]) for b in raw_blocks
        if not _is_header_or_footer((b[0], b[1], b[2], b[3]), page_height)
    ]

    gutter_x = _find_column_gutter(body_bboxes, page_width, page_height)
    if gutter_x is not None:
        log.debug("Gutter detected at x=%.1f (page_width=%.1f)", gutter_x, page_width)
        return "2-column", gutter_x

    x_mid = page_width / 2.0
    gap   = TWO_COLUMN_GUTTER_PX
    left_count  = sum(1 for b in body_bboxes if b[2] <= x_mid - gap)
    right_count = sum(1 for b in body_bboxes if b[0] >= x_mid + gap)
    if left_count >= TWO_COLUMN_MIN_BLOCKS_PER_COL and right_count >= TWO_COLUMN_MIN_BLOCKS_PER_COL:
        return "2-column", x_mid

    return "1-column", None


def classify_document_layout(doc: fitz.Document) -> str:
    """Vote layout toàn tài liệu từ các trang sample."""
    n = len(doc)
    sample_pages = sorted({min(1,n-1), min(2,n-1), min(3,n-1), min(4,n-1)})
    votes = [classify_page_layout(doc[i])[0] for i in sample_pages]
    result = "2-column" if votes.count("2-column") > len(votes) / 2 else "1-column"
    log.debug("Document layout vote: %s → %s", votes, result)
    return result


# ─── Reading Order ────────────────────────────────────────────────────────────

def _sort_reading_order(
    raw_blocks: list[dict[str, Any]],
    layout: str,
    page_width: float,
    gutter_x: float | None = None,
) -> list[dict[str, Any]]:
    """Sắp xếp block theo thứ tự đọc: 1-col theo y0; 2-col theo left→right→full-width."""
    if layout == "1-column" or not raw_blocks:
        return sorted(raw_blocks, key=lambda b: (round(b["bbox"][1] / 5) * 5, b["bbox"][0]))

    x_split = gutter_x if gutter_x is not None else page_width / 2.0
    gap = TWO_COLUMN_GUTTER_PX

    left_col, right_col, full_width = [], [], []
    for b in raw_blocks:
        x0, y0, x1, y1 = b["bbox"]
        span_width = x1 - x0
        if span_width > page_width * FULL_WIDTH_RATIO:
            full_width.append(b)
        elif x1 <= x_split + gap:
            left_col.append(b)
        elif x0 >= x_split - gap:
            right_col.append(b)
        else:
            full_width.append(b)

    left_col.sort(key=lambda b: b["bbox"][1])
    right_col.sort(key=lambda b: b["bbox"][1])
    full_width.sort(key=lambda b: b["bbox"][1])

    result: list[dict] = []
    l_idx = r_idx = f_idx = 0

    while l_idx < len(left_col) or r_idx < len(right_col) or f_idx < len(full_width):
        next_full_y = full_width[f_idx]["bbox"][1] if f_idx < len(full_width) else float("inf")
        next_left_y = left_col[l_idx]["bbox"][1]   if l_idx < len(left_col)   else float("inf")

        if next_full_y <= next_left_y and f_idx < len(full_width):
            result.append(full_width[f_idx]); f_idx += 1
        elif l_idx < len(left_col):
            result.append(left_col[l_idx]); l_idx += 1
        elif r_idx < len(right_col):
            result.append(right_col[r_idx]); r_idx += 1
        elif f_idx < len(full_width):
            result.append(full_width[f_idx]); f_idx += 1
        else:
            break

    result.extend(right_col[r_idx:])
    result.extend(full_width[f_idx:])
    return result


# ─── Crop helper ──────────────────────────────────────────────────────────────

def _crop_block_to_png(
    page: fitz.Page,
    bbox: tuple,
    dpi: int = RENDER_DPI,
    high_dpi: bool = False,
) -> bytes | None:
    """Crop vùng bbox trên trang, trả về PNG bytes. high_dpi=True dùng MATH_CROP_DPI."""
    try:
        render_dpi = MATH_CROP_DPI if high_dpi else dpi
        rect  = fitz.Rect(bbox)
        scale = render_dpi / 72.0
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


# ─── Math Span Group Merging ──────────────────────────────────────────────────

def _merge_math_spans_in_line(spans: list[dict]) -> str:
    """
    Gộp các span toán liền kề trong 1 dòng thành 1 nhóm $...$, tránh $p$$g$.

    Thuật toán:
      - Quét từ trái sang phải qua danh sách spans.
      - Khi gặp span math, mở nhóm math và thu thập text vào buffer.
      - Span tiếp theo được tiếp tục vào nhóm nếu:
        * Cũng là math span, HOẶC
        * Là text ngắn (≤ 3 ký tự) và chỉ gồm MATH_PUNCT_CHARS (dấu câu toán học
          như (), [], {}, +, -, =...) — tức là dấu câu text nằm giữa 2 biểu thức math.
      - Khi gặp span text dài hoặc text chữ thường, đóng nhóm math → emit $buffer$.
      - Trả về chuỗi text đã xử lý của toàn bộ dòng.

    Ví dụ PDF spans: ["p"(CMMI), "g"(CMMI7), "("(CMR), "x"(CMMI), ")"(CMR)]
    Kết quả cũ:      "$p$$g$$($x$)$"   ← sai
    Kết quả mới:     "$p_g(x)$"         ← đúng (gộp liên tục, dấu () pass-through)
    """
    parts: list[str] = []
    math_buffer: list[str] = []
    in_math_group = False

    def flush_math():
        nonlocal in_math_group
        if math_buffer:
            merged = "".join(math_buffer).strip()
            if merged:
                parts.append(f"${merged}$")
            math_buffer.clear()
        in_math_group = False

    i = 0
    while i < len(spans):
        span      = spans[i]
        raw_text  = span.get("text", "")
        is_math   = _span_is_math(span)
        is_mono   = _is_mono_font(span.get("font", ""))

        # Monospace: kết thúc nhóm math nếu đang mở, rồi emit trực tiếp
        if is_mono:
            flush_math()
            parts.append(raw_text)
            i += 1
            continue

        if is_math:
            in_math_group = True
            math_buffer.append(raw_text)
        else:
            # Span text thường — kiểm tra có phải "dấu câu pass-through" không
            stripped = raw_text.strip()

            # Pass-through: text rất ngắn và chỉ là dấu câu toán
            is_punct_passthrough = (
                in_math_group
                and len(stripped) <= 3
                and all(c in MATH_PUNCT_CHARS for c in stripped)
            )

            # Xem span tiếp theo có phải math không (lookahead)
            next_is_math = (
                i + 1 < len(spans)
                and _span_is_math(spans[i + 1])
            )

            # Dấu đóng ngoặc/ký hiệu kết thúc biểu thức luôn được kéo vào nhóm math
            # bất kể span tiếp theo là gì (chúng là phần kết thúc của biểu thức toán)
            _CLOSING_PUNCTS = frozenset(")]}>")
            is_closing_punct_only = (
                in_math_group
                and bool(stripped)
                and len(stripped) <= 3
                and all(c in _CLOSING_PUNCTS for c in stripped)
            )

            if is_closing_punct_only:
                # Dấu đóng ngoặc cuối biểu thức toán: luôn gộp vào nhóm
                math_buffer.append(raw_text)
            elif is_punct_passthrough and next_is_math:
                # Dấu câu pass-through giữa 2 math span: gộp vào buffer
                math_buffer.append(raw_text)
            else:
                # Text thường thực sự: đóng nhóm math trước, rồi emit text
                flush_math()
                parts.append(raw_text)

        i += 1

    flush_math()
    return "".join(parts)


# ─── Block Analysis ───────────────────────────────────────────────────────────

def _analyze_block_from_dict(
    block_dict: dict,
    font_hierarchy: dict,
    page_width: float,
) -> dict[str, Any]:
    """
    Phân tích 1 block từ get_text("dict") → trả về dict với:
      - content: text đã xử lý (math spans gộp thành $...$)
      - type: BlockType (TEXT / MATH / ALGORITHM)
      - heading_level, font_size, has_inline_math, ocr_mode

    Chiến lược phân loại:
      - ALGORITHM: >60% span dùng monospace font
      - MATH:      >75% span dùng math font (sau khi loại monospace)
      - TEXT:      còn lại (kể cả có inline math spans)
    """
    lines_data = block_dict.get("lines", [])
    if not lines_data:
        return {}

    all_line_texts: list[str] = []
    math_span_count = 0
    mono_span_count = 0
    total_span_count = 0
    max_font_size = 0.0
    has_inline_math = False

    # ── Pass 1: Thống kê font và tạo text thuần (cho fallback) ─────────────────
    for line in lines_data:
        spans = line.get("spans", [])
        for span in spans:
            total_span_count += 1
            sz = span.get("size", 0.0)
            if sz > max_font_size:
                max_font_size = sz
            font = span.get("font", "")
            if _is_mono_font(font):
                mono_span_count += 1
            elif _span_is_math(span):
                math_span_count += 1

    # ── Phân loại sơ bộ ────────────────────────────────────────────────────────
    if total_span_count == 0:
        return {}

    mono_ratio = mono_span_count / total_span_count
    math_ratio = (math_span_count) / total_span_count  # chỉ tính non-mono

    if mono_ratio >= ALGORITHM_MONO_RATIO:
        block_type = BlockType.ALGORITHM
    elif math_ratio >= MATH_BLOCK_RATIO:
        block_type = BlockType.MATH
    else:
        block_type = BlockType.TEXT

    # ── Pass 2: Tạo content theo block_type ────────────────────────────────────
    if block_type == BlockType.MATH:
        # MATH block → trích text thô (không bọc $) để gửi VLM
        raw_lines = []
        for line in lines_data:
            line_txt = " ".join(sp.get("text", "") for sp in line.get("spans", []))
            if line_txt.strip():
                raw_lines.append(line_txt.strip())
        content = "\n".join(raw_lines)
        ocr_mode = "math"

    elif block_type == BlockType.ALGORITHM:
        # ALGORITHM block → trích text thô để gửi VLM → fenced code
        raw_lines = []
        for line in lines_data:
            line_txt = "".join(sp.get("text", "") for sp in line.get("spans", []))
            if line_txt.strip():
                raw_lines.append(line_txt)
        content = "\n".join(raw_lines)
        ocr_mode = "algorithm"

    else:
        # TEXT block → áp dụng Math Span Group Merging trên từng dòng
        for line in lines_data:
            spans = line.get("spans", [])
            merged_line = _merge_math_spans_in_line(spans).strip()
            if merged_line:
                all_line_texts.append(merged_line)
                if "$" in merged_line:
                    has_inline_math = True
        content = "\n".join(all_line_texts)
        ocr_mode = "text"

    heading_level = _detect_heading_level(block_dict, font_hierarchy)
    bbox = block_dict.get("bbox", (0, 0, 0, 0))

    return {
        "bbox":            tuple(bbox),
        "type":            block_type,
        "content":         content,
        "heading_level":   heading_level,
        "font_size":       max_font_size if max_font_size > 0 else None,
        "has_inline_math": has_inline_math,
        "ocr_mode":        ocr_mode,
    }


# ─── Vertical Math Block Merging ──────────────────────────────────────────────

def _merge_consecutive_math_blocks(raw_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Gộp các block MATH đứng liên tiếp theo chiều dọc thành 1 block MATH lớn.

    Tiêu chí gộp:
      - Cả 2 block đều là BlockType.MATH.
      - Khoảng cách dọc (y0_next - y1_prev) < MATH_BLOCK_MERGE_GAP_PT (14pt).
      - Cùng nằm trong một cột (x overlap đáng kể).

    Kết quả: 1 block MATH với bbox hợp nhất (union), content là raw text của tất cả
    lines được gộp. Crop ảnh sẽ bao phủ toàn bộ vùng công thức → OCR 1 lần.

    Tại sao cần: PyMuPDF chia mỗi dòng/phần của công thức thành dict-block riêng.
    Không gộp → trang có 25 MATH blocks → 25 lần crop nhỏ → OCR 25 lần → 25 tag rời rạc.
    Sau gộp → 2-3 MATH blocks lớn (mỗi khối công thức) → OCR 2-3 lần → đầu ra chuẩn.
    """
    if not raw_blocks:
        return []

    result: list[dict] = []
    i = 0

    while i < len(raw_blocks):
        block = raw_blocks[i]

        if block.get("type") != BlockType.MATH:
            result.append(block)
            i += 1
            continue

        # Bắt đầu nhóm MATH: thu thập các block MATH liên tiếp
        group_blocks = [block]
        j = i + 1

        while j < len(raw_blocks):
            next_block = raw_blocks[j]

            if next_block.get("type") != BlockType.MATH:
                break

            # Kiểm tra khoảng cách dọc
            prev_y1 = group_blocks[-1]["bbox"][3]
            next_y0 = next_block["bbox"][1]
            gap = next_y0 - prev_y1

            if gap > MATH_BLOCK_MERGE_GAP_PT:
                break

            # Kiểm tra overlap ngang (cùng cột)
            prev_x0 = group_blocks[-1]["bbox"][0]
            prev_x1 = group_blocks[-1]["bbox"][2]
            next_x0 = next_block["bbox"][0]
            next_x1 = next_block["bbox"][2]
            overlap = min(prev_x1, next_x1) - max(prev_x0, next_x0)
            width   = min(prev_x1 - prev_x0, next_x1 - next_x0)

            # Chỉ gộp nếu x overlap đủ lớn (> 20% chiều rộng nhỏ hơn)
            if width > 0 and overlap / width < 0.2:
                break

            group_blocks.append(next_block)
            j += 1

        if len(group_blocks) == 1:
            result.append(block)
            i += 1
            continue

        # Gộp group thành 1 block
        merged_x0 = min(b["bbox"][0] for b in group_blocks)
        merged_y0 = min(b["bbox"][1] for b in group_blocks)
        merged_x1 = max(b["bbox"][2] for b in group_blocks)
        merged_y1 = max(b["bbox"][3] for b in group_blocks)

        merged_content = "\n".join(b.get("content", "") for b in group_blocks if b.get("content"))

        merged_block = {
            "bbox":            (merged_x0, merged_y0, merged_x1, merged_y1),
            "type":            BlockType.MATH,
            "content":         merged_content,
            "heading_level":   None,
            "font_size":       group_blocks[0].get("font_size"),
            "has_inline_math": False,
            "ocr_mode":        "math",
        }

        log.debug(
            "Gộp %d MATH blocks → 1 (y: %.1f→%.1f, gap trung bình: %.1f pt)",
            len(group_blocks), merged_y0, merged_y1,
            (merged_y1 - merged_y0) / len(group_blocks),
        )
        result.append(merged_block)
        i = j

    return result


# ─── Figure vs Image classification ──────────────────────────────────────────

def _classify_image_blocks(
    image_blocks: list[dict],
    text_blocks: list[dict],
) -> list[dict]:
    """
    Phân biệt IMAGE thuần (ảnh chụp, logo) vs FIGURE (đồ thị, diagram có caption).

    Heuristic:
      - Tìm text block ngay bên dưới image block (trong vòng 30pt).
      - Nếu text bắt đầu bằng "Figure", "Fig.", "Table", "Hình"... → FIGURE.
      - Ngược lại → IMAGE.

    Gán thêm caption text nếu tìm thấy.
    """
    result = []
    for img in image_blocks:
        img_y1 = img["bbox"][3]
        img_x0 = img["bbox"][0]
        img_x1 = img["bbox"][2]
        caption_text = ""
        ocr_mode     = "image"

        # Tìm text block bên dưới trong vòng 30pt và overlap ngang > 30%
        for txt in text_blocks:
            txt_y0 = txt["bbox"][1]
            txt_x0 = txt["bbox"][0]
            txt_x1 = txt["bbox"][2]
            gap    = txt_y0 - img_y1

            if 0 <= gap <= 30:
                # Kiểm tra overlap ngang
                overlap = min(img_x1, txt_x1) - max(img_x0, txt_x0)
                img_width = img_x1 - img_x0
                if img_width > 0 and overlap / img_width > 0.3:
                    caption_cand = txt.get("content", "").strip()
                    if _CAPTION_RE.match(caption_cand):
                        caption_text = caption_cand
                        ocr_mode     = "figure"
                        break

        new_img = dict(img)
        new_img["caption"]  = caption_text
        new_img["ocr_mode"] = ocr_mode
        new_img["type"]     = BlockType.FIGURE if ocr_mode == "figure" else BlockType.IMAGE
        result.append(new_img)

    return result


# ─── Smart Table classification ───────────────────────────────────────────────

def _classify_table(table_data: list[list], md_content: str) -> tuple[str, str]:
    """
    Trả về (block_type_hint, ocr_mode) cho bảng.

    Nếu bảng có nhiều cột (≥ TABLE_LATEX_MIN_COLS) hoặc có merged cells:
      → ocr_mode = "table_complex" (gửi VLM → LaTeX tabular)
    Ngược lại:
      → ocr_mode = "table_simple" (dùng Markdown table)
    """
    if not table_data or not table_data[0]:
        return "table", "table_simple"

    n_cols = len(table_data[0])
    if n_cols >= TABLE_LATEX_MIN_COLS:
        return "table", "table_complex"

    # Kiểm tra merged cells: None cell ở giữa bảng → có merged cells
    has_merged = any(
        cell is None
        for row in table_data[1:]
        for cell in row
    )
    if has_merged:
        return "table", "table_complex"

    return "table", "table_simple"


# ─── Main segmentation ────────────────────────────────────────────────────────

def segment_page(
    page: fitz.Page,
    page_num: int,
    layout: str,
    gutter_x: float | None = None,
) -> list[DocumentBlock]:
    """
    Phân đoạn 1 trang PDF → danh sách DocumentBlock theo Reading Order.

    Quy trình mới (Hybrid Markdown-LaTeX v3):
      1. Font hierarchy analysis.
      2. Table detection (find_tables) + smart classification.
      3. Text/Math/Algorithm block detection từ get_text("dict").
         3a. Math Span Group Merging trong từng dòng.
         3b. Block type classification (MATH/ALGORITHM/TEXT).
      4. Image detection + Figure vs Image classification.
      5. Filter header/footer.
      6. Sort Reading Order.
      7. Vertical Math Block Merging (gộp MATH blocks liên tiếp).
      8. Assign block_id + crop PNG.
    """
    page_height = page.rect.height
    page_width  = page.rect.width
    raw_blocks: list[dict[str, Any]] = []

    # ── 1. Font Hierarchy ──────────────────────────────────────────────────────
    font_hierarchy = analyze_font_hierarchy(page)

    # ── 2. Bảng biểu ──────────────────────────────────────────────────────────
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
            header  = data[0]
            n_cols  = len(header)

            # Tạo Markdown table (fallback / simple case)
            md_rows = [
                "| " + " | ".join(
                    str(c or "").replace("|", "\\|").strip() for c in header
                ) + " |",
                "| " + " | ".join(["---"] * n_cols) + " |",
            ]
            for row in data[1:]:
                md_rows.append(
                    "| " + " | ".join(
                        str(c or "").replace("|", "\\|").strip() for c in row
                    ) + " |"
                )
            md_content = "\n".join(md_rows)

            _, ocr_mode = _classify_table(data, md_content)

            raw_blocks.append({
                "bbox":           tuple(table.bbox),
                "type":           BlockType.TABLE,
                "content":        md_content,
                "heading_level":  None,
                "font_size":      None,
                "has_inline_math": False,
                "ocr_mode":       ocr_mode,
                "caption":        "",
            })
    except Exception as exc:
        log.debug("find_tables() lỗi trang %d: %s", page_num, exc)

    # ── 3. Text / Math / Algorithm blocks ─────────────────────────────────────
    image_blocks_raw: list[dict] = []
    try:
        dict_result = page.get_text(
            "dict",
            flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES,
        )
    except Exception:
        dict_result = {"blocks": []}

    text_blocks_for_caption: list[dict] = []  # dùng để detect figure caption

    for block_dict in dict_result.get("blocks", []):
        if block_dict.get("type") != 0:
            continue

        bbox = block_dict.get("bbox", (0, 0, 0, 0))
        if _is_header_or_footer(bbox, page_height):
            continue

        block_rect = fitz.Rect(bbox)
        if any(block_rect.intersects(tb) for tb in table_bboxes):
            continue

        analyzed = _analyze_block_from_dict(block_dict, font_hierarchy, page_width)
        if not analyzed or not analyzed.get("content", "").strip():
            continue

        analyzed.setdefault("caption", "")
        raw_blocks.append(analyzed)
        text_blocks_for_caption.append(analyzed)

    # ── 4. Image blocks ────────────────────────────────────────────────────────
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
            image_blocks_raw.append({
                "bbox":           bbox,
                "type":           BlockType.IMAGE,
                "content":        "",
                "heading_level":  None,
                "font_size":      None,
                "has_inline_math": False,
                "ocr_mode":       "image",
                "caption":        "",
            })

    # Classify image → FIGURE vs IMAGE
    classified_images = _classify_image_blocks(image_blocks_raw, text_blocks_for_caption)
    raw_blocks.extend(classified_images)

    # ── 5. Sort Reading Order ──────────────────────────────────────────────────
    ordered = _sort_reading_order(raw_blocks, layout, page_width, gutter_x)

    # ── 6. Vertical Math Block Merging ─────────────────────────────────────────
    ordered = _merge_consecutive_math_blocks(ordered)

    # ── 7. Assign block_id + crop ─────────────────────────────────────────────
    document_blocks: list[DocumentBlock] = []
    for idx, item in enumerate(ordered):
        btype    = item["type"]
        content  = item.get("content", "")
        ocr_mode = item.get("ocr_mode", "text")
        caption  = item.get("caption", "")
        crop_png = None

        needs_crop = btype in (BlockType.IMAGE, BlockType.FIGURE, BlockType.MATH, BlockType.ALGORITHM)
        if needs_crop:
            high_dpi = (btype == BlockType.MATH)
            crop_png = _crop_block_to_png(page, item["bbox"], high_dpi=high_dpi)
            if crop_png is None and btype in (BlockType.IMAGE, BlockType.FIGURE):
                btype   = BlockType.TEXT
                content = caption or "[Image could not be extracted]"

        block = DocumentBlock(
            block_id        = idx,
            page_num        = page_num,
            bbox            = item["bbox"],
            block_type      = btype,
            raw_content     = content,
            crop_bytes      = crop_png,
            heading_level   = item.get("heading_level"),
            font_size       = item.get("font_size"),
            has_inline_math = item.get("has_inline_math", False),
            ocr_mode        = ocr_mode,
            caption         = caption,
        )

        # CPU blocks (TEXT/TABLE simple): set is_done ngay
        if not block.needs_ocr:
            block.markdown_result = content
            block.is_done         = True

        document_blocks.append(block)

    # Thống kê
    log.debug(
        "Page %d: %d blocks (text=%d table=%d image=%d figure=%d math=%d algo=%d) [%s]",
        page_num, len(document_blocks),
        sum(1 for b in document_blocks if b.block_type == BlockType.TEXT),
        sum(1 for b in document_blocks if b.block_type == BlockType.TABLE),
        sum(1 for b in document_blocks if b.block_type == BlockType.IMAGE),
        sum(1 for b in document_blocks if b.block_type == BlockType.FIGURE),
        sum(1 for b in document_blocks if b.block_type == BlockType.MATH),
        sum(1 for b in document_blocks if b.block_type == BlockType.ALGORITHM),
        layout,
    )

    return document_blocks
