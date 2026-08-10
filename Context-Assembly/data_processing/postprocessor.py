"""
postprocessor.py — Hậu xử lý văn bản sau khi đã thu thập từ tất cả blocks.

Cải tiến so với phiên bản cũ:
  - build_section_map(): fallback sang font-based heading detection khi TOC trống.
  - Thêm merge_split_paragraphs(): ghép đoạn văn bị cắt do column break.
  - Bảo vệ inline math ($...$) khi áp dụng hyphenation repair.

Các bước xử lý:
  1. Sửa lỗi gạch nối cuối dòng (hyphenation repair), bảo vệ math.
  2. Chuẩn hóa khoảng trắng và newlines.
  3. Lọc header/footer lặp lại.
  4. Phát hiện và đánh dấu phần References.
  5. Gắn section path từ TOC hoặc font-based detection.
"""

from __future__ import annotations

import re
import logging
from collections import Counter
from pathlib import Path

import fitz

from .config import REFERENCES_LOOKBACK_PAGES

log = logging.getLogger(__name__)


# ─── Hyphenation repair (math-aware) ─────────────────────────────────────────

_HYPHEN_EOL   = re.compile(r"(\w{3,})-\s*\n\s*([a-z])")
_SOFT_WRAP    = re.compile(r"([a-z,;:])[ \t]*\n[ \t]*([a-z])")
_MULTI_NL     = re.compile(r"\n{3,}")
_TRAIL_WS     = re.compile(r"[ \t]+$", re.MULTILINE)
_INLINE_MATH  = re.compile(r"\$[^$\n]+\$|\$\$[\s\S]+?\$\$")


def _protect_math(text: str) -> tuple[str, list[str]]:
    """
    Thay thế tất cả vùng math ($...$ và $$...$$) bằng placeholder để bảo vệ
    khỏi các phép biến đổi text (hyphenation, soft-wrap...).

    Trả về (text_with_placeholders, [math_regions]).
    """
    placeholders: list[str] = []
    def replacer(m: re.Match) -> str:
        idx = len(placeholders)
        placeholders.append(m.group(0))
        return f"\x00MATH{idx}\x00"
    protected = _INLINE_MATH.sub(replacer, text)
    return protected, placeholders


def _restore_math(text: str, placeholders: list[str]) -> str:
    """Khôi phục các vùng math từ placeholder."""
    for i, math in enumerate(placeholders):
        text = text.replace(f"\x00MATH{i}\x00", math)
    return text


def repair_hyphenation(text: str) -> str:
    """
    Sửa lỗi từ bị ngắt dòng bằng gạch nối (hyphenation artifact từ PDF).
    Bảo vệ inline math ($...$) khỏi bị sửa sai.

    Ví dụ:
        "auto-regres-\\nsive" → "autoregressive"
        "represen-\\ntation" → "representation"
    """
    protected, placeholders = _protect_math(text)
    protected = _HYPHEN_EOL.sub(r"\1\2", protected)
    protected = _SOFT_WRAP.sub(r"\1 \2", protected)
    return _restore_math(protected, placeholders)


