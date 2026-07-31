"""
postprocessor.py — Hậu xử lý văn bản sau khi đã thu thập từ tất cả blocks.

Các bước xử lý:
  1. Sửa lỗi gạch nối cuối dòng (hyphenation repair).
  2. Chuẩn hóa khoảng trắng và newlines.
  3. Phát hiện và đánh dấu phần References.
  4. Gắn section path từ TOC (nếu có).
"""

from __future__ import annotations

import re
import logging
from collections import Counter
from pathlib import Path

import fitz

from .config import REFERENCES_LOOKBACK_PAGES

log = logging.getLogger(__name__)


# ─── Hyphenation repair ───────────────────────────────────────────────────────

_HYPHEN_EOL = re.compile(r"(\w{3,})-\s*\n\s*([a-z])")
_SOFT_WRAP  = re.compile(r"([a-z,;:])[ \t]*\n[ \t]*([a-z])")
_MULTI_NL   = re.compile(r"\n{3,}")
_TRAIL_WS   = re.compile(r"[ \t]+$", re.MULTILINE)


def repair_hyphenation(text: str) -> str:
    """
    Sửa lỗi từ bị ngắt dòng bằng gạch nối (hyphenation artifact từ PDF).

    Ví dụ:
        "auto-regres-\nsive" → "autoregressive"
        "represen-\ntation" → "representation"
    """
    text = _HYPHEN_EOL.sub(r"\1\2", text)
    text = _SOFT_WRAP.sub(r"\1 \2", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Chuẩn hóa khoảng trắng thừa."""
    text = _TRAIL_WS.sub("", text)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()


# ─── Repeated header/footer detection ────────────────────────────────────────

def find_repeated_strings(pages_text: list[str], min_pages: int = 4) -> set[str]:
    """
    Tìm các chuỗi xuất hiện lặp lại ở đầu/cuối nhiều trang → header/footer.

    Được dùng để lọc ra các dòng như "Deep Learning" (tên sách) hoặc số trang.
    """
    counter: Counter[str] = Counter()
    for text in pages_text:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        # Chỉ kiểm tra 2 dòng đầu và 2 dòng cuối
        candidates = lines[:2] + lines[-2:]
        for c in candidates:
            if 3 < len(c) <= 80 and len(c.split()) <= 10:
                counter[c] += 1
    return {t for t, cnt in counter.items() if cnt >= min_pages}


def filter_repeated_strings(text: str, repeated: set[str]) -> str:
    """Lọc bỏ các dòng header/footer lặp lại khỏi text."""
    if not repeated:
        return text
    lines  = text.splitlines()
    kept   = [l for l in lines if l.strip() not in repeated]
    return "\n".join(kept)


# ─── References detection ─────────────────────────────────────────────────────

_REFERENCE_PATTERNS = [
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


# ─── TOC section map ──────────────────────────────────────────────────────────

def build_section_map(doc: fitz.Document) -> dict[int, str]:
    """
    Xây dựng mapping page_num → section_path từ TOC (Table of Contents).

    Ví dụ: {3: "Introduction", 5: "Methods > Dataset", 8: "Methods > Training"}
    """
    toc = doc.get_toc()
    section_map: dict[int, str] = {}
    stack: list[tuple[int, str]] = []

    for level, title, page in toc:
        stack = [(l, t) for l, t in stack if l < level]
        stack.append((level, title))
        section_map[page] = " > ".join(t for _, t in stack)

    # Điền forward cho các trang không có TOC entry
    current = ""
    result: dict[int, str] = {}
    for pg in range(1, len(doc) + 1):
        if pg in section_map:
            current = section_map[pg]
        result[pg] = current

    return result


# ─── Page-level postprocessing ────────────────────────────────────────────────

def postprocess_page_markdown(
    markdown: str,
    repeated_strings: set[str],
) -> str:
    """
    Áp dụng toàn bộ bước hậu xử lý cho markdown của 1 trang.
    """
    markdown = filter_repeated_strings(markdown, repeated_strings)
    markdown = repair_hyphenation(markdown)
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
        - metadata_dict: {"section_map", "references_page"}.
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

    # 3. Xây dựng section map từ TOC
    section_map = build_section_map(doc)

    # 4. Xử lý từng trang
    processed: list[str] = []
    for i, md in enumerate(pages_markdown):
        page_num = i + 1

        # Thêm header section nếu có TOC
        section = section_map.get(page_num, "")

        # Hậu xử lý text
        clean_md = postprocess_page_markdown(md, repeated)

        # Thêm ghi chú references
        if refs_page and page_num >= refs_page:
            clean_md = f"<!-- references section -->\n\n{clean_md}"

        # Ghép section heading vào đầu trang (nếu có và trang đó bắt đầu section mới)
        if section and section_map.get(page_num) != section_map.get(page_num - 1):
            clean_md = f"<!-- section: {section} -->\n\n{clean_md}"

        processed.append(clean_md)

    metadata = {
        "section_map":     section_map,
        "references_page": refs_page,
        "repeated_strings": list(repeated),
    }

    log.info("[%s] Hoàn thành hậu xử lý.", doc_name)
    return processed, metadata