def normalize_whitespace(text: str) -> str:
    """Chuẩn hóa khoảng trắng thừa."""
    text = _TRAIL_WS.sub("", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# ─── Merge split paragraphs (column-break artifact) ──────────────────────────

def merge_split_paragraphs(text: str) -> str:
    """
    Ghép các đoạn văn bị cắt đứng do column break trong PDF 2 cột.

    Dấu hiệu đoạn bị cắt:
      - Dòng kết thúc KHÔNG phải dấu câu kết thúc (., ?, !, :)
      - Dòng tiếp theo bắt đầu bằng chữ thường (tiếp tục câu)

    Không áp dụng cho:
      - Heading (dòng bắt đầu bằng #)
      - Bullet/numbered list
      - Math blocks
    """
    lines = text.splitlines()
    result: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # Không merge heading, list, math display
        if (line.startswith("#") or
                line.startswith("- ") or
                line.startswith("* ") or
                re.match(r"^\d+\.", line) or
                line.startswith("$$") or
                line.startswith("|")):
            result.append(line)
            i += 1
            continue

        # Kiểm tra có thể merge với dòng tiếp theo không
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            current_stripped = line.rstrip()

            can_merge = (
                current_stripped
                and not current_stripped[-1] in ".?!:"
                and not current_stripped.endswith("$$")
                and next_line
                and next_line[0].islower()
                and not next_line.startswith("#")
                and not next_line.startswith("- ")
                and not next_line.startswith("$$")
                and not next_line.startswith("|")
            )

            if can_merge:
                result.append(current_stripped + " " + next_line.lstrip())
                i += 2
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


# ─── Repeated header/footer detection ────────────────────────────────────────

def find_repeated_strings(pages_text: list[str], min_pages: int = 4) -> set[str]:
    """
    Tìm các chuỗi xuất hiện lặp lại ở đầu/cuối nhiều trang → header/footer.
    """
    counter: Counter[str] = Counter()
    for text in pages_text:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        candidates = lines[:2] + lines[-2:]
        for c in candidates:
            if 3 < len(c) <= 80 and len(c.split()) <= 10:
                counter[c] += 1
    return {t for t, cnt in counter.items() if cnt >= min_pages}


def filter_repeated_strings(text: str, repeated: set[str]) -> str:
    """Lọc bỏ các dòng header/footer lặp lại khỏi text."""
    if not repeated:
        return text
    lines = text.splitlines()
    kept  = [l for l in lines if l.strip() not in repeated]
    return "\n".join(kept)


# ─── References detection ─────────────────────────────────────────────────────

_REFERENCE_PATTERNS = [
    re.compile(r"^#+\s*(References|REFERENCES)\s*$", re.MULTILINE),
    re.compile(r"^\s*(References|REFERENCES)\s*$", re.MULTILINE),
    re.compile(r"^\s*(Bibliography|BIBLIOGRAPHY)\s*$", re.MULTILINE),
    re.compile(r"^\s*TÀI LIỆU THAM KHẢO\s*$", re.MULTILINE),
    re.compile(r"^\s*References and Further Reading\s*$", re.MULTILINE | re.IGNORECASE),
]


def find_references_page(pages_text: list[str]) -> int | None:
    """
    Tìm trang bắt đầu phần References (duyệt từ cuối ngược lên).
    Trả về page_num (1-indexed) hoặc None nếu không tìm thấy.
    """
    for i in range(len(pages_text) - 1, -1, -1):
        for pattern in _REFERENCE_PATTERNS:
            if pattern.search(pages_text[i]):
                return i + 1  # 1-indexed
    return None


# ─── TOC / Font-based section map ────────────────────────────────────────────

def build_section_map(doc: fitz.Document) -> dict[int, str]:
    """
    Xây dựng mapping page_num → section_path từ TOC (Table of Contents).

    Fallback: nếu TOC rỗng, quét heading được detect bởi layout_detector
    trong markdown output (dòng bắt đầu bằng #, ##, ###).

    Ví dụ: {3: "Introduction", 5: "Methods > Dataset", 8: "Methods > Training"}
    """
    toc = doc.get_toc()
    section_map: dict[int, str] = {}

    if toc:
        # === Dùng TOC có sẵn ===
        stack: list[tuple[int, str]] = []
        for level, title, page in toc:
            stack = [(l, t) for l, t in stack if l < level]
            stack.append((level, title))
            section_map[page] = " > ".join(t for _, t in stack)
    else:
        # === Fallback: font-based heading detection từ PyMuPDF ===
        log.debug("TOC rỗng — dùng font-based heading detection để build section_map.")
        section_map = _build_section_map_from_fonts(doc)

    # Điền forward cho các trang không có TOC entry
    current = ""
    result: dict[int, str] = {}
    for pg in range(1, len(doc) + 1):
        if pg in section_map:
            current = section_map[pg]
        result[pg] = current

    return result


def _build_section_map_from_fonts(doc: fitz.Document) -> dict[int, str]:
    """
    Khi PDF không có TOC bookmark, reconstruct section hierarchy bằng font analysis.

    Thuật toán:
      1. Thu thập tất cả font sizes trong document.
      2. Cluster để tìm body_size (mode).
      3. Trên mỗi trang: tìm các span có font_size > body_size * 1.15 ở đầu trang.
      4. Map chúng thành H1/H2/H3 sections.
    """
    # Bước 1: Xác định body_size cho toàn document
    size_char_count: dict[float, int] = {}
    sample_pages = list(range(min(10, len(doc))))

    for page_idx in sample_pages:
        try:
            page = doc[page_idx]
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = round(span.get("size", 0), 1)
                        text = span.get("text", "").strip()
                        if size > 0 and text:
                            size_char_count[size] = size_char_count.get(size, 0) + len(text)
        except Exception:
            continue

    if not size_char_count:
        return {}

    body_size = max(size_char_count, key=lambda s: size_char_count[s])
    body_size  = max(body_size, 6.0)
    h1_min = body_size * 1.6
    h2_min = body_size * 1.35
    h3_min = body_size * 1.15

    log.debug(
        "Font-based section: body=%.1f | H1>=%.1f | H2>=%.1f | H3>=%.1f",
        body_size, h1_min, h2_min, h3_min,
    )

    # Bước 2: Tìm headings trên từng trang
    section_map: dict[int, str] = {}
    heading_stack: list[tuple[int, str]] = []

    for page_idx in range(len(doc)):
        page_num = page_idx + 1
        try:
            page   = doc[page_idx]
            blocks = page.get_text("dict")["blocks"]
        except Exception:
            continue

        for block in blocks:
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            if not lines or len(lines) > 3:
                continue

            # Thu thập text và max_size của block
            block_text = ""
            max_size   = 0.0
            is_bold    = False
            for line in lines:
                for span in line.get("spans", []):
                    block_text += span.get("text", "")
                    sz = span.get("size", 0.0)
                    if sz > max_size:
                        max_size = sz
                    flags = span.get("flags", 0)
                    font  = span.get("font", "")
                    if (flags & 16) or "Bold" in font:
                        is_bold = True

            block_text = block_text.strip()
            if not block_text or len(block_text) < 3 or len(block_text) > 200:
                continue
            if block_text.isdigit():
                continue

            # Xác định level
            if max_size >= h1_min:
                level = 1
            elif max_size >= h2_min:
                level = 2
            elif max_size >= h3_min or (is_bold and max_size >= body_size):
                level = 3
            else:
                continue

            # Cập nhật heading stack
            heading_stack = [(l, t) for l, t in heading_stack if l < level]
            heading_stack.append((level, block_text))
            section_path = " > ".join(t for _, t in heading_stack)
            section_map[page_num] = section_path

    return section_map


# ─── Page-level postprocessing ────────────────────────────────────────────────

def postprocess_page_markdown(
    markdown: str,
    repeated_strings: set[str],
) -> str:
    """Áp dụng toàn bộ bước hậu xử lý cho markdown của 1 trang."""
    markdown = filter_repeated_strings(markdown, repeated_strings)
    markdown = repair_hyphenation(markdown)
    markdown = merge_split_paragraphs(markdown)
    markdown = normalize_whitespace(markdown)
    return markdown


# ─── Document-level postprocessing ───────────────────────────────────────────

def postprocess_document(
    pages_markdown: list[str],
    doc: fitz.Document,
    doc_name: str,
) -> tuple[list[str], dict]:
    """
    Hậu xử lý cấp tài liệu.

    Args:
        pages_markdown: Danh sách markdown thô theo trang (index 0 = trang 1).
        doc: fitz.Document đang mở.
        doc_name: Tên file (dùng trong log).

    Returns:
        (processed_pages, metadata_dict)
        - processed_pages: Danh sách markdown đã xử lý.
        - metadata_dict: {"section_map", "references_page", "repeated_strings"}.
    """
    log.info("[%s] Bắt đầu hậu xử lý %d trang...", doc_name, len(pages_markdown))

    # 1. Tìm header/footer lặp lại
    repeated = find_repeated_strings(pages_markdown)
    if repeated:
        log.debug("Header/footer lặp lại: %s", repeated)

    # 2. Tìm trang References
    refs_page = find_references_page(pages_markdown)
    if refs_page:
        log.info("[%s] Phần References bắt đầu từ trang %d", doc_name, refs_page)

    # 3. Xây dựng section map (TOC hoặc font-based fallback)
    section_map = build_section_map(doc)
    has_sections = any(v for v in section_map.values())
    log.debug(
        "[%s] Section map: %d entries, has_content=%s",
        doc_name, len(section_map), has_sections,
    )

    # 4. Xử lý từng trang
    processed: list[str] = []
    for i, md in enumerate(pages_markdown):
        page_num = i + 1

        # Hậu xử lý text
        clean_md = postprocess_page_markdown(md, repeated)

        # Thêm ghi chú references
        if refs_page and page_num >= refs_page:
            clean_md = f"<!-- references section -->\n\n{clean_md}"

        # Ghép section heading vào đầu trang (nếu có và trang đó bắt đầu section mới)
        section = section_map.get(page_num, "")
        if section and section_map.get(page_num) != section_map.get(page_num - 1):
            clean_md = f"<!-- section: {section} -->\n\n{clean_md}"

        processed.append(clean_md)

    metadata = {
        "section_map":      section_map,
        "references_page":  refs_page,
        "repeated_strings": list(repeated),
    }

    log.info("[%s] Hoàn thành hậu xử lý.", doc_name)
    return processed, metadata
